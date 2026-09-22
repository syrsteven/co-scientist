from pathlib import Path

import pytest
import pytest_asyncio

from co_scientist.application.cockpit import snapshot
from co_scientist.application.cockpit_control import control_run
from co_scientist.application.config import resolve_run_config
from co_scientist.runtime.core_runner import CoreRunner
from tests.core_preview_support import write_core_preview_inputs


@pytest_asyncio.fixture
async def live(tmp_path: Path):
    goal, profile, environment = write_core_preview_inputs(tmp_path, novelty_verdict="novel")
    config = resolve_run_config(goal_file=goal, profile_file=profile,
                                provider="replay", environment=environment)
    runner = CoreRunner(data_dir=tmp_path / "data", environment=environment)
    result = await runner.execute(config=config)
    yield tmp_path / "data" / "co-scientist.db", result.run_id, result.last_sequence
    runner.uow.engine.dispose()


@pytest.mark.asyncio
async def test_pause_resume_stop_events_without_worker(live) -> None:
    db, run_id, seq = live
    for action, expected in [("pause", "paused"), ("resume", "running"), ("stop", "stopping")]:
        before = snapshot(db, run_id)
        result = control_run(db, run_id, {"action": action, "expected_sequence": seq,
                                         "confirmed": True})
        assert result["ok"], result
        assert result["worker_started"] is False
        assert "worker run" in result["worker_command"]
        after = snapshot(db, run_id)
        assert after["manifest"]["final_state"] == expected
        assert len(after["external_calls"]) == len(before["external_calls"])
        seq = result["current_sequence"]
    assert after["events"][-1]["event_type"] != "RunCompleted"


@pytest.mark.asyncio
async def test_stale_and_disallowed_commands_do_not_write(live) -> None:
    db, run_id, seq = live
    before = snapshot(db, run_id)
    for payload in [
        {"action": "pause", "expected_sequence": seq - 1, "confirmed": True},
        {"action": "resume", "expected_sequence": seq, "confirmed": True},
    ]:
        assert control_run(db, run_id, payload)["status"] == 409
    assert snapshot(db, run_id) == before


@pytest.mark.parametrize("payload", [
    {}, {"action": "cancel", "expected_sequence": 0, "confirmed": True},
    {"action": "pause", "expected_sequence": True, "confirmed": True},
    {"action": "pause", "expected_sequence": 0, "confirmed": "true"},
    {"action": "pause", "expected_sequence": 0, "confirmed": False},
    {"action": "pause", "expected_sequence": 0, "confirmed": True, "run_id": "injected"},
])
def test_invalid_request_does_not_create_database(tmp_path: Path, payload: object) -> None:
    db = tmp_path / "absent.db"
    assert control_run(db, "run", payload)["status"] == 422
    assert not db.exists()


def test_missing_database_is_not_created(tmp_path: Path) -> None:
    db = tmp_path / "absent.db"
    assert control_run(db, "run", {"action": "pause", "expected_sequence": 0,
                                    "confirmed": True})["status"] == 404
    assert not db.exists()
