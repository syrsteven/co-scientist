"""Loopback-only W0-T4 HTTP page. GET never executes or recovers a Run."""

import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .background import BackgroundService
from .background_ops import DevelopmentReadingAdapter
from .europe_pmc import public_http
from .generation import GenerationService
from .generation_migration import MigrationService
from .generation_ops import DevelopmentGenerationAdapter
from .goal import DEVELOPMENT_POLICY, DevelopmentAdapter, GoalSlice, validate_brief
from .literature_runtime import LiteratureService
from .reading_model import OpenAIChat, load_credential
from .responses_model import OpenAIResponses
from .store import Store


def make_server(
    store,
    *,
    port=0,
    development_test=False,
    public_literature=False,
    literature_transport=public_http,
    reading_adapter=None,
    generation_adapter=None,
):
    service = GoalSlice(
        store, DevelopmentAdapter() if development_test else None, development_test=development_test
    )

    literature = LiteratureService(store, enabled=public_literature, transport=literature_transport)

    background = BackgroundService(store, reading_adapter)
    generation = GenerationService(store, generation_adapter)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # Do not print user text, requests or raw model errors.

        def reply(self, status, value, content_type="application/json; charset=utf-8"):
            data = (
                value
                if isinstance(value, bytes)
                else json.dumps(value, ensure_ascii=False).encode()
            )
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'",
            )
            self.end_headers()
            self.wfile.write(data)

        def allowed_origin(self):
            expected = f"127.0.0.1:{self.server.server_port}"
            if self.headers.get("Host") != expected:
                raise ValueError("Use the loopback URL printed by this server")
            origin = self.headers.get("Origin")
            if origin is not None and origin != "http://" + expected:
                raise ValueError("Cross-origin writes are not supported")

        def do_GET(self):
            try:
                self.allowed_origin()
                parsed = urlsplit(self.path)
                path = parsed.path
                if path in ("/", "/app.js", "/app.css", "/background.js", "/generation.js"):
                    asset, mime = {
                        "/": ("index.html", "text/html"),
                        "/app.js": ("app.js", "text/javascript"),
                        "/background.js": ("background.js", "text/javascript"),
                        "/generation.js": ("generation.js", "text/javascript"),
                        "/app.css": ("app.css", "text/css"),
                    }[path]
                    self.reply(
                        200,
                        files("co_scientist_next").joinpath("frontend", asset).read_bytes(),
                        mime + "; charset=utf-8",
                    )
                elif path == "/api/config":
                    self.reply(
                        200,
                        {
                            "development_test": development_test,
                            "real_adapter_connected": False,
                            "reading_model": background.config(),
                            "generation_model": generation.config(),
                            "public_literature_enabled": public_literature,
                            "example_policy": DEVELOPMENT_POLICY if development_test else None,
                        },
                    )
                elif path == "/api/projects":
                    self.reply(200, store.rows("SELECT * FROM projects ORDER BY created_at DESC"))
                elif path == "/api/project":
                    project = store.one(
                        "SELECT * FROM projects WHERE id=?", (parse_qs(parsed.query)["id"][0],)
                    )
                    revisions = store.rows(
                        "SELECT * FROM brief_revisions WHERE project_id=? ORDER BY created_at DESC",
                        (project["id"],),
                    )
                    runs = store.rows(
                        "SELECT r.* FROM runs r JOIN goal_run_config c ON c.run_id=r.id WHERE r.project_id=? ORDER BY r.created_at DESC",
                        (project["id"],),
                    )
                    self.reply(
                        200,
                        {
                            "project": project,
                            "revisions": [
                                {**r, "content": json.loads(r["content"])} for r in revisions
                            ],
                            "runs": runs,
                        },
                    )
                elif path == "/api/generation":
                    self.reply(200, generation.snapshot(parse_qs(parsed.query)["run_id"][0]))
                elif path == "/api/generation/attempt":
                    self.reply(
                        200,
                        store.one(
                            "SELECT p.* FROM attempts p JOIN generation_actions a ON a.task_id=p.task_id WHERE p.id=?",
                            (parse_qs(parsed.query)["attempt_id"][0],),
                        ),
                    )
                elif path == "/api/background":
                    self.reply(200, background.snapshot(parse_qs(parsed.query)["run_id"][0]))
                elif path == "/api/background/attempt":
                    attempt = store.one(
                        """SELECT p.* FROM attempts p JOIN background_actions a ON a.task_id=p.task_id
                        WHERE p.id=?""",
                        (parse_qs(parsed.query)["attempt_id"][0],),
                    )
                    self.reply(200, attempt)
                elif path == "/api/literature/response":
                    attempt = store.one(
                        """SELECT p.* FROM attempts p JOIN literature_actions a
                        ON a.task_id=p.task_id WHERE p.id=?""",
                        (parse_qs(parsed.query)["attempt_id"][0],),
                    )
                    self.reply(
                        200,
                        {
                            **attempt,
                            "request": json.loads(attempt["request"]),
                            "response": json.loads(attempt["response"])
                            if attempt["response"]
                            else None,
                        },
                    )
                elif path == "/api/literature":
                    self.reply(200, literature.history(parse_qs(parsed.query)["run_id"][0]))
                elif path == "/api/run":
                    self.reply(200, service.snapshot(parse_qs(parsed.query)["id"][0]))
                else:
                    self.reply(404, {"error": "Not found"})
            except (KeyError, ValueError) as exc:
                self.reply(400, {"error": str(exc)})

        def do_POST(self):
            try:
                self.allowed_origin()
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 200_000:
                    raise ValueError("Request must contain at most 200 KB of JSON")
                if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    raise ValueError("JSON request required")
                data = json.loads(self.rfile.read(size))
                path = urlsplit(self.path).path
                if path == "/api/brief":
                    validate_brief(data["brief"])
                    project_id = data.get("project_id")
                    if project_id is None:
                        name = data.get("name", "").strip()
                        if not name:
                            raise ValueError("Project name required")
                        project_id = store.create_project(name)
                    revision = store.revise_brief(
                        project_id, data["brief"], data.get("previous_revision_id")
                    )
                    self.reply(201, {"project_id": project_id, "revision_id": revision})
                elif path == "/api/runs":
                    run = service.create_run(
                        data["revision_id"],
                        data.get("policy"),
                        scenario=data.get("scenario", "pass"),
                    )
                    self.reply(201, {"run_id": run})
                elif path == "/api/execute":
                    # POST is explicit. Loading /api/run does not reach this operation.
                    if store.tasks(data["run_id"])[-1]["module"].startswith(
                        ("literature.", "background.", "generation.")
                    ):
                        raise ValueError("Use the explicit literature action recovery endpoint")
                    service.execute(data["run_id"], recover=data.get("recover") is True)
                    self.reply(200, service.snapshot(data["run_id"]))
                elif path == "/api/material-views":
                    view = background.create_view(
                        data["run_id"],
                        data["acquisition_task_id"],
                        start=data.get("start", 0),
                        end=data.get("end"),
                        reason=data.get("reason", ""),
                        seed_id=data.get("seed_id"),
                    )
                    self.reply(201, view)
                elif path == "/api/background":
                    action = background.submit(
                        data["run_id"], data["request_id"], data["operation"], data["request"]
                    )
                    self.reply(
                        201, {"request_id": action["request_id"], "task_id": action["task_id"]}
                    )
                elif path == "/api/generation":
                    saved = generation.submit(data["run_id"], data["request_id"], data["request"])
                    self.reply(
                        201, {"request_id": saved["request_id"], "task_id": saved["task_id"]}
                    )
                elif path in (
                    "/api/generation/migration/preview",
                    "/api/generation/migration/confirm",
                ):
                    if not getattr(generation.adapter, "background_responses", False):
                        raise ValueError("Explicit Responses configuration required for migration")
                    migration = MigrationService(store, generation.adapter.config)
                    if path.endswith("/preview"):
                        self.reply(200, migration.preview(data["run_id"], data["request"]))
                    else:
                        self.reply(
                            201,
                            migration.confirm(
                                data["run_id"],
                                data["request"],
                                data["preview_hash"],
                                data["acknowledgements"],
                            ),
                        )
                elif path == "/api/generation/query":
                    self.reply(200, generation.query_remote(data["request_id"]))
                elif path == "/api/generation/execute":
                    self.reply(
                        200,
                        generation.execute(
                            data["request_id"],
                            recover=data.get("recover") is True,
                            authorize_migrated_execution=data.get("authorize_migrated_execution")
                            is True,
                        ),
                    )
                elif path == "/api/background/execute":
                    self.reply(
                        200,
                        background.execute(data["request_id"], recover=data.get("recover") is True),
                    )
                elif path == "/api/background/query":
                    self.reply(
                        200,
                        background.execute_query(
                            data["run_id"],
                            data["plan_ref"],
                            data["query_index"],
                            data["request_id"],
                            literature,
                        ),
                    )
                elif path == "/api/literature":
                    action = literature.submit(data["run_id"], data["request_id"], data["request"])
                    self.reply(200, literature.execute(action["request_id"]))
                elif path == "/api/literature/execute":
                    self.reply(
                        200,
                        literature.execute(data["request_id"], recover=data.get("recover") is True),
                    )
                else:
                    self.reply(404, {"error": "Not found"})
            except (KeyError, ValueError, TypeError) as exc:
                self.reply(400, {"error": str(exc)})

    return HTTPServer(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(description="New-system Goal workspace; no paid model calls")
    parser.add_argument("--db", required=True)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--development-test",
        action="store_true",
        help="Explicit deterministic fixtures; NOT scientific validation",
    )
    parser.add_argument(
        "--public-literature",
        action="store_true",
        help="Enable explicit real public Europe PMC requests; no models",
    )
    parser.add_argument(
        "--development-reading",
        action="store_true",
        help="Explicit offline P03-P07 fixtures, not real model reading",
    )
    parser.add_argument(
        "--development-generation",
        action="store_true",
        help="Explicit deterministic P08 fixture; no real model or science validation",
    )
    parser.add_argument(
        "--generation-responses-config",
        help="Separate explicit P08 Responses background profile; no implicit migration/fallback",
    )
    parser.add_argument(
        "--reading-model-config", help="Public explicit OpenAI model/endpoint/parameters JSON"
    )
    parser.add_argument(
        "--credential-env", help="Explicitly named environment with separate model credential"
    )
    parser.add_argument(
        "--credential-file", help="Separate private JSON credential file, outside Git"
    )
    parser.add_argument(
        "--allow-real-model-calls",
        action="store_true",
        help="Explicitly authorize model sends only when operations are clicked",
    )
    args = parser.parse_args()
    if args.generation_responses_config and (
        args.development_generation or args.reading_model_config or args.development_reading
    ):
        parser.error("Select a separate Responses profile; no implicit API migration")
    if args.development_reading and (
        args.reading_model_config
        or args.allow_real_model_calls
        or args.credential_env
        or args.credential_file
    ):
        parser.error("Select explicit development reading or real configuration; no fallback")
    if not (args.reading_model_config or args.generation_responses_config) and (
        args.credential_env or args.credential_file or args.allow_real_model_calls
    ):
        parser.error(
            "Explicit model configuration required; credentials/authorization alone do not select a model"
        )
    adapter = DevelopmentReadingAdapter() if args.development_reading else None
    if args.reading_model_config:
        try:
            config = json.loads(Path(args.reading_model_config).read_text())
            secret = (
                load_credential(env_name=args.credential_env, credential_file=args.credential_file)
                if args.credential_env or args.credential_file
                else None
            )
            adapter = OpenAIChat(config, secret, authorized=args.allow_real_model_calls)
        except (ValueError, OSError):
            parser.error(
                "Reading configuration/credential unavailable; no fallback or secret details printed"
            )
    generation_adapter = adapter if args.reading_model_config else None
    if args.generation_responses_config:
        try:
            config = json.loads(Path(args.generation_responses_config).read_text())
            secret = (
                load_credential(env_name=args.credential_env, credential_file=args.credential_file)
                if args.credential_env or args.credential_file
                else None
            )
            generation_adapter = OpenAIResponses(
                config, secret, authorized=args.allow_real_model_calls
            )
        except (ValueError, OSError):
            parser.error(
                "Responses configuration/credential unavailable; no fallback or secret details printed"
            )
    with Store(args.db) as store:
        server = make_server(
            store,
            port=args.port,
            development_test=args.development_test,
            public_literature=args.public_literature,
            reading_adapter=adapter,
            generation_adapter=(
                DevelopmentGenerationAdapter()
                if args.development_generation
                else generation_adapter
            ),
        )
        # No store.recover() here. Restart and refresh are observational until explicit POST.
        print(
            f"http://127.0.0.1:{server.server_port} | development_test={args.development_test} | goal_real_adapter_connected=False | reading_mode={adapter.execution_mode if adapter else 'not_configured'}",
            flush=True,
        )
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()


if __name__ == "__main__":
    main()
