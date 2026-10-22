"""Workbench acceptance boundaries; no real sockets or credentials."""

import io
import json
import time
import zipfile

import httpx
import pytest

from co_scientist.release.service import RunService, code_identity
from co_scientist_web.app import create_app
from co_scientist_web.configuration import Runtime

pytestmark = pytest.mark.asyncio
GOAL = {
    "title": "Synthetic causal recovery",
    "goal": "Distinguish reversible stress from persistent recovery failure.",
    "required_causal_chain": ["stress", "recovery"],
    "required_outputs": ["testable prediction"],
}


async def client(tmp_path, **kwargs):
    app = create_app(tmp_path, **kwargs)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://127.0.0.1:8765"
    ) as bootstrap:
        await bootstrap.get("/")
        csrf = (await bootstrap.get("/api/v1/session")).json()["csrf_token"]
        cookies = httpx.Cookies(bootstrap.cookies)
    c = httpx.AsyncClient(
        transport=transport,
        base_url="http://127.0.0.1:8765",
        cookies=cookies,
        headers={"Origin": "http://127.0.0.1:8765", "X-CSRF-Token": csrf},
    )
    return app, c


async def prepare(c, **changes):
    payload = {"goal": GOAL, "run_config": Runtime().model_dump(), **changes}
    pf = await c.post("/api/v1/config/preflight", json=payload)
    assert pf.status_code == 200, pf.text
    result = await c.post("/api/v1/runs", json={"preflight_id": pf.json()["preflight_id"]})
    assert result.status_code == 200, result.text
    return result.json()["id"]


async def test_prepared_csrf_paths_profile_and_draft(tmp_path):
    app, c = await client(tmp_path)
    async with c:
        assert (
            await c.post(
                "/api/v1/projects",
                json={"title": "Study"},
                headers={"Origin": "http://evil.invalid"},
            )
        ).status_code == 403
        assert (await c.get("/api/v1/health", headers={"Host": "evil.invalid"})).status_code == 403
        assert (
            await c.post(
                "/api/v1/projects", json={"title": "Study"}, headers={"X-CSRF-Token": "bad"}
            )
        ).status_code == 403
        project = (await c.post("/api/v1/projects", json={"title": "Study"})).json()
        saved = await c.post("/api/v1/drafts", json={"goal": GOAL, "project_id": project["id"]})
        assert saved.status_code == 200
        changed = {
            **Runtime().model_dump(),
            "reproduction_transitions": 5,
            "generation_model": "gpt-6-astra",
        }
        assert (
            await c.post("/api/v1/config/preflight", json={"goal": GOAL, "run_config": changed})
        ).status_code == 422
        run = await prepare(c)
        root = app.state.store.run_root(run)
        assert (await c.get(f"/api/v1/runs/{run}/status")).json()["state"] == "prepared"
        assert (await c.get(f"/api/v1/runs/{run}/events")).json() == []
        assert (await c.post(f"/api/v1/runs/{run}/exports")).status_code == 409
        assert not (root / "runtime").exists()
        assert (await c.post(f"/api/v1/runs/{run}/start")).status_code == 403
        assert (await c.get("/api/v1/runs/%2Ftmp%2Fother/status")).status_code in {404, 409}
        assert (await c.post("/api/v1/runs", json={"preflight_id": "../x"})).status_code == 409
        assert not (root / "runtime").exists()


async def test_credentials_no_leak_live_authorization_and_email_freeze(tmp_path):
    app, c = await client(tmp_path)
    sentinels = {"openai": "FAKE-OPENAI-DO-NOT-LEAK", "deepseek": "FAKE-DEEPSEEK-DO-NOT-LEAK"}
    async with c:
        for provider, value in sentinels.items():
            response = await c.put(f"/api/v1/settings/credentials/{provider}", json={"key": value})
            assert response.status_code == 200 and value not in response.text
        bad = await c.put(
            "/api/v1/settings/credentials/openai",
            json={"key": sentinels["openai"], "extra": sentinels["deepseek"]},
        )
        assert bad.status_code == 422 and not any(x in bad.text for x in sentinels.values())
        assert (
            await c.put("/api/v1/settings/pubmed", json={"email": "invalid"})
        ).status_code == 422
        await c.put("/api/v1/settings/pubmed", json={"email": "original@example.test"})
        run = await prepare(c, mode="LIVE_SINGLE_DISPATCH")
        root = app.state.store.run_root(run)
        await c.put("/api/v1/settings/pubmed", json={"email": "changed@example.test"})
        assert (
            json.loads((root / "plan.json").read_bytes())["pubmed_email"] == "original@example.test"
        )
        assert (
            await c.post(
                f"/api/v1/runs/{run}/authorize", json={"confirm": True, "accept_usd": "60"}
            )
        ).status_code == 409
        assert (
            await c.post(
                f"/api/v1/runs/{run}/authorize",
                json={
                    "confirm": True,
                    "accept_usd": "60",
                    "confirm_pricing": True,
                    "accept_unknown_risk": True,
                },
            )
        ).status_code == 200
        assert (await c.post(f"/api/v1/runs/{run}/start")).status_code == 403
        assert not (root / "runtime").exists()
        for path in tmp_path.rglob("*"):
            if path.is_file():
                assert not any(x.encode() in path.read_bytes() for x in sentinels.values()), path
        _, restarted = await client(tmp_path)
        async with restarted:
            assert not (await restarted.get("/api/v1/settings/status")).json()["openai_configured"]


async def test_native_stop_partial_no_resume_and_old_identity(tmp_path):
    app, c = await client(tmp_path)
    async with c:
        run = await prepare(c)
        root = app.state.store.run_root(run)
        await c.post(f"/api/v1/runs/{run}/authorize", json={"confirm": True, "accept_usd": "60"})
        native = RunService(environment={})
        await native.execute(root, steps=1)
        assert (await c.post(f"/api/v1/runs/{run}/stop")).status_code == 200
        await native.execute(root)
        status = (await c.get(f"/api/v1/runs/{run}/status")).json()
        assert status["state"] == "completed_partial"
        assert not status["final"] or status["final"]["selection_result"] != "FINAL_WINNER"
        assert (await c.post(f"/api/v1/runs/{run}/resume")).json()[
            "state"
        ] == "terminal_no_dispatch"
        plan = json.loads((root / "plan.json").read_bytes())
        plan["code_identity"] = "old-version"
        (root / "plan.json").write_text(json.dumps(plan))
        assert (await c.post(f"/api/v1/runs/{run}/resume")).status_code == 409
        assert (await c.post(f"/api/v1/runs/{run}/exports")).status_code == 409


async def test_full_web_mock_background_restart_export_and_sse(tmp_path):
    _initial_app, c = await client(tmp_path)
    original_identity = code_identity()
    async with c:
        run = await prepare(c)
        await c.post(f"/api/v1/runs/{run}/authorize", json={"confirm": True, "accept_usd": "60"})
        # Resume an interrupted nonterminal native checkpoint, not a fresh Run.
        root = _initial_app.state.store.run_root(run)
        await RunService(environment={}).execute(root, steps=1)
        _initial_app.state.store.job(run, pid=999999, state="running")
        assert (await c.get(f"/api/v1/runs/{run}/status")).json()["job"][
            "state"
        ] == "interrupted_needs_review"
        first = (await c.post(f"/api/v1/runs/{run}/start")).json()
        second = (await c.post(f"/api/v1/runs/{run}/start")).json()
        assert first["pid"] == second["pid"]
    # New HTTP app/session, same durable detached driver; no credentials needed.
    _app, c = await client(tmp_path)
    async with c:
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            response = await c.get(f"/api/v1/runs/{run}/status")
            if response.status_code != 200:
                await __import__("asyncio").sleep(0.2)
                continue
            status = response.json()
            if status["state"] == "completed":
                break
            assert status["job"]["state"] != "interrupted_needs_review", status
            await __import__("asyncio").sleep(1)
        else:
            pytest.fail("detached G3 did not finish")
        assert status["final"]["execution_result"] == "COMPLETE"
        assert status["final"]["terminal_barrier_complete"]
        assert status["final"]["selection_result"] == "FINAL_WINNER"
        board = (await c.get(f"/api/v1/runs/{run}/leaderboard")).json()
        assert len(board["ranked"]) == 10 and not board["pending"]
        assert sum(c["operator"] == "root" for c in board["ranked"]) == 4
        assert all(c["operator"] in {"root", "mutation", "crossover"} for c in board["ranked"])
        assert [x["rating"]["mu"] for x in board["ranked"]] == sorted(
            [x["rating"]["mu"] for x in board["ranked"]], reverse=True
        )
        assert board["ranked"][0]["hypothesis_id"] == status["final"]["winner_id"]
        detail = (
            await c.get(f"/api/v1/runs/{run}/candidates/{board['ranked'][0]['hypothesis_id']}")
        ).json()
        assert (
            detail["predictions"]
            and detail["ethics"]
            and detail["reflection"]
            and detail["matches"]
        )
        assert any(
            r["event_type"] == "RootReviewPlannedV1"
            for r in detail["source_and_generation_records"]
        )
        tree = (await c.get(f"/api/v1/runs/{run}/lineage")).json()
        assert (
            len(tree["reproduction"]) == 6
            and max(x["generation"] for x in tree["reproduction"]) == 3
        )
        rows = (await c.get(f"/api/v1/runs/{run}/events")).json()
        stream = await c.get(
            f"/api/v1/runs/{run}/stream", headers={"Last-Event-ID": str(rows[-3]["sequence"])}
        )
        assert f"id: {rows[-3]['sequence']}\n" not in stream.text
        assert f"id: {rows[-1]['sequence']}\n" in stream.text
        exported = (await c.post(f"/api/v1/runs/{run}/exports")).json()
        response = await c.get(f"/api/v1/runs/{run}/exports/{exported['export_id']}")
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            assert len(archive.namelist()) == 5
            timeline = json.loads(archive.read("run-timeline.json"))
            assert timeline["evidence_kind"] == "MOCK_ONLY"
            assert {x["provider"] for x in timeline["calls"]} == {
                "deepseek",
                "openai",
                "pubmed:root",
            }
            assert all(x["permit"]["mode"] == "MOCK_ONLY" for x in timeline["requests"])
        assert (await c.post(f"/api/v1/runs/{run}/resume")).json()[
            "state"
        ] == "terminal_no_dispatch"
        assert (await c.get(f"/api/v1/runs/{run}/events")).json() == rows
        assert code_identity() == original_identity
        print("WEB_MOCK_RUN", run, tmp_path, status["final"]["winner_id"])


async def test_export_busy_retry_resources_and_authorization_transfer(tmp_path, monkeypatch):
    app, c = await client(tmp_path)
    async with c:
        run = await prepare(c)
        other = await prepare(c)
        await c.post(f"/api/v1/runs/{run}/authorize", json={"confirm": True, "accept_usd": "60"})
        root = app.state.store.run_root(run)
        second = app.state.store.run_root(other)
        (second / "authorization.json").write_bytes((root / "authorization.json").read_bytes())
        assert (await c.post(f"/api/v1/runs/{other}/start")).status_code == 409
        assert not (second / "runtime").exists()
        await RunService(environment={}).execute(root, steps=1)
        original = RunService.export

        async def busy(*args, **kwargs):
            raise ValueError("trace snapshot changed during export")

        monkeypatch.setattr(RunService, "export", busy)
        response = await c.post(f"/api/v1/runs/{run}/exports")
        assert response.status_code == 409 and response.json()["error"] == "SNAPSHOT_BUSY"
        monkeypatch.setattr(RunService, "export", original)
        assert (await c.post(f"/api/v1/runs/{run}/exports")).status_code == 200
        monkeypatch.setenv("CO_SCIENTIST_RESOURCE_DIR", str(tmp_path / "missing-assets"))
        response = await c.post("/api/v1/config/preflight", json={"goal": GOAL})
        assert response.status_code == 422
        assert not (tmp_path / "missing-assets").exists()


async def test_credential_overwrite_clear_and_missing_session(tmp_path):
    _app, c = await client(tmp_path)
    async with c:
        for key in ("FAKE-FIRST-KEY", "FAKE-SECOND-KEY"):
            assert (
                await c.put("/api/v1/settings/credentials/openai", json={"key": key})
            ).status_code == 200
            assert key not in (await c.get("/api/v1/settings/status")).text
        assert (await c.delete("/api/v1/settings/credentials/openai")).status_code == 200
        assert not (await c.get("/api/v1/settings/status")).json()["openai_configured"]
        assert (await c.get("/api/v1/settings/credentials/openai")).status_code == 405
        c.cookies.clear()
        assert (await c.get("/api/v1/settings/status")).status_code == 403
