"""Loopback-only W0-T4 HTTP page. GET never executes or recovers a Run."""

import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib.resources import files
from urllib.parse import parse_qs, urlsplit

from .goal import DEVELOPMENT_POLICY, DevelopmentAdapter, GoalSlice, validate_brief
from .store import Store


def make_server(store, *, port=0, development_test=False):
    service = GoalSlice(
        store, DevelopmentAdapter() if development_test else None, development_test=development_test
    )

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
                if path in ("/", "/app.js", "/app.css"):
                    asset, mime = {
                        "/": ("index.html", "text/html"),
                        "/app.js": ("app.js", "text/javascript"),
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
                    service.execute(data["run_id"], recover=data.get("recover") is True)
                    self.reply(200, service.snapshot(data["run_id"]))
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
    args = parser.parse_args()
    with Store(args.db) as store:
        server = make_server(store, port=args.port, development_test=args.development_test)
        # No store.recover() here. Restart and refresh are observational until explicit POST.
        print(
            f"http://127.0.0.1:{server.server_port} | development_test={args.development_test} | real_adapter_connected=False",
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
