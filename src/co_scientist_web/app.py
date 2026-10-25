"""Authenticated, loopback-only HTTP boundary over the native DEV runtime."""

import asyncio
import hashlib
import io
import json
import re
import secrets
import sqlite3
import tempfile
import time
import zipfile
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import Field, SecretStr, StrictBool
from starlette.concurrency import run_in_threadpool

from co_scientist import __version__
from co_scientist.adapters.artifacts.filesystem import FilesystemArtifactStore
from co_scientist.domain.research_protocol import protocol_hash
from co_scientist.release.resources import package_file, resource_path
from co_scientist.release.service import RunService, budget, code_identity, load
from co_scientist.runtime.ideation_trace import trace_documents
from co_scientist.runtime.trace_snapshot import readonly_uow

from .configuration import Draft, Runtime, Strict, diagnostics
from .diagnostics import Diagnostics, exception_detail, request_id, tail
from .jobs import TERMINAL, driver_alive, launch
from .monitor import event_page, monitor_page
from .store import Store, identifier
from .views import candidates, source_records

FRONTEND = Path(__file__).parent / "frontend"
TRACE_FILES = {
    "run-timeline.json",
    "candidates.json",
    "ranking-history.json",
    "evolution-tree.json",
    "ideation-report.md",
}


class Project(Strict):
    title: str = Field(min_length=1, max_length=150)
    description: str = Field(default="", max_length=2000)


class Create(Strict):
    preflight_id: str


class Approve(Strict):
    confirm: StrictBool
    accept_usd: str
    confirm_pricing: StrictBool = False
    accept_unknown_risk: StrictBool = False


class Credential(Strict):
    key: SecretStr = Field(min_length=1, max_length=8192)


class Contact(Strict):
    email: str = Field(max_length=254)


class Resume(Strict):
    confirm_execution: StrictBool = False


def create_app(data_root, *, allow_live=False, log_level="INFO", observer=None):
    store = Store(data_root)
    log = observer or Diagnostics(store.path("logs", "workbench.jsonl"), level=log_level)

    @asynccontextmanager
    async def lifespan(app):
        log.emit("web.application_ready", phase="startup", live_enabled=allow_live)
        try:
            yield
        finally:
            log.emit("web.application_stopping", phase="shutdown")

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    session, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    credentials = {}  # Only in this server process; never persisted.
    contact = {"email": ""}
    app.state.store = store
    app.state.launch = launch
    app.state.diagnostics = log
    app.state.log_level = log_level
    store.diagnostics = log
    store.log_level = log_level
    log.emit("web.configured", phase="startup", live_enabled=allow_live)

    def failed(request, error, code, status, **content):
        error_id = log.error(error, phase=request.scope.get("route").name
                             if request.scope.get("route") else "http",
                             run_id=observed_run(request), code=code)
        return JSONResponse({"error": code, "error_id": error_id, **content}, status)

    def observed_run(request):
        key = request.path_params.get("key", "")
        return key if re.fullmatch(r"ideation-g3-[0-9]{8}-[a-f0-9]{32}", key) else None

    def service(mode="MOCK_ONLY"):
        env = (
            {}
            if mode == "MOCK_ONLY"
            else {
                "OPENAI_API_KEY": credentials.get("openai", ""),
                "DEEPSEEK_API_KEY": credentials.get("deepseek", ""),
                "CO_SCIENTIST_PUBMED_EMAIL": contact["email"],
            }
        )
        return RunService(environment=env)

    def info(key):
        record = store.get("run", key)
        return record, store.run_root(key)

    def observe(root):
        try:
            return service().status(root)
        except sqlite3.OperationalError:
            if not driver_alive(root):
                raise ValueError("native database needs inspection") from None
            plan = load(root / "plan.json")
            return {
                "run_id": plan["run_id"],
                "state": "initializing",
                "events": 0,
                "limits": plan["limits"],
            }

    def observed_events(root, after):
        if observe(root)["state"] in {"prepared", "initializing"}:
            return []
        return service().events(root, after=after)

    def native_documents(key):
        _, root = info(key)
        native = service()
        native._verify(root)
        if observe(root)["state"] in {"prepared", "initializing"}:
            raise HTTPException(409, "Run 尚未启动，无原生快照")
        with readonly_uow(root / "runtime/co-scientist.db") as uow:
            return trace_documents(
                uow,
                FilesystemArtifactStore(root / "runtime/artifacts"),
                key,
                transport_artifacts=FilesystemArtifactStore(
                    root / "runtime/dispatch" / key / "artifacts"
                ),
            )

    @app.middleware("http")
    async def security(request, call_next):
        host = request.headers.get("host", "")
        if not re.fullmatch(r"(?:127\.0\.0\.1|localhost)(?::[0-9]{1,5})?", host):
            return JSONResponse({"error": "untrusted host"}, 403)
        origin = request.headers.get("origin")
        if origin is not None and origin != f"http://{host}":
            return JSONResponse({"error": "origin rejected"}, 403)
        if request.url.path.startswith("/api/"):
            if not secrets.compare_digest(request.cookies.get("wb_session", ""), session):
                return JSONResponse({"error": "reload trusted local Workbench"}, 403)
            if request.method not in {"GET", "HEAD"} and (
                origin != f"http://{host}"
                or not secrets.compare_digest(request.headers.get("x-csrf-token", ""), csrf)
            ):
                return JSONResponse({"error": "CSRF rejected"}, 403)
            if int(request.headers.get("content-length", "0")) > 300000:
                return JSONResponse({"error": "request too large"}, 413)
        response = await call_next(request)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'",
                "Referrer-Policy": "no-referrer",
            }
        )
        return response

    @app.middleware("http")
    async def observation(request, call_next):
        # Never trust incoming correlation IDs or log raw paths/query/headers.
        rid = "req-" + secrets.token_hex(16)
        request.state.request_id = rid
        context = request_id.set(rid)
        started = time.monotonic()
        try:
            try:
                response = await call_next(request)
            except Exception as error:  # noqa: BLE001 -- safe metadata, no automatic retry
                response = failed(request, error, "BACKEND_OPERATION_FAILED", 500)
            response.headers["X-Request-ID"] = rid
            route = request.scope.get("route")
            level = "WARNING" if response.status_code >= 400 else (
                "DEBUG" if request.method == "GET" else "INFO")
            log.emit("http.completed", level=level,
                     route=route.path if route else "unmatched", method=request.method,
                     run_id=observed_run(request), status=response.status_code,
                     duration_ms=round((time.monotonic() - started) * 1000))
            return response
        finally:
            request_id.reset(context)

    @app.exception_handler(RequestValidationError)
    async def validation(request, error):
        # Error locations may contain arbitrary JSON keys; do not echo them.
        return failed(request, error, "invalid request", 422,
                      diagnostics=[{"code": e["type"]} for e in error.errors()])

    @app.exception_handler(ValueError)
    async def conflict(request, error):
        # Never serialize arbitrary native/provider exception bodies or keys.
        text = str(error)
        code = (
            "SNAPSHOT_BUSY"
            if "snapshot" in text or "overwrite" in text
            else "IDENTITY_OR_CONFIG_CONFLICT"
        )
        return failed(request, error, code, 409,
                      message="快照忙请稍后重试；身份不符的旧 Run 请使用原版本环境。")

    @app.exception_handler(KeyError)
    async def missing(request, error):
        return failed(request, error, "unknown logical identifier", 404)

    @app.exception_handler(Exception)
    async def failure(request, error):
        return failed(request, error, "local backend operation failed; no automatic retry", 500)

    @app.exception_handler(HTTPException)
    async def http_failure(request, error):
        return failed(request, error, "HTTP_OPERATION_REJECTED", error.status_code)

    @app.get("/")
    async def index():
        response = FileResponse(FRONTEND / "index.html")
        response.set_cookie("wb_session", session, httponly=True, samesite="strict")
        return response

    @app.get("/assets/{name}")
    async def asset(name: str):
        if name not in {"styles.css", "fixture.js", "app.js", "workbench.js", "backend.js"}:
            raise HTTPException(404)
        return FileResponse(FRONTEND / name)

    @app.get("/api/v1/session")
    async def bootstrap():
        return {"csrf_token": csrf}

    @app.get("/api/v1/health")
    def health():
        checks = {}
        for name in ("deepseek-v41.json", "o200k_base.tiktoken"):
            try:
                resource_path("resource:" + name)
                checks[name] = "ready"
            except ValueError:
                checks[name] = "missing_or_invalid: explicit resources install required"
        return {
            "backend_connected": True,
            "release": __version__,
            "resources": checks,
            "live_enabled": allow_live,
            "code_identity": code_identity(),
        }

    @app.get("/api/v1/projects")
    def projects():
        return store.list("project")

    @app.post("/api/v1/projects")
    def add_project(body: Project):
        return store.save("project", body.model_dump())

    @app.get("/api/v1/projects/{key}")
    def project(key: str):
        return store.get("project", key)

    @app.patch("/api/v1/projects/{key}")
    def edit_project(key: str, body: Project):
        store.get("project", key)
        return store.save("project", body.model_dump(), key)

    @app.get("/api/v1/drafts")
    def drafts():
        return store.list("draft")

    @app.post("/api/v1/drafts")
    def save_draft(body: Draft):
        if body.project_id:
            store.get("project", body.project_id)
        return store.save("draft", body.model_dump())

    @app.patch("/api/v1/drafts/{key}")
    def update_draft(key: str, body: Draft):
        store.get("draft", key)
        if body.project_id:
            store.get("project", body.project_id)
        return store.save("draft", body.model_dump(), key)

    @app.get("/api/v1/config/defaults")
    def defaults():
        return {
            "version": "web-config-builder-v1",
            "run_config": Runtime().model_dump(),
            "profile_sha256": hashlib.sha256(package_file("g3.yaml").read_bytes()).hexdigest(),
            "custom_execution": "BLOCKED_UNTIL_FULL_MOCK_VALIDATED",
        }

    @app.get("/api/v1/config/models")
    def models():
        return {
            "account_access": "UNVERIFIED_NO_NETWORK",
            "models": [
                {"id": "gpt-6.1-sol", "role": "generation", "adapted": True},
                {"id": "deepseek-flash", "role": "review_evolution", "adapted": True},
                *[
                    {"id": m, "adapted": False, "reason": "UNVALIDATED_CONFIGURATION"}
                    for m in (
                        "gpt-6-astra",
                        "gpt-5.6-sol",
                        "gpt-5.6-terra",
                        "gpt-5.6-luna",
                        "gpt-5.5",
                        "deepseek-v4-pro",
                    )
                ],
            ],
        }

    @app.post("/api/v1/config/preflight")
    def preflight(body: Draft):
        log.emit("preflight.started", phase="preflight")
        error_id = None
        errors = diagnostics(body)
        if body.project_id:
            store.get("project", body.project_id)
        if body.mode == "LIVE_SINGLE_DISPATCH" and not (
            credentials.get("openai") and credentials.get("deepseek") and contact["email"]
        ):
            errors.append({"field": "settings", "code": "MISSING_CREDENTIALS_OR_EMAIL"})
        manifest = None
        if not errors:
            with tempfile.TemporaryDirectory(prefix="wb-preflight-") as folder:
                goal = Path(folder) / "goal.json"
                goal.write_text(body.goal.model_dump_json(), encoding="utf-8")
                try:
                    manifest = service(body.mode).validate(goal)
                except (ValueError, FileNotFoundError) as error:
                    error_id = log.error(error, phase="preflight", code="NATIVE_PREFLIGHT_REJECTED")
                    hint = exception_detail(error).get("hint")
                    errors.append(
                        {
                            "field": "resources_or_goal",
                            "code": "NATIVE_PREFLIGHT_REJECTED",
                            "message": "请检查研究目标和 tokenizer；显式安装资源，不会自动下载。",
                            "hint": hint,
                        }
                    )
        if errors:
            if error_id is None:
                error_id = "err-" + secrets.token_hex(16)
                log.emit("preflight.rejected", level="WARNING", phase="preflight",
                         error_id=error_id, code="CONFIGURATION_REJECTED")
            return JSONResponse({"runner_compatible": False, "diagnostics": errors,
                                 "error_id": error_id}, 422)
        limits = budget(manifest)
        digest = protocol_hash(
            {
                "revision": "web-config-builder-v1",
                "draft": body.model_dump(),
                "manifest": manifest,
                "code_identity": code_identity(),
            }
        )
        saved = store.save(
            "preflight",
            {"draft": body.model_dump(), "hash": digest, "code_identity": code_identity()},
        )
        log.emit("preflight.passed", phase="preflight")
        return {
            "preflight_id": saved["id"],
            "configuration_id": "continuous-g3-r2-default",
            "configuration_hash": digest,
            "runner_compatible": True,
            "supports_full_terminal_evaluation": True,
            "estimated_dispatch_bounds": limits,
            "conservative_reservation_usd": limits["conservative_usd"],
            "user_risk_ceiling_usd": limits["risk_ceiling_usd"],
            "capability_checks": ["frozen declarations; account access not checked"],
            "resource_checks": ["tokenizer SHA and native profile validated"],
            "diagnostics": [],
        }

    @app.get("/api/v1/settings/status")
    async def settings():
        return {
            "openai_configured": bool(credentials.get("openai")),
            "deepseek_configured": bool(credentials.get("deepseek")),
            "pubmed_email_configured": bool(contact["email"]),
            "backend_connected": True,
            "account_validation": "UNVERIFIED",
            "storage": "SERVER_PROCESS_MEMORY_ONLY",
        }

    @app.put("/api/v1/settings/credentials/{provider}")
    async def save_key(provider: str, body: Credential):
        if provider not in {"openai", "deepseek"}:
            raise HTTPException(422, "unsupported provider")
        credentials[provider] = body.key.get_secret_value()
        return {"configured": True, "validated": False}

    @app.delete("/api/v1/settings/credentials/{provider}")
    async def clear_key(provider: str):
        credentials.pop(provider, None)
        return {"configured": False}

    @app.put("/api/v1/settings/pubmed")
    async def save_email(body: Contact):
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", body.email):
            raise HTTPException(422, "invalid contact email")
        contact["email"] = body.email
        return {"configured": True}

    @app.delete("/api/v1/settings/pubmed")
    async def clear_email():
        contact["email"] = ""
        return {"configured": False}

    @app.post("/api/v1/settings/validation")
    async def validate_settings():
        return {
            "account_validation": "UNVERIFIED",
            "network_dispatches": 0,
            "message": "仅本地设置检查；没有模型权限或付费探测。",
        }

    @app.get("/api/v1/runs")
    def runs():
        return store.list("run")

    @app.post("/api/v1/runs")
    def create_run(body: Create):
        pf = store.get("preflight", body.preflight_id)
        if pf["code_identity"] != code_identity():
            raise ValueError("old code identity")
        draft = Draft.model_validate(pf["draft"])
        if diagnostics(draft):
            raise HTTPException(422, "unvalidated configuration")
        if draft.mode == "LIVE_SINGLE_DISPATCH" and not all(
            (credentials.get("openai"), credentials.get("deepseek"), contact["email"])
        ):
            raise HTTPException(422, "LIVE prerequisites missing")
        with tempfile.TemporaryDirectory(prefix="wb-create-") as folder:
            goal = Path(folder) / "goal.json"
            goal.write_text(draft.goal.model_dump_json(), encoding="utf-8")
            value = service(draft.mode).create(
                goal, store.path("runs"), mock=draft.mode == "MOCK_ONLY"
            )
        record = store.save(
            "run",
            {
                "project_id": draft.project_id,
                "title": draft.goal.title,
                "mode": draft.mode,
                "configuration_hash": pf["hash"],
                "limits": value["limits"],
            },
            value["run_id"],
        )
        log.emit("run.created", run_id=value["run_id"], phase="prepared")
        return record

    @app.post("/api/v1/runs/{key}/authorize")
    def authorize(key: str, body: Approve):
        record, root = info(key)
        result = service(record["mode"]).authorize(root, **body.model_dump())
        log.emit("run.authorized", run_id=key, phase="authorize")
        return result

    @app.post("/api/v1/runs/{key}/start")
    async def start(key: str):
        return await run_in_threadpool(start_native, key)

    @app.post("/api/v1/runs/{key}/resume")
    async def resume(key: str, body: Resume | None = None):
        _, root = info(key)
        service()._verify(root)
        state = await run_in_threadpool(observe, root)
        if state["state"] in TERMINAL:
            return {"state": "terminal_no_dispatch", "status": state}
        if state["state"] == "prepared":
            raise HTTPException(409, "prepared Run requires explicit start, not resume")
        if body is None or not body.confirm_execution:
            raise HTTPException(403, "resume can dispatch paid requests; explicit intent required")
        return await run_in_threadpool(start_native, key, True)

    def start_native(key, resuming=False):
        record, root = info(key)
        native = service(record["mode"])
        native._verify(root)
        if observe(root)["state"] in TERMINAL:
            return {"state": "terminal_no_dispatch", "status": native.status(root)}
        if not resuming and observe(root)["state"] != "prepared" and not driver_alive(root):
            raise HTTPException(409, "interrupted Run requires explicit resume intent")
        if record["mode"] == "LIVE_SINGLE_DISPATCH" and not allow_live:
            raise HTTPException(
                403,
                "LIVE dispatch disabled; explicit server opt-in and per-Run authorization required",
            )
        if not (root / "authorization.json").is_file():
            raise HTTPException(403, "per-Run authorization required")
        auth = load(root / "authorization.json")
        plan = load(root / "plan.json")
        if (auth.get("plan_hash") != protocol_hash(plan) or auth.get("run_id") != key
                or auth.get("version") != "release-authorization-v1"
                or auth.get("mode") != plan["mode"] or auth.get("limits") != plan["limits"]
                or Decimal(str(auth.get("accepted_risk_usd"))) != Decimal(plan["limits"]["risk_ceiling_usd"])):
            raise ValueError("authorization identity mismatch")
        if record["mode"] == "LIVE_SINGLE_DISPATCH" and not (
            auth.get("operator_confirmed_pricing_capability") and auth.get("accepted_unknown_delivery_risk")
        ):
            raise HTTPException(403, "LIVE pricing and risk confirmation required")
        if record["mode"] == "LIVE_SINGLE_DISPATCH" and not all(
            (credentials.get("openai"), credentials.get("deepseek"), contact["email"])
        ):
            raise HTTPException(403, "re-enter process-memory credentials after server restart")
        log.emit("run.resume_requested" if resuming else "run.start_requested",
                 run_id=key, phase="resume" if resuming else "start")
        return app.state.launch(store, key, native.environment)

    @app.post("/api/v1/runs/{key}/stop")
    def stop(key: str):
        _, root = info(key)
        service()._verify(root)
        result = service().stop(root)
        log.emit("run.stop_requested", run_id=key, phase="stop")
        return result

    @app.get("/api/v1/runs/{key}/status")
    def status(key: str):
        record, root = info(key)
        result = observe(root)
        job = store.job(key)
        alive = driver_alive(root)
        if (
            not alive
            and result["state"] not in TERMINAL
            and job["state"] in {"starting", "running", "finished"}
        ):
            job = store.job(key, pid=job["pid"], state="interrupted_needs_review",
                            diagnostic=job.get("diagnostic") or {
                                "code": "DRIVER_LOST", "phase": "observation",
                                "error_id": "err-" + secrets.token_hex(16),
                                "last_event_sequence": result.get("events"),
                                "native_state": result["state"]})
            log.emit("driver.lost", level="WARNING", run_id=key, phase="observation",
                     native_state=result["state"], sequence=result.get("events"),
                     error_id=(job.get("diagnostic") or {}).get("error_id"))
        if result["state"] in TERMINAL:
            job = {**job, "observed_driver_state": job["state"], "state": "terminal"}
        result.update(
            {
                "mode": record["mode"],
                "job": {**job, "alive": alive},
                "resume_is_not_pause": True,
                "limits": load(root / "plan.json")["limits"],
            }
        )
        return result

    @app.get("/api/v1/runs/{key}/logs")
    def run_logs(key: str, limit: int = 100):
        _, root = info(key)
        if not 1 <= limit <= 500:
            raise HTTPException(422)
        return {"run_id": key, "records": tail(root / "logs/driver.jsonl", limit),
                "note": "Local diagnostics only; native events remain authoritative."}

    @app.get("/api/v1/runs/{key}/events")
    def events(key: str, after: int = 0):
        if after < 0:
            raise HTTPException(422)
        _, root = info(key)
        return observed_events(root, after)

    @app.get("/api/v1/runs/{key}/monitor")
    def monitor(key: str, after: int = 0):
        if after < 0:
            raise HTTPException(422)
        _, root = info(key)
        try:
            return monitor_page(root, key, after)
        except sqlite3.OperationalError:
            raise HTTPException(503, "MONITOR_BUSY: retry read only") from None

    @app.get("/api/v1/runs/{key}/stream")
    async def stream(key: str, request: Request, after: int = 0):
        _, root = info(key)
        try:
            cursor = max(after, int(request.headers.get("last-event-id", "0")))
        except ValueError:
            raise HTTPException(422, "invalid sequence") from None
        if cursor < 0:
            raise HTTPException(422)

        async def generate():
            nonlocal cursor
            while not await request.is_disconnected():
                try:
                    rows = await run_in_threadpool(event_page, root, cursor)
                except sqlite3.OperationalError:
                    yield "event: read.busy\ndata: {}\n\n"
                    await asyncio.sleep(1)
                    continue
                for row in rows:
                    cursor = row["sequence"]
                    yield f"id: {cursor}\nevent: run.event\ndata: {json.dumps(row, ensure_ascii=False)}\n\n"
                if len(rows) == 1000:
                    continue
                try:
                    current = await run_in_threadpool(observe, root)
                except sqlite3.OperationalError:
                    yield "event: read.busy\ndata: {}\n\n"
                    await asyncio.sleep(1)
                    continue
                if current["state"] in TERMINAL or not await run_in_threadpool(driver_alive, root):
                    yield "event: boundary\ndata: {}\n\n"
                    return
                yield ": heartbeat\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(generate(), media_type="text/event-stream")

    @app.get("/api/v1/runs/{key}/leaderboard")
    def leaderboard(key: str):
        _, root = info(key)
        return candidates(root, key)

    @app.get("/api/v1/runs/{key}/candidates/{candidate_id}")
    def candidate(key: str, candidate_id: str):
        identifier(candidate_id)
        docs = native_documents(key)
        value = next(
            (c for c in docs["candidates.json"] if c["hypothesis_id"] == candidate_id), None
        )
        if value is None:
            raise HTTPException(404)
        # Full frozen ancestry/source facts remain inspectable, without claiming
        # every source supports this candidate or fabricating claim-level bindings.
        value["source_and_generation_records"] = source_records(
            docs["candidates.json"], docs["run-timeline.json"]["events"], candidate_id)
        value["matches"] = [
            r for r in docs["ranking-history.json"] if candidate_id in (r["left_id"], r["right_id"])
        ]
        return value

    @app.get("/api/v1/runs/{key}/lineage")
    def lineage(key: str):
        return native_documents(key)["evolution-tree.json"]

    @app.get("/api/v1/runs/{key}/rankings")
    def rankings(key: str):
        return native_documents(key)["ranking-history.json"]

    @app.get("/api/v1/runs/{key}/trace")
    def trace(key: str):
        return native_documents(key)

    @app.post("/api/v1/runs/{key}/exports")
    async def export(key: str):
        _, root = info(key)
        export_id = "export-" + secrets.token_hex(16)
        destination = store.path("exports", key, export_id)
        await run_in_threadpool(lambda: asyncio.run(service().export(root, destination)))
        store.save("export", {"run_id": key, "files": sorted(TRACE_FILES)}, export_id)
        log.emit("run.exported", run_id=key, phase="export")
        return {"export_id": export_id, "files": sorted(TRACE_FILES)}

    @app.get("/api/v1/runs/{key}/exports/{export_id}")
    def download_export(key: str, export_id: str):
        info(key)
        record = store.get("export", export_id)
        if record["run_id"] != key:
            raise HTTPException(404)
        target = store.path("exports", key, export_id)
        content = io.BytesIO()
        with zipfile.ZipFile(content, "w", zipfile.ZIP_DEFLATED) as archive:
            for name in sorted(TRACE_FILES):
                path = target / name
                if path.is_symlink():
                    raise HTTPException(409)
                archive.writestr(name, path.read_bytes())
        return Response(
            content.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{key}-native-trace.zip"'},
        )

    return app
