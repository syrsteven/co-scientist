"""Loopback-only W0-T4 HTTP page. GET never executes or recovers a Run."""

import argparse
import base64
import hashlib
import json
import re
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from threading import Lock
from urllib.parse import parse_qs, urlsplit

from .background import BackgroundService
from .background_ops import DevelopmentReadingAdapter
from .candidate_review import CandidateReviewService
from .candidate_review_ops import (
    DEVELOPMENT_DECISIONS,
    DEVELOPMENT_R0_POLICY,
    DevelopmentReviewAdapter,
)
from .candidate_review_ops import (
    DEVELOPMENT_POLICY as REVIEW_POLICY,
)
from .europe_pmc import public_http
from .generation import GenerationService
from .generation_migration import MigrationService, ReadOnlyStore
from .generation_ops import DevelopmentGenerationAdapter
from .goal import DEVELOPMENT_POLICY, DevelopmentAdapter, GoalSlice, validate_brief
from .literature_runtime import LiteratureService
from .reading_model import OpenAIChat, load_credential
from .responses_model import OpenAIResponses
from .store import Store
from .workspace_records import WorkspaceRecords


def make_server(
    store,
    *,
    port=0,
    development_test=False,
    public_literature=False,
    literature_transport=public_http,
    reading_adapter=None,
    generation_adapter=None,
    review_adapter=None,
    development_review=False,
    require_goal_test_opt_in=False,
    responsive=False,
    history_db=None,
    literature_mode="real_public",
    automatic_research=False,
    offline_start_response_loss=False,
    goal_adapter=None,
    allow_development_goal_policy=False,
):
    database_path = store.one("PRAGMA database_list")["file"]
    if history_db and Path(history_db).resolve() == Path(database_path).resolve():
        raise ValueError("History and stage databases must be separate")
    if responsive and not getattr(store, "http_threads", False):
        raise ValueError("Responsive server requires explicitly serialized HTTP Store threads")
    write_lock = Lock()
    service = GoalSlice(
        store, DevelopmentAdapter() if development_test else goal_adapter, development_test=development_test, allow_development_policy=allow_development_goal_policy
    )

    literature = LiteratureService(store, enabled=public_literature, transport=literature_transport)

    background = BackgroundService(store, reading_adapter)
    generation = GenerationService(store, generation_adapter)
    reviews = CandidateReviewService(store, review_adapter, development=development_review)

    controller = None
    if automatic_research:
        if not responsive:
            raise ValueError("Automatic controller requires responsive serialized runtime")
        from .research import ResearchController
        controller = ResearchController(store, service, background, literature, generation, reviews)
        controller.initialize()

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
                (
                    "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:; connect-src 'none'; frame-ancestors 'self'; form-action 'none'"
                    if urlsplit(self.path).path == "/history.html"
                    else ("default-src 'none'; style-src 'unsafe-inline'; script-src " + ' '.join("'sha256-" + base64.b64encode(hashlib.sha256(script).digest()).decode() + "'" for script in re.findall(rb'<script[^>]*>(.*?)</script>', data, re.DOTALL)) + "; img-src data:; connect-src 'none'; frame-src 'self' blob:; form-action 'none'" )
                    if urlsplit(self.path).path == '/design-reference' and development_test
                    else "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'"
                ),
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
            with ReadOnlyStore(database_path) as snapshot:
                snapshot.db.execute("BEGIN")
                self.read_get(snapshot)

        def read_get(self, store):
            service = GoalSlice(store, development_test=development_test)
            literature = LiteratureService(
                store, enabled=public_literature, transport=literature_transport
            )
            background = BackgroundService(store, reading_adapter)
            generation = GenerationService(store, generation_adapter)
            reviews = CandidateReviewService(store, review_adapter, development=development_review)
            try:
                self.allowed_origin()
                parsed = urlsplit(self.path)
                path = parsed.path
                if path == "/api/projects":
                    from .research_projects import projects
                    self.reply(200, projects(store))
                    return
                if path == "/api/research/start-status":
                    key = parse_qs(parsed.query)["start_key"][0]
                    rows = store.rows("SELECT run_id,status FROM research_runs WHERE start_key=?", (key,))
                    self.reply(200, {"state": "running" if rows else "not_created", "run": rows[0] if rows else None})
                    return
                if path == "/api/research/detail":
                    params = parse_qs(parsed.query)
                    run_id, kind, ref = params['run_id'][0], params['kind'][0], params['ref'][0]
                    if kind == 'view':
                        value = json.loads(store.one('SELECT content FROM material_views WHERE run_id=? AND id=?', (run_id,ref))['content'])
                    elif kind in ('candidate','background'):
                        service_snapshot = generation.snapshot(run_id) if kind == 'candidate' else background.snapshot(run_id)
                        value = next((a for a in service_snapshot['actions'] if a['request_id'] == ref), None)
                        if value is None:
                            raise ValueError('Saved detail not found in this Run')
                    else:
                        raise ValueError('Unknown detail kind')
                    self.reply(200,value)
                    return
                if path == "/api/research/status":
                    params = parse_qs(parsed.query)
                    run_id = params["run_id"][0]
                    row = store.one("SELECT run_id,status,state,reason,updated_at FROM research_runs WHERE run_id=?", (run_id,))
                    row["state"] = json.loads(row["state"])
                    events = store.rows("SELECT * FROM research_events WHERE run_id=? AND id>? ORDER BY id LIMIT 100", (run_id, int(params.get("after", [0])[0])))
                    for event in events:
                        event["detail"] = json.loads(event["detail"])
                    marker = store.one("SELECT COUNT(*) AS results,COALESCE(MAX(applied_at),'') AS latest FROM results WHERE task_id IN (SELECT id FROM tasks WHERE run_id=?)", (run_id,))
                    self.reply(200, {"research": row, "events": events, "marker": str(marker)+row['state'].get('phase','')})
                    return
                if path == "/api/research-workspace":
                    from .research_view import summary
                    self.reply(200, summary(store, parse_qs(parsed.query)["run_id"][0]))
                    return
                if path == "/api/research-runs":
                    rows = store.rows("SELECT r.*,p.name FROM research_runs a JOIN runs r ON a.run_id=r.id JOIN projects p ON p.id=r.project_id ORDER BY r.created_at DESC") if controller else []
                    self.reply(200, rows)
                    return
                if path == '/design-reference' and development_test:
                    reference = Path(__file__).resolve().parents[2] / 'docs/design/workspace-journey-user-provided/co_scientist_v6_research_journey_REBUILT.html'
                    self.reply(200, reference.read_bytes(), 'text/html; charset=utf-8')
                    return
                if path == "/reader.js":
                    raw=files("co_scientist_next").joinpath("frontend", "workbench.js").read_text()
                    self.reply(200, raw.split("// Live data only.")[0].encode(), "text/javascript")
                    return
                if path in (
                    "/",
                    "/app.js",
                    "/app.css",
                    "/background.js",
                    "/generation.js",
                    "/candidate-review.js",
                    "/workbench.js",
                    "/workbench.css",
                    "/history.html",
                    "/journey.js", "/journey.css", "/journey", "/manual",
                ):
                    asset, mime = {
                        "/": ("journey.html" if controller else "index.html", "text/html"),
                        "/manual": ("index.html", "text/html"),
                        "/journey": ("journey.html", "text/html"),
                        "/journey.js": ("journey.js", "text/javascript"),
                        "/journey.css": ("journey.css", "text/css"),
                        "/app.js": ("app.js", "text/javascript"),
                        "/background.js": ("background.js", "text/javascript"),
                        "/generation.js": ("generation.js", "text/javascript"),
                        "/candidate-review.js": ("candidate-review.js", "text/javascript"),
                        "/app.css": ("app.css", "text/css"),
                        "/workbench.js": ("workbench.js", "text/javascript"),
                        "/workbench.css": ("workbench.css", "text/css"),
                        "/history.html": ("history.html", "text/html"),
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
                            "automatic_research": automatic_research,
                            "policy_choices": __import__("co_scientist_next.policy_catalog", fromlist=["choices"]).choices(development_test),
                            "research_policies": {"goal": DEVELOPMENT_POLICY, "candidate": REVIEW_POLICY, "decision_policy": DEVELOPMENT_DECISIONS, "r0": DEVELOPMENT_R0_POLICY} if development_test else __import__("co_scientist_next.research_policies", fromlist=["POLICIES"]).POLICIES,
                            "research_defaults": __import__("co_scientist_next.research_config", fromlist=["DEFAULTS"]).DEFAULTS,
                            "goal_model": controller.profiles()["goal"] if controller else {"execution_mode":"development_fixture" if development_test else "not_configured"},
                            "development_test": development_test,
                            "real_adapter_connected": False,
                            "reading_model": background.config(),
                            "generation_model": generation.config(),
                            "public_literature_enabled": public_literature,
                            "literature_execution_mode": literature_mode
                            if public_literature
                            else "not_configured",
                            "review_model": reviews.config(),
                            "review_development_policy_allowed": development_review,
                            "module_authorization": {
                                "reading": bool(
                                    reading_adapter
                                    and getattr(reading_adapter, "authorized", False)
                                ),
                                "generation": bool(
                                    generation_adapter and generation_adapter.authorized
                                ),
                                "review": bool(
                                    review_adapter and getattr(review_adapter, "authorized", False)
                                ),
                            },
                            "goal_test_opt_in_required": require_goal_test_opt_in,
                            "history_available": bool(history_db and Path(history_db).is_file()),
                            "production_policy_default": False,
                            "development_review_templates": {
                                "ethics": REVIEW_POLICY,
                                "decisions": DEVELOPMENT_DECISIONS,
                                "r0": DEVELOPMENT_R0_POLICY,
                            }
                            if development_review
                            else None,
                            "example_policy": DEVELOPMENT_POLICY if development_test else None,
                        },
                    )
                elif path == "/api/annotations":
                    run_id = parse_qs(parsed.query)["run_id"][0]
                    records = WorkspaceRecords(store)
                    self.reply(
                        200,
                        {
                            "records": records.list(run_id),
                            "targets": records.targets(run_id),
                            "automatically_in_model_input": False,
                        },
                    )
                elif path == "/api/export":
                    self.reply(
                        200, WorkspaceRecords(store).export(parse_qs(parsed.query)["run_id"][0])
                    )
                elif path == "/api/history":
                    if not history_db:
                        raise ValueError("No read-only historical record configured")
                    with ReadOnlyStore(history_db) as historical:
                        historical.db.execute("BEGIN")
                        runs = historical.rows(
                            "SELECT id,status FROM runs ORDER BY created_at DESC"
                        )
                        selected = parse_qs(parsed.query).get(
                            "run_id", [runs[0]["id"] if runs else None]
                        )[0]
                        self.reply(
                            200,
                            {
                                "read_only": True,
                                "runs": runs,
                                "export": WorkspaceRecords(historical).export(selected)
                                if selected
                                else None,
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
                elif path == "/api/candidate-review":
                    self.reply(200, reviews.snapshot(parse_qs(parsed.query)["run_id"][0]))
                elif path == "/api/candidate-review/attempt":
                    self.reply(
                        200,
                        store.one(
                            "SELECT p.* FROM attempts p JOIN candidate_review_actions a ON a.task_id=p.task_id WHERE p.id=?",
                            (parse_qs(parsed.query)["attempt_id"][0],),
                        ),
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
            if controller and urlsplit(self.path).path == '/api/runs':
                self.reply(400, {'error': 'Use Start Research with a server-controlled policy selection'})
                return
            if urlsplit(self.path).path == "/api/annotations":
                try:
                    self.allowed_origin()
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 < size <= 30000:
                        raise ValueError("Bounded annotation JSON required")
                    data = json.loads(self.rfile.read(size))
                    from .annotation_writer import save_annotation
                    self.reply(201, save_annotation(database_path, data))
                except (ValueError, KeyError, sqlite3.Error) as exc:
                    self.reply(400, {"error": str(exc) if not isinstance(exc, sqlite3.Error) else "Local save unavailable; your draft is retained"})
                return
            if urlsplit(self.path).path in ("/api/research/control", "/api/projects/change"):
                try:
                    self.allowed_origin()
                    size=int(self.headers.get("Content-Length", "0"))
                    if not controller or not 0 < size < 4000:
                        raise ValueError("Invalid controller request")
                    data=json.loads(self.rfile.read(size))
                    with sqlite3.connect(database_path) as db:
                        if urlsplit(self.path).path == "/api/projects/change":
                            from .research_projects import change
                            scoped = Store.__new__(Store)
                            scoped.db = db
                            db.row_factory = sqlite3.Row
                            db.execute("PRAGMA foreign_keys=ON")
                            self.reply(200, change(scoped, data["project_id"], data["action"], data.get("name")))
                        else:
                            self.reply(200, controller.control(db, data["run_id"], data["action"]))
                except (ValueError, KeyError) as exc:
                    self.reply(400, {"error":str(exc)})
                return
            if not write_lock.acquire(blocking=False):
                self.reply(409, {"error": "Another scheduling operation is in progress. Read the saved launch status before retrying."})
                return
            try:
                self.write_post()
            except (BrokenPipeError, ConnectionResetError):
                pass  # Browser refresh does not cancel or resend an already recorded operation.
            finally:
                write_lock.release()

        def write_post(self):
            try:
                self.allowed_origin()
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 200_000:
                    raise ValueError("Request must contain at most 200 KB of JSON")
                if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    raise ValueError("JSON request required")
                data = json.loads(self.rfile.read(size))
                path = urlsplit(self.path).path
                if controller and path not in ("/api/research/start", "/api/brief", "/api/annotations", "/api/runs"):
                    managed_run = data.get("run_id")
                    if data.get("request_id"):
                        for table in ("background_actions", "literature_actions", "generation_actions", "candidate_review_actions"):
                            rows = store.rows("SELECT run_id FROM " + table + " WHERE request_id=?", (data["request_id"],))
                            if rows:
                                managed_run = rows[0]["run_id"]
                                break
                    if managed_run and store.rows("SELECT run_id FROM research_runs WHERE run_id=?", (managed_run,)):
                        raise ValueError("Automatic Run is controller-owned; manual submissions/recovery cannot bypass its frozen plan or stop state")
                if path == "/api/research/start":
                    if not controller or data.get("authorize_automatic_execution") is not True:
                        raise ValueError("Explicit Start authorization required")
                    if development_test and data.get("goal_test_mode") != "deterministic_development":
                        raise ValueError("Explicit isolated fixture mode choice required")
                    if "policies" in data:
                        raise ValueError("Client policy text is not accepted")
                    from .policy_catalog import resolve
                    policies = resolve(data.get("policy_selection"), development_test)
                    run=controller.start(data["revision_id"],data["start_key"],data["config"],policies,policy_selection=data["policy_selection"])
                    if development_test and offline_start_response_loss and not getattr(self.server, 'start_response_lost', False):
                        self.server.start_response_lost = True
                        self.close_connection = True
                        raise ConnectionResetError('OFFLINE lost Start response after commit')
                    self.reply(201,{"run_id":run})
                elif path == "/api/annotations":
                    self.reply(201, WorkspaceRecords(store).save(data["run_id"], data))
                elif path == "/api/brief":
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
                    if require_goal_test_opt_in and (
                        not development_test
                        or data.get("goal_test_mode") != "deterministic_development"
                    ):
                        raise ValueError(
                            "请明确选择 Goal 制备/筛查开发替身模式；不代表真实伦理审查"
                        )
                    run = service.create_run(
                        data["revision_id"],
                        data.get("policy"),
                        scenario=data.get("scenario", "pass"),
                    )
                    self.reply(201, {"run_id": run})
                elif path == "/api/execute":
                    # POST is explicit. Loading /api/run does not reach this operation.
                    if store.tasks(data["run_id"])[-1]["module"].startswith(
                        ("literature.", "background.", "generation.", "candidate_review.")
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
                elif path == "/api/candidate-review":
                    action = reviews.submit(data["run_id"], data["request_id"], data["request"])
                    self.reply(
                        201, {"task_id": action["task_id"], "request_id": action["request_id"]}
                    )
                elif path == "/api/candidate-review/execute":
                    self.reply(
                        200,
                        reviews.execute(data["request_id"], recover=data.get("recover") is True),
                    )
                elif path == "/api/candidate-review/query":
                    self.reply(200, reviews.query_remote(data["request_id"]))
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

    server = (ThreadingHTTPServer if responsive else HTTPServer)(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    server.research_controller = controller
    if controller:
        controller.start_worker(write_lock)
    return server


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
    parser.add_argument(
        "--development-review",
        action="store_true",
        help="Explicit offline Candidate Ethics/R0 fixtures and development policies only",
    )
    parser.add_argument(
        "--review-responses-config",
        help="Explicit public Responses configuration for candidate review; no default model",
    )
    parser.add_argument(
        "--allow-development-review-policy",
        action="store_true",
        help="Permit explicit nonproduction policies with a real Responses profile; does not select fixtures or authorize calls",
    )
    parser.add_argument("--require-goal-test-opt-in", action="store_true")
    parser.add_argument(
        "--responsive",
        action="store_true",
        help="One serialized writer, independent read-only GET snapshots during long calls",
    )
    parser.add_argument(
        "--history-db",
        help="Optional historical database: read-only GET/export only, never a Store",
    )
    parser.add_argument("--automatic-research", action="store_true", help="Enable explicit Start and persisted bounded controller; startup alone creates no research")
    parser.add_argument("--real-goal", action="store_true", help="Use explicitly configured reading Chat profile for actual Goal preparation/screening")
    parser.add_argument("--allow-development-goal-policy", action="store_true")
    args = parser.parse_args()
    if args.real_goal and (args.development_test or not args.reading_model_config):
        parser.error("Real Goal requires explicit reading profile and forbids development fixture fallback")
    if args.allow_development_review_policy and (
        not args.review_responses_config or args.development_review
    ):
        parser.error(
            "Nonproduction real review requires explicit review Responses profile, separate from fixture mode"
        )
    if args.development_review and (args.review_responses_config):
        parser.error("Development review cannot load model credentials or authorize real calls")
    if args.generation_responses_config and (args.development_generation):
        parser.error("Select a separate Responses profile; no implicit API migration")
    if args.development_reading and (args.reading_model_config):
        parser.error("Select explicit development reading or real configuration; no fallback")
    if not (
        args.reading_model_config
        or args.generation_responses_config
        or args.review_responses_config
    ) and (args.credential_env or args.credential_file or args.allow_real_model_calls):
        parser.error(
            "Explicit model configuration required; credentials/authorization alone do not select a model"
        )
    secret = None
    if args.credential_env or args.credential_file:
        try:
            secret = load_credential(
                env_name=args.credential_env, credential_file=args.credential_file
            )
        except (ValueError, OSError):
            secret = None
    adapter = DevelopmentReadingAdapter() if args.development_reading else None
    if args.reading_model_config:
        try:
            config = json.loads(Path(args.reading_model_config).read_text())
            adapter = OpenAIChat(config, secret, authorized=args.allow_real_model_calls)
        except (ValueError, OSError):
            parser.error(
                "Reading configuration/credential unavailable; no fallback or secret details printed"
            )
    generation_adapter = None  # Each role selects its own explicit API/configuration.
    if args.generation_responses_config:
        try:
            config = json.loads(Path(args.generation_responses_config).read_text())
            generation_adapter = OpenAIResponses(
                config, secret, authorized=args.allow_real_model_calls
            )
        except (ValueError, OSError):
            parser.error(
                "Responses configuration/credential unavailable; no fallback or secret details printed"
            )
    review_adapter = DevelopmentReviewAdapter() if args.development_review else None
    if args.review_responses_config:
        try:
            config = json.loads(Path(args.review_responses_config).read_text())
            review_adapter = OpenAIResponses(config, secret, authorized=args.allow_real_model_calls)
        except (ValueError, OSError):
            parser.error(
                "Review configuration/credential unavailable; no fallback or secret details printed"
            )
    if args.history_db and Path(args.history_db).resolve() == Path(args.db).resolve():
        parser.error("Stage database must be distinct from the read-only history database")
    with Store(args.db, http_threads=args.responsive) as store:
        server = make_server(
            store,
            port=args.port,
            automatic_research=args.automatic_research,
            goal_adapter=adapter if args.real_goal else None,
            allow_development_goal_policy=args.allow_development_goal_policy,
            development_test=args.development_test,
            public_literature=args.public_literature,
            require_goal_test_opt_in=args.require_goal_test_opt_in,
            responsive=args.responsive,
            history_db=args.history_db,
            reading_adapter=adapter,
            review_adapter=review_adapter,
            development_review=args.development_review or args.allow_development_review_policy,
            generation_adapter=(
                DevelopmentGenerationAdapter()
                if args.development_generation
                else generation_adapter
            ),
        )
        # No store.recover() here. Restart and refresh are observational until explicit POST.
        print(
            f"http://127.0.0.1:{server.server_port} | development_test={args.development_test} | goal_real_adapter_connected={args.real_goal} | reading_mode={adapter.execution_mode if adapter else 'not_configured'}",
            flush=True,
        )
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            if server.research_controller:
                server.research_controller.stop_event.set()
            server.server_close()


if __name__ == "__main__":
    main()
