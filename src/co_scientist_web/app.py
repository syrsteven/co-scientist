"""Authenticated, loopback-only opt-in HTTP boundary over Release v0.1.1."""

import asyncio
import hashlib
import io
import json
import re
import secrets
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import Field, SecretStr, StrictBool

from co_scientist.adapters.artifacts.filesystem import FilesystemArtifactStore
from co_scientist.domain.research_protocol import protocol_hash
from co_scientist.release.resources import package_file, resource_path
from co_scientist.release.service import RunService, budget, code_identity, load
from co_scientist.runtime.ideation_trace import trace_documents
from co_scientist.runtime.trace_snapshot import readonly_uow

from .configuration import Draft, Runtime, Strict, diagnostics
from .jobs import TERMINAL, driver_alive, launch
from .store import Store, identifier
from .views import candidates

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


def create_app(data_root, *, allow_live=False):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    store = Store(data_root)
    session, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    credentials = {}  # Only in this server process; never persisted.
    contact = {"email": ""}
    app.state.store = store
    app.state.launch = launch

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

    @app.exception_handler(RequestValidationError)
    async def validation(request, error):
        return JSONResponse(
            {
                "error": "invalid request",
                "diagnostics": [
                    {"field": ".".join(map(str, e["loc"])), "code": e["type"]}
                    for e in error.errors()
                ],
            },
            422,
        )

    @app.exception_handler(ValueError)
    async def conflict(request, error):
        # Never serialize arbitrary native/provider exception bodies or keys.
        text = str(error)
        code = (
            "SNAPSHOT_BUSY"
            if "snapshot" in text or "overwrite" in text
            else "IDENTITY_OR_CONFIG_CONFLICT"
        )
        return JSONResponse(
            {"error": code, "message": "快照忙请稍后重试；身份不符的旧 Run 请使用原版本环境。"}, 409
        )

    @app.exception_handler(KeyError)
    async def missing(request, error):
        return JSONResponse({"error": "unknown logical identifier"}, 404)

    @app.exception_handler(Exception)
    async def failure(request, error):
        return JSONResponse({"error": "local backend operation failed; no automatic retry"}, 500)

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
    async def health():
        checks = {}
        for name in ("deepseek-v41.json", "o200k_base.tiktoken"):
            try:
                resource_path("resource:" + name)
                checks[name] = "ready"
            except ValueError:
                checks[name] = "missing_or_invalid: explicit resources install required"
        return {
            "backend_connected": True,
            "release": "0.1.1",
            "resources": checks,
            "live_enabled": allow_live,
            "code_identity": code_identity(),
        }

    @app.get("/api/v1/projects")
    async def projects():
        return store.list("project")

    @app.post("/api/v1/projects")
    async def add_project(body: Project):
        return store.save("project", body.model_dump())

    @app.get("/api/v1/projects/{key}")
    async def project(key: str):
        return store.get("project", key)

    @app.patch("/api/v1/projects/{key}")
    async def edit_project(key: str, body: Project):
        store.get("project", key)
        return store.save("project", body.model_dump(), key)

    @app.get("/api/v1/drafts")
    async def drafts():
        return store.list("draft")

    @app.post("/api/v1/drafts")
    async def save_draft(body: Draft):
        if body.project_id:
            store.get("project", body.project_id)
        return store.save("draft", body.model_dump())

    @app.patch("/api/v1/drafts/{key}")
    async def update_draft(key: str, body: Draft):
        store.get("draft", key)
        if body.project_id:
            store.get("project", body.project_id)
        return store.save("draft", body.model_dump(), key)

    @app.get("/api/v1/config/defaults")
    async def defaults():
        return {
            "version": "web-config-builder-v1",
            "run_config": Runtime().model_dump(),
            "profile_sha256": hashlib.sha256(package_file("g3.yaml").read_bytes()).hexdigest(),
            "custom_execution": "BLOCKED_UNTIL_FULL_MOCK_VALIDATED",
        }

    @app.get("/api/v1/config/models")
    async def models():
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
    async def preflight(body: Draft):
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
                except (ValueError, FileNotFoundError):
                    errors.append(
                        {
                            "field": "resources_or_goal",
                            "code": "NATIVE_PREFLIGHT_REJECTED",
                            "message": "请检查研究目标和 tokenizer；显式安装资源，不会自动下载。",
                        }
                    )
        if errors:
            return JSONResponse({"runner_compatible": False, "diagnostics": errors}, 422)
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
    async def runs():
        return store.list("run")

    @app.post("/api/v1/runs")
    async def create_run(body: Create):
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
        return record

    @app.post("/api/v1/runs/{key}/authorize")
    async def authorize(key: str, body: Approve):
        record, root = info(key)
        return service(record["mode"]).authorize(root, **body.model_dump())

    @app.post("/api/v1/runs/{key}/start")
    @app.post("/api/v1/runs/{key}/resume")
    async def start(key: str):
        record, root = info(key)
        native = service(record["mode"])
        native._verify(root)
        if observe(root)["state"] in TERMINAL:
            return {"state": "terminal_no_dispatch", "status": native.status(root)}
        if record["mode"] == "LIVE_SINGLE_DISPATCH" and not allow_live:
            raise HTTPException(
                403,
                "LIVE dispatch disabled; explicit server opt-in and per-Run authorization required",
            )
        if not (root / "authorization.json").is_file():
            raise HTTPException(403, "per-Run authorization required")
        auth = load(root / "authorization.json")
        plan = load(root / "plan.json")
        if auth.get("plan_hash") != protocol_hash(plan) or auth.get("run_id") != key:
            raise ValueError("authorization identity mismatch")
        if record["mode"] == "LIVE_SINGLE_DISPATCH" and not all(
            (credentials.get("openai"), credentials.get("deepseek"), contact["email"])
        ):
            raise HTTPException(403, "re-enter process-memory credentials after server restart")
        return app.state.launch(store, key, native.environment)

    @app.post("/api/v1/runs/{key}/stop")
    async def stop(key: str):
        _, root = info(key)
        service()._verify(root)
        return service().stop(root)

    @app.get("/api/v1/runs/{key}/status")
    async def status(key: str):
        record, root = info(key)
        result = observe(root)
        job = store.job(key)
        alive = driver_alive(root)
        if (
            not alive
            and result["state"] not in TERMINAL
            and job["state"] in {"starting", "running"}
        ):
            job = store.job(key, pid=job["pid"], state="interrupted_needs_review")
        result.update(
            {
                "mode": record["mode"],
                "job": {**job, "alive": alive},
                "resume_is_not_pause": True,
                "limits": load(root / "plan.json")["limits"],
            }
        )
        return result

    @app.get("/api/v1/runs/{key}/events")
    async def events(key: str, after: int = 0):
        if after < 0:
            raise HTTPException(422)
        _, root = info(key)
        return observed_events(root, after)

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
                for row in observed_events(root, cursor):
                    cursor = row["sequence"]
                    yield f"id: {cursor}\nevent: run.event\ndata: {json.dumps(row, ensure_ascii=False)}\n\n"
                current = observe(root)
                if current["state"] in TERMINAL or not driver_alive(root):
                    yield "event: boundary\ndata: {}\n\n"
                    return
                yield ": heartbeat\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(generate(), media_type="text/event-stream")

    @app.get("/api/v1/runs/{key}/leaderboard")
    async def leaderboard(key: str):
        _, root = info(key)
        return candidates(root, key)

    @app.get("/api/v1/runs/{key}/candidates/{candidate_id}")
    async def candidate(key: str, candidate_id: str):
        identifier(candidate_id)
        docs = native_documents(key)
        value = next(
            (c for c in docs["candidates.json"] if c["hypothesis_id"] == candidate_id), None
        )
        if value is None:
            raise HTTPException(404)
        # Full frozen ancestry/source facts remain inspectable, without claiming
        # every source supports this candidate or fabricating claim-level bindings.
        value["source_and_generation_records"] = [
            r
            for r in docs["run-timeline.json"]["events"]
            if r["event_type"]
            in {
                "RootReviewPlannedV1",
                "RootRetrievalOutcomeRecordedV2",
                "RootRetrievalReusedV2",
                "RootSourceReviewRecordedV1",
                "RootGroundingFrozenV1",
                "GroundedGenerationRecordedV1",
            }
        ]
        value["matches"] = [
            r for r in docs["ranking-history.json"] if candidate_id in (r["left_id"], r["right_id"])
        ]
        return value

    @app.get("/api/v1/runs/{key}/lineage")
    async def lineage(key: str):
        return native_documents(key)["evolution-tree.json"]

    @app.get("/api/v1/runs/{key}/rankings")
    async def rankings(key: str):
        return native_documents(key)["ranking-history.json"]

    @app.get("/api/v1/runs/{key}/trace")
    async def trace(key: str):
        return native_documents(key)

    @app.post("/api/v1/runs/{key}/exports")
    async def export(key: str):
        _, root = info(key)
        export_id = "export-" + secrets.token_hex(16)
        destination = store.path("exports", key, export_id)
        await service().export(root, destination)
        store.save("export", {"run_id": key, "files": sorted(TRACE_FILES)}, export_id)
        return {"export_id": export_id, "files": sorted(TRACE_FILES)}

    @app.get("/api/v1/runs/{key}/exports/{export_id}")
    async def download_export(key: str, export_id: str):
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
