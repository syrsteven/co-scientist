"""Synthetic boundaries: no historical data or external dispatch."""

from types import SimpleNamespace as NS

import pytest

from co_scientist.release.service import RunService, save_new
from co_scientist.supervisor.orchestrator import Supervisor


class Frozen(Exception):
    pass


def supervisor_fixture(monkeypatch, ready_count=5, rated_count=4):
    events = [NS(event_type="TournamentEntryCreated", sequence=i + 1,
                 payload={"epoch_id": "epoch", "hypothesis_id": str(i), "content_hash": str(i)})
              for i in range(rated_count)]
    manifest = {"goal": {"goal": "synthetic"}, "tournament_contract": {
        "epoch_id": "epoch", "research_plan_version": 1},
        "ideation_search_contract": {}, "ideation_search_contract_hash": "hash"}
    monkeypatch.setattr("co_scientist.domain.population_evolution.read_search_policy",
                        lambda _: NS(reproduction_transitions=3))
    monkeypatch.setattr("co_scientist.domain.continuous_execution.policy_for", lambda _: None)
    finals = []

    def commit(**kwargs):
        finals.extend(kwargs["events"])
        raise Frozen

    supervisor = object.__new__(Supervisor)
    supervisor.uow = NS(load=lambda _: events, run_manifest=lambda _: manifest,
                        unresolved_task_ids=lambda _: [], commit_domain_batch=commit)
    supervisor._baseline_ready_candidates = lambda _: {
        str(i): NS(content_hash=str(i)) for i in range(ready_count)}
    return supervisor, events, finals


@pytest.mark.parametrize("generation", [0, 1, 2, 3])
def test_partial_stop_can_leave_ready_candidates_unrated(monkeypatch, generation):
    supervisor, _, finals = supervisor_fixture(monkeypatch)
    with pytest.raises(Frozen):
        supervisor._baseline_search_stop(run_id="r", expected_sequence=4,
                                         reason="USER_STOP", generation=generation, complete=False)
    final = finals[0].payload
    assert final["execution_result"] == "PARTIAL"
    assert final["winner_id"] is None and final["best_so_far_id"] is None
    assert not final["eligible_pool_ids"]


def test_complete_and_invalid_partial_still_fail_closed(monkeypatch):
    supervisor, _, _ = supervisor_fixture(monkeypatch)
    with pytest.raises(ValueError, match="R ledger"):
        supervisor._baseline_search_stop(run_id="r", expected_sequence=4,
                                         reason="DONE", generation=3, complete=True)
    supervisor, _, _ = supervisor_fixture(monkeypatch, ready_count=3)
    with pytest.raises(ValueError, match="R ledger"):
        supervisor._baseline_search_stop(run_id="r", expected_sequence=4,
                                         reason="STOP", generation=1, complete=False)


def test_partial_content_identity_still_rejected(monkeypatch):
    supervisor, events, _ = supervisor_fixture(monkeypatch)
    events[0].payload["content_hash"] = "forged"
    with pytest.raises(ValueError, match="content identity"):
        supervisor._baseline_search_stop(run_id="r", expected_sequence=4,
                                         reason="STOP", generation=1, complete=False)


@pytest.mark.parametrize("count", [0, 1, 4])
def test_partial_empty_or_uncompared_has_no_best(monkeypatch, count):
    supervisor, _, finals = supervisor_fixture(monkeypatch, count, count)
    with pytest.raises(Frozen):
        supervisor._baseline_search_stop(run_id="r", expected_sequence=count,
                                         reason="STOP", generation=0, complete=False)
    assert finals[0].payload["best_so_far_id"] is None


def test_partial_best_uses_only_real_decisive_ledger(monkeypatch):
    supervisor, events, finals = supervisor_fixture(monkeypatch)
    for i in range(2):
        events.extend([
            NS(sequence=5+i*2, event_type="MatchPairReserved", payload={"epoch_id":"epoch",
                "match_id":str(i), "left_id":"0", "right_id":"1"}),
            NS(sequence=6+i*2, event_type="MatchEvaluated", payload={"epoch_id":"epoch",
                "match_id":str(i), "left_id":"0", "right_id":"1", "winner_id":"0", "decision":"decisive"})])
    with pytest.raises(Frozen):
        supervisor._baseline_search_stop(run_id="r", expected_sequence=8,
                                         reason="STOP", generation=1, complete=False)
    final=finals[0].payload
    assert final["best_so_far_id"] == "0" and final["winner_id"] is None
    assert set(final["eligible_pool_ids"]) == {"0", "1"}


def test_save_new_interruption_does_not_publish_partial_json(tmp_path, monkeypatch):
    def interrupted(value, handle, **kwargs):
        handle.write('{"unfinished":')
        raise OSError("simulated interruption")
    monkeypatch.setattr("co_scientist.release.service.json.dump", interrupted)
    target = tmp_path / "authorization.json"
    with pytest.raises(OSError):
        save_new(target, {"a": 1})
    assert not target.exists()


def test_prepared_stop_creates_no_control_file(tmp_path, monkeypatch):
    native = RunService(environment={})
    monkeypatch.setattr(native, "_verify", lambda root: (root, {}, {}))
    monkeypatch.setattr(native, "status", lambda root: {"state": "prepared"})
    with pytest.raises(ValueError, match="prepared"):
        native.stop(tmp_path)
    assert not (tmp_path / "stop-request.json").exists()


@pytest.mark.asyncio
async def test_driver_nonterminal_return_is_not_finished(tmp_path, monkeypatch):
    import asyncio

    from co_scientist_web.driver import run_driver
    from co_scientist_web.store import Store

    store = Store(tmp_path)
    store.save("run", {}, "r")
    class Native:
        async def execute(self, root):
            return {"state": "running"}
        def status(self, root):
            return {"state": "running", "events": 230}
    monkeypatch.setattr("co_scientist_web.driver.RunService", lambda **_: Native())
    await asyncio.to_thread(run_driver, store, "r", {})
    job = store.job("r")
    assert job["state"] == "interrupted_needs_review"
    assert job["diagnostic"]["last_event_sequence"] == 230
    assert job["diagnostic"]["code"] == "NATIVE_NONTERMINAL_RETURN"


@pytest.mark.asyncio
async def test_reconnect_prepared_stop_and_resume_require_intent(tmp_path):
    from tests.test_web import client, prepare
    app, c = await client(tmp_path)
    async with c:
        run = await prepare(c)
        root = app.state.store.run_root(run)
        assert (await c.post(f"/api/v1/runs/{run}/stop")).status_code == 409
        assert not (root / "stop-request.json").exists()
        assert (await c.post(f"/api/v1/runs/{run}/resume")).status_code in {403, 409}
        assert not (root / "runtime").exists()


def test_monitor_does_not_regenerate_full_trace():
    from pathlib import Path
    source = Path("src/co_scientist_web/frontend/backend.js").read_text()
    update = source.split("async function update(){", 1)[1].split("window.addEventListener", 1)[0]
    assert '/trace`' not in update
    assert '/monitor' in update


@pytest.mark.asyncio
async def test_native_stop_at_fifth_review_before_r_entry(tmp_path, monkeypatch):
    from co_scientist.domain.bayesian_ranking import TrueSkillConfig, replay_bayesian_rating
    from co_scientist.release.service import load
    from co_scientist.runtime.worker import Worker
    from tests.test_release import create
    service, root = create(tmp_path, mock=True)
    service.authorize(root, confirm=True, accept_usd="60")
    original = Worker.run_once
    boundary = []
    async def observe(self, run_id):
        result = await original(self, run_id)
        # Use the same authoritative readiness validator, never invented PASS.
        supervisor = self.supervisor
        uow = self.runtime.uow
        if uow.run_state(run_id) == "running" and not boundary:
            ready = supervisor._baseline_ready_candidates(run_id)
            history = uow.load(run_id)
            epoch = uow.run_manifest(run_id)["tournament_contract"]["epoch_id"]
            rated = replay_bayesian_rating(history, epoch_id=epoch, policy=TrueSkillConfig())
            if len(ready) == 5 and len(rated) == 4:
                boundary.append(history[-1].sequence)
                service.stop(root)
        return result
    monkeypatch.setattr(Worker, "run_once", observe)
    result = await service.execute(root)
    assert boundary and result["state"] == "completed_partial"
    assert result["final"]["execution_result"] == "PARTIAL"
    assert result["final"]["winner_id"] is None
    before = service.events(root)
    timeline = load(root / "exports/run-timeline.json")
    calls = timeline["dispatch_ledger"]["attempts"]
    await service.execute(root)
    assert service.events(root) == before
    assert load(root / "exports/run-timeline.json")["dispatch_ledger"]["attempts"] == calls
    assert sum(e["event_type"] == "IdeationFinalSelectionV1" for e in before) == 1


def test_atomic_exclusive_multi_process_publish(tmp_path):
    import json
    import os
    import subprocess
    import sys
    target = tmp_path / "permit.json"
    script = """import sys
from co_scientist.release.service import save_new
try:
    save_new(sys.argv[1], {'writer': sys.argv[2], 'body': 'x' * 50000})
except FileExistsError:
    sys.exit(9)
"""
    children = [subprocess.Popen([sys.executable, "-c", script, str(target), str(i)],
                                env=os.environ.copy()) for i in range(3)]
    exits = [c.wait(timeout=30) for c in children]
    assert sorted(exits) == [0, 9, 9]
    assert len(json.loads(target.read_bytes())["body"]) == 50000
    before = target.read_bytes()
    with pytest.raises(FileExistsError):
        save_new(target, {"replace": True})
    assert target.read_bytes() == before


def test_monitor_paging_is_read_only_and_bounded(tmp_path):
    import json
    import sqlite3

    from co_scientist_web.monitor import monitor_page
    (tmp_path / "runtime").mkdir()
    with sqlite3.connect(tmp_path / "runtime/co-scientist.db") as db:
        db.execute("CREATE TABLE events(sequence INTEGER,event_type TEXT,payload_json TEXT,occurred_at TEXT)")
        db.executemany("INSERT INTO events VALUES (?,'Synthetic','{}','2026-10-23')",
                       [(i,) for i in range(1, 5001)])
    (tmp_path / "manifest.json").write_text(json.dumps({"goal": {}, "effective_execution_config": {}}))
    cursor, observed = 0, []
    for _ in range(6):
        packet = monitor_page(tmp_path, "r", cursor)
        assert len(packet["events"]) <= 1000
        observed.extend(e["sequence"] for e in packet["events"])
        cursor = packet["source_sequence"]
    assert observed == list(range(1, 5001))
    assert not packet["has_more"]


@pytest.mark.asyncio
async def test_expired_watchdog_never_enters_dispatch(monkeypatch):
    from datetime import UTC, datetime, timedelta
    from unittest.mock import AsyncMock

    from co_scientist.runtime.core_runner import CoreRunner
    runner = object.__new__(CoreRunner)
    runner.uow = NS(run_manifest=lambda _: {}, load=lambda _: [NS(
        occurred_at=datetime.now(UTC)-timedelta(hours=3))])
    runner._drive = AsyncMock(side_effect=AssertionError("no dispatch after watchdog"))
    runner._finish_continuous_partial = AsyncMock(return_value="partial")
    monkeypatch.setattr("co_scientist.domain.continuous_execution.policy_for", lambda _: object())
    monkeypatch.setattr("co_scientist.domain.execution_config.frozen_execution",
                        lambda _: NS(envelope=NS(max_wall_seconds=7200)))
    assert await runner.drive(run_id="r") == "partial"
    runner._finish_continuous_partial.assert_awaited_once_with("r", "RUN_WATCHDOG")
    runner._drive.assert_not_called()


@pytest.mark.asyncio
async def test_stale_finished_metadata_is_not_native_completion(tmp_path, monkeypatch):
    from tests.test_web import client, prepare
    app, c = await client(tmp_path)
    async with c:
        run = await prepare(c)
        root = app.state.store.run_root(run)
        await c.post(f"/api/v1/runs/{run}/authorize", json={"confirm": True, "accept_usd": "60"})
        await RunService(environment={}).execute(root, steps=1)
        app.state.store.job(run, pid=99999999, state="finished")
        before = RunService(environment={}).events(root)
        status = (await c.get(f"/api/v1/runs/{run}/status")).json()
        assert status["state"] == "running"
        assert status["job"]["state"] == "interrupted_needs_review"
        assert status["job"]["diagnostic"]["code"] == "DRIVER_LOST"
        for _ in range(2):
            await c.get(f"/api/v1/runs/{run}/events")
            await c.get(f"/api/v1/runs/{run}/monitor")
            assert (await c.post(f"/api/v1/runs/{run}/resume")).status_code == 403
        assert RunService(environment={}).events(root) == before


@pytest.mark.asyncio
async def test_driver_error_diagnostic_is_allowlisted_not_exception_text(tmp_path, monkeypatch):
    import asyncio

    from co_scientist_web.driver import run_driver
    from co_scientist_web.store import Store
    store = Store(tmp_path)
    store.save("run", {}, "r")
    class Native:
        async def execute(self, root):
            raise ValueError("FAKE-SECRET Authorization: full response body must not escape")
        def status(self, root):
            return {"state": "running", "events": 12}
    monkeypatch.setattr("co_scientist_web.driver.RunService", lambda **_: Native())
    await asyncio.to_thread(run_driver, store, "r", {})
    job = store.job("r")
    assert "FAKE-SECRET" not in str(job)
    assert job["diagnostic"]["code"] == "NATIVE_EXECUTION_REJECTED"


@pytest.mark.asyncio
async def test_stopping_finalization_is_not_enqueued_twice():
    from unittest.mock import Mock

    from co_scientist.runtime.core_runner import CoreRunner
    runner = object.__new__(CoreRunner)
    states = ["stopping"]
    runner.uow = NS(run_state=lambda _: states[0], load=lambda _: [NS(
        event_type="IdeationFinalSelectionV1", sequence=10)])
    runner.supervisor = NS(_resume_baseline_finalization=Mock(side_effect=AssertionError("duplicate lifecycle")))
    async def finish(run_id):
        states[0] = "completed_partial"
    runner.worker = NS(run_once=finish)
    runner._result = lambda _: "partial"
    assert await runner._finish_continuous_partial("r", "STOP") == "partial"
    runner.supervisor._resume_baseline_finalization.assert_not_called()


@pytest.mark.asyncio
async def test_export_does_not_block_health_or_mutate_run(tmp_path, monkeypatch):
    import asyncio
    import threading
    import time

    from tests.test_web import client, prepare
    entered, finished = threading.Event(), threading.Event()
    async def busy_export(*args, **kwargs):
        entered.set()
        time.sleep(2)  # noqa: ASYNC251 -- intentional blocking-work fault injection
        finished.set()
        raise ValueError("trace snapshot busy")
    app, c = await client(tmp_path)
    async with c:
        run = await prepare(c)
        monkeypatch.setattr(RunService, "export", busy_export)
        pending = asyncio.create_task(c.post(f"/api/v1/runs/{run}/exports"))
        assert await asyncio.to_thread(entered.wait, 5)
        health = await c.get("/api/v1/health")
        assert health.status_code == 200
        nonblocking = not finished.is_set()
        assert (await pending).status_code == 409
        assert nonblocking, "synchronous export blocked FastAPI event loop"
        assert not (app.state.store.run_root(run) / "runtime").exists()


@pytest.mark.asyncio
async def test_original_driver_entrypoint_reconciles_nonterminal_return(tmp_path, monkeypatch):
    import asyncio
    import io
    import os

    from co_scientist_web import driver
    from co_scientist_web.store import Store
    store = Store(tmp_path)
    store.save("run", {}, "r")
    class Native:
        async def execute(self, root):
            return {"state": "running"}
        def status(self, root):
            return {"state": "running", "events": 230}
    fd = os.open(tmp_path / "lock", os.O_CREAT | os.O_RDWR, 0o600)
    monkeypatch.setattr(driver, "Store", lambda _: store)
    monkeypatch.setattr(driver, "RunService", lambda **_: Native())
    monkeypatch.setattr(driver, "load", lambda _: {"mode": "LIVE_SINGLE_DISPATCH"})
    monkeypatch.setattr(driver.sys, "argv", ["driver", str(tmp_path), "r", str(fd)])
    monkeypatch.setattr(driver.sys, "stdin", NS(buffer=io.BytesIO(b"{}")))
    await asyncio.to_thread(driver.main)
    assert store.job("r")["state"] == "interrupted_needs_review"
