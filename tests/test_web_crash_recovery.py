"""SIGKILL at synthetic delivery/raw boundaries; never send a real request."""

import asyncio
import json
import os
import sqlite3
import subprocess
import sys

import pytest

CHILD = """
import asyncio, socket, sys, time
from pathlib import Path
from co_scientist.release.service import RunService
from co_scientist.release.mock_http import MockHTTP
from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork
def deny(*a, **k): raise AssertionError('child denies real sockets')
socket.socket.connect = deny
socket.socket.connect_ex = deny
marker = Path(sys.argv[2])
if sys.argv[3] == 'delivery':
    original = MockHTTP.__call__
    async def hold(self, request):
        result = await original(self, request)
        marker.write_text('synthetic response in memory, not captured')
        await asyncio.sleep(120)
        return result
    MockHTTP.__call__ = hold
else:
    original = SqliteUnitOfWork.record_raw_and_transition
    def hold(self, *args, **kwargs):
        marker.write_text('domain raw durable, no domain apply')
        time.sleep(120)
        return original(self, *args, **kwargs)
    SqliteUnitOfWork.record_raw_and_transition = hold
asyncio.run(RunService(environment={}).execute(Path(sys.argv[1])))
"""


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["delivery", "raw"])
async def test_kill_and_explicit_stop_preserve_raw_and_no_resend(tmp_path, boundary):
    from tests.test_release import create
    service, root = create(tmp_path, mock=True)
    service.authorize(root, confirm=True, accept_usd="60")
    marker = tmp_path / "kill-boundary"
    child = await asyncio.to_thread(subprocess.Popen,
        [sys.executable, "-c", CHILD, str(root), str(marker), boundary],
        env=os.environ.copy(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(300):
            if marker.exists():
                break
            assert child.poll() is None, "fault-injection child exited before boundary"
            await asyncio.sleep(.1)
        else:
            pytest.fail("crash boundary not reached")
        child.kill()
        await asyncio.to_thread(child.wait, timeout=10)
        assert service.status(root)["state"] == "running"
        run_id = service.status(root)["run_id"]
        ledger = root / "runtime/dispatch" / run_id / "dispatch.sqlite3"
        with sqlite3.connect(ledger) as db:
            before = db.execute("SELECT id FROM attempts ORDER BY id").fetchall()
        assert before
        service.stop(root)
        result = await service.execute(root)
        assert result["state"] == "completed_partial" and result["final"]["winner_id"] is None
        with sqlite3.connect(ledger) as db:
            assert db.execute("SELECT id FROM attempts ORDER BY id").fetchall() == before
        events = service.events(root)
        assert not any(e["event_type"] == "DirectiveEthicsRecordedV1" for e in events)
        timeline = json.loads((root / "exports/run-timeline.json").read_bytes())
        assert not timeline["cost_entries"]  # No fabricated zero-cost settlement.
        assert result["accounting"]["actively_reserved"]["cost_usd"] != "0"
        await service.execute(root)
        assert service.events(root) == events
    finally:
        if child.poll() is None:
            child.kill()
            await asyncio.to_thread(child.wait, timeout=10)
