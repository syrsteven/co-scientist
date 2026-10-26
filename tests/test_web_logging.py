"""Offline diagnostics: useful provenance, never request/exception content."""

import json
import logging
import os
import sqlite3
import subprocess
import sys
from types import SimpleNamespace

import pytest

from co_scientist.release.service import RunService
from co_scientist_web.diagnostics import Diagnostics, SafeFormatter, tail
from co_scientist_web.driver import run_driver
from co_scientist_web.jobs import reap, start_readers
from co_scientist_web.progress import Progress
from co_scientist_web.store import Store
from tests.test_web import GOAL, client


@pytest.mark.asyncio
async def test_preflight_error_has_local_diagnostics_not_secret_text(tmp_path, monkeypatch):
    def broken(*args, **kwargs):
        raise ValueError("sk-secret-canary response=private-science email=private@example.test")

    monkeypatch.setattr(RunService, "validate", broken)
    _app, c = await client(tmp_path)
    async with c:
        response = await c.post("/api/v1/config/preflight", json={"goal": GOAL})
    assert response.status_code == 422
    assert response.json()["error_id"]
    logs = (tmp_path / "logs/workbench.jsonl").read_text()
    entry = next(json.loads(line) for line in logs.splitlines()
                 if json.loads(line).get("error_id") == response.json()["error_id"])
    assert entry["exception_type"] == "ValueError"
    assert entry["phase"] == "preflight"
    assert entry["frames"][-1]["function"] == "broken"
    assert entry["frames"][-1]["line"] > 0
    assert "sk-secret-canary" not in logs + response.text
    assert "private-science" not in logs + response.text


@pytest.mark.asyncio
async def test_api_safe_correlation_and_unexpected_failure(tmp_path):
    app, c = await client(tmp_path)

    @app.get("/api/v1/test-failure")
    def broken():
        raise RuntimeError("Bearer sensitive-provider-response")

    async with c:
        response = await c.get("/api/v1/test-failure?secret=query-canary",
                               headers={"Authorization": "Bearer header-canary",
                                        "X-Request-ID": "untrusted-id"})
    assert response.status_code == 500
    assert response.json()["error_id"]
    assert response.headers["x-request-id"] != "untrusted-id"
    logs = (tmp_path / "logs/workbench.jsonl").read_text()
    assert response.json()["error_id"] in logs
    assert response.headers["x-request-id"] in logs
    for secret in ("query-canary", "header-canary", "sensitive-provider-response"):
        assert secret not in logs + response.text


def test_driver_exception_and_causes_are_locatable_without_bodies(tmp_path, monkeypatch):
    store = Store(tmp_path)
    store.save("run", {}, "r")

    class Native:
        async def execute(self, root):
            try:
                raise OSError("Authorization: secret-inner-body")
            except OSError as error:
                raise ValueError("private-outer-result") from error

        def status(self, root):
            return {"state": "running", "events": 7}

    monkeypatch.setattr("co_scientist_web.driver.RunService", lambda **kwargs: Native())
    run_driver(store, "r", {})
    job = store.job("r")
    assert job["state"] == "interrupted_needs_review"
    assert job["diagnostic"]["error_id"]
    assert job["diagnostic"]["exception_type"] == "ValueError"
    assert job["diagnostic"]["causes"][0]["exception_type"] == "OSError"
    records = tail(store.run_root("r") / "logs/driver.jsonl")
    assert job["diagnostic"]["error_id"] in json.dumps(records)
    assert "secret-inner-body" not in json.dumps(records) + json.dumps(job)
    assert "private-outer-result" not in json.dumps(records) + json.dumps(job)
    assert not (store.run_root("r") / "runtime").exists()


def test_foreign_logs_never_format_message_or_exception(tmp_path):
    record = logging.LogRecord("httpx", logging.ERROR, __file__, 1,
                               "Authorization: %s", ("sk-canary",), None)
    assert "sk-canary" not in SafeFormatter().format(record)
    try:
        raise RuntimeError("response-body-canary")
    except RuntimeError:
        record.exc_info = sys.exc_info()
    text = SafeFormatter().format(record)
    assert "RuntimeError" in text and "response-body-canary" not in text


@pytest.mark.parametrize("name", ["third.party", "workbench.observation"])
def test_extra_safe_record_does_not_grant_trust(tmp_path, name):
    log = Diagnostics(tmp_path / "driver.jsonl", console=False)
    forged = {"event": "forged", "body": "sk-forged-canary", "run_id": "private-run-canary"}
    foreign = logging.Logger(name)  # noqa: LOG001 -- isolated untrusted logger, no global state
    foreign.handlers[:] = log.logger.handlers
    foreign.warning("ignored", extra={"safe_record": forged})
    log.emit("internal.progress", run_id="r", phase="generation")
    records = tail(log.path)
    assert records[0]["event"] == "library.log_omitted"
    assert "sk-forged-canary" not in json.dumps(records)
    assert "private-run-canary" not in json.dumps(records)
    assert records[1]["event"] == "internal.progress"
    log.close()


def test_custom_unhashable_foreign_record_is_safely_downgraded():
    class ForeignRecord(logging.LogRecord):
        __hash__ = None

    record = ForeignRecord("third.party", logging.WARNING, __file__, 1,
                           "sk-message-canary", (), None)
    record.safe_record = {"event": "forged", "body": "sk-extra-canary"}
    result = SafeFormatter().format(record)
    assert json.loads(result)["event"] == "library.log_omitted"
    assert "sk-message-canary" not in result and "sk-extra-canary" not in result


@pytest.mark.asyncio
async def test_status_lost_observation_cannot_overwrite_concurrent_resume(tmp_path, monkeypatch):
    from tests.test_web import prepare

    app, c = await client(tmp_path)
    async with c:
        run = await prepare(c)
        store = app.state.store
        store.job(run, pid=111, state="running")
        monkeypatch.setattr(RunService, "status", lambda *a: {"state": "running", "events": 230})
        calls = []

        def raced_lock_observation(root):
            if not calls:
                calls.append(True)
                store.job(run, pid=222, state="running", diagnostic={"code": "NEW_DRIVER"})
                return False  # Lock observation predates the concurrent resume.
            return True

        monkeypatch.setattr("co_scientist_web.app.driver_alive", raced_lock_observation)
        response = await c.get(f"/api/v1/runs/{run}/status")
    assert response.status_code == 200
    assert store.job(run)["pid"] == 222
    assert store.job(run)["state"] == "running"
    assert store.job(run)["diagnostic"] == {"code": "NEW_DRIVER"}
    assert response.json()["job"]["pid"] == 222
    assert response.json()["job"]["alive"]


@pytest.mark.parametrize("operation", ["fileno", "buffer", "closed_parent"])
def test_driver_preserves_standard_streams(tmp_path, operation):
    script = r'''
import json, os, subprocess, sys
from pathlib import Path
from co_scientist_web import driver
from co_scientist_web.store import Store
store = Store(sys.argv[1])
store.save("run", {}, "r")
root = store.run_root("r")
root.mkdir(parents=True)
(root / "plan.json").write_text('{"mode":"MOCK_ONLY"}')
operation = sys.argv[2]
original_stdout, original_stderr = sys.stdout, sys.stderr
class Native:
    done = False
    async def execute(self, root):
        if operation == "fileno":
            assert sys.stdout.fileno() == 1 and sys.stderr.fileno() == 2
        else:
            sys.stdout.buffer.write(b"private-binary-canary\n")
            sys.stderr.buffer.write(b"private-stderr-canary\n")
        # Native TextIOWrapper APIs must remain available, not just text write().
        sys.stdout.reconfigure(write_through=True)
        os.write(sys.stdout.fileno(), b"private-fd-canary\n")
        subprocess.run([sys.executable, "-c", "print('private-child-canary')"], check=True)
        self.done = True
    def status(self, root):
        return {"state":"completed" if self.done else "running", "events":0}
driver.RunService = lambda **kwargs: Native()
fd = os.open(root / "web-job.lock", os.O_CREAT | os.O_WRONLY, 0o600)
sys.argv = ["driver", str(store.root), "r", str(fd)]
driver.main()
assert sys.stdout is original_stdout and sys.stderr is original_stderr
if operation != "closed_parent":
    print("DRIVER_INTERFACES_OK")
'''
    command = [sys.executable, "-c", script, str(tmp_path), operation]
    if operation == "closed_parent":
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
        # Close parent-side readers *before* allowing driver.main's stdin read to
        # complete. Binary/fd/subprocess output must still work after Web exits.
        process.stdout.close()
        process.stderr.close()
        process.stdin.write(b"{}")
        process.stdin.close()
        result = SimpleNamespace(returncode=process.wait(timeout=20), stdout=b"", stderr=b"")
    else:
        result = subprocess.run(command, input=b"{}", capture_output=True, timeout=20, check=False)
    assert result.returncode == 0
    assert Store(tmp_path).job("r")["state"] == "finished"
    evidence = result.stdout + result.stderr + (tmp_path / "runs/r/logs/driver.jsonl").read_bytes()
    for secret in (b"private-binary-canary", b"private-stderr-canary", b"private-fd-canary",
                   b"private-child-canary"):
        assert secret not in evidence


def test_lost_observation_cannot_overwrite_advanced_state_for_same_pid(tmp_path):
    store = Store(tmp_path)
    store.save("run", {}, "r")
    store.job("r", pid=111, state="finished", diagnostic={"code": "NATIVE_TERMINAL"})
    assert not store.observed_exit("r", 111, {"code": "STALE_OBSERVATION"},
                                   expected_state="running")
    assert store.job("r")["state"] == "finished"
    assert store.job("r")["diagnostic"] == {"code": "NATIVE_TERMINAL"}


def test_progress_reads_only_committed_metadata_and_does_not_write(tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    dbpath = runtime / "co-scientist.db"
    with sqlite3.connect(dbpath) as db:
        db.execute("CREATE TABLE events(sequence INTEGER,event_type TEXT,payload_json TEXT)")
        db.executemany("INSERT INTO events VALUES (?,?,?)", [
            (1, "TaskEnqueued", json.dumps({"task_id": "task-1", "payload": {
                "output_schema_id": "DirectiveEthicsResultV1", "inputs": "secret-science"}})),
            (2, "DirectiveEthicsRecordedV1", '{"verdict":"PASS","body":"secret-science"}'),
            (3, "secret-event-canary", '{}'),
        ])
    before = dbpath.read_bytes()
    log = Diagnostics(tmp_path / "logs/driver.jsonl", console=False)
    observer = Progress(tmp_path, "r", log)
    observer.drain()
    observer.drain()
    records = tail(log.path)
    assert [r["sequence"] for r in records] == [1, 2]
    assert records[0]["task_id"] == "task-1"
    assert "secret-science" not in json.dumps(records)
    assert "secret-event-canary" not in json.dumps(records)
    assert dbpath.read_bytes() == before
    log.close()


def test_rotating_private_logs_and_bounded_tail(tmp_path):
    log = Diagnostics(tmp_path / "logs/workbench.jsonl", console=False, level="DEBUG")
    log.logger.handlers[0].maxBytes = 1000
    for n in range(100):
        log.emit("sample", sequence=n)
    assert len(list(log.path.parent.glob("*.jsonl*"))) <= 5
    assert tail(log.path, 1)[0]["sequence"] == 99
    assert log.path.stat().st_mode & 0o777 == 0o600
    log.close()


def test_disconnected_web_pipe_cannot_stop_driver_file_logging(tmp_path):
    read_fd, write_fd = os.pipe()
    os.close(read_fd)  # Web process exited; detached driver must still work.
    stream = os.fdopen(write_fd, "w")
    try:
        log = Diagnostics(tmp_path / "driver.jsonl", stream=stream)
        log.emit("driver.still_running", run_id="r", phase="execute")
        records = tail(log.path)
        assert records[-1]["event"] == "driver.still_running"
        assert "sk-private-output" not in json.dumps(records)
        log.close()
    finally:
        try:
            stream.close()
        except BrokenPipeError:
            pass  # Same explicit shutdown handling as the detached driver.


def test_child_stdout_stderr_and_abnormal_exit_do_not_silently_disappear(tmp_path):
    store = Store(tmp_path)
    store.save("run", {}, "r")
    log = Diagnostics(tmp_path / "logs/workbench.jsonl", console=False)
    read_fd, write_fd = os.pipe()
    script = """
import os, sys
from co_scientist_web.diagnostics import Diagnostics
stream = os.fdopen(int(sys.argv[1]), 'w')
log = Diagnostics(sys.argv[2], stream=stream)
log.emit('driver.test_progress', run_id='r', phase='generation')
print('sk-stdout-canary')
print('provider-response-canary', file=sys.stderr)
print('  File "/private/sk_path_secret.py", line 1, in sk_function_secret', file=sys.stderr)
print('sk_type_secretError: body-secret', file=sys.stderr)
print('ModuleNotFoundError: secret-package-name', file=sys.stderr)
log.close()
stream.close()
sys.exit(7)
"""
    child = subprocess.Popen([sys.executable, "-c", script, str(write_fd),
                              str(tmp_path / "runs/r/logs/driver.jsonl")],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             pass_fds=(write_fd,))
    os.close(write_fd)
    readers = start_readers(child, read_fd, log, "r")
    store.job("r", pid=child.pid, state="running")
    reap(child, readers, store, "r", log)
    records = tail(log.path)
    assert any(r["event"] == "driver.test_progress" for r in records)
    assert {r["stream"] for r in records if r["event"] == "driver.output_omitted"} == {
        "stdout", "stderr"}
    assert store.job("r")["diagnostic"]["exit_code"] == 7
    assert store.job("r")["diagnostic"]["error_id"]
    assert "sk-stdout-canary" not in json.dumps(records)
    assert "provider-response-canary" not in json.dumps(records)
    for secret in ("sk_path_secret", "sk_function_secret", "sk_type_secret", "secret-package-name"):
        assert secret not in json.dumps(records)
    stderr = next(r for r in records if r.get("stream") == "stderr")
    assert stderr["exception_type"] == "ModuleNotFoundError"
    assert stderr["frames"][0]["file"] == "python_frame"
    log.close()


def test_old_process_reaper_cannot_overwrite_resumed_driver(tmp_path):
    store = Store(tmp_path)
    store.save("run", {}, "r")
    store.job("r", pid=222, state="running", diagnostic={"code": "CURRENT_DRIVER"})
    log = Diagnostics(tmp_path / "logs/workbench.jsonl", console=False)
    old = SimpleNamespace(pid=111, wait=lambda: -9)
    reap(old, [], store, "r", log)
    assert store.job("r")["pid"] == 222
    assert store.job("r")["state"] == "running"
    assert store.job("r")["diagnostic"] == {"code": "CURRENT_DRIVER"}
    log.close()


@pytest.mark.asyncio
async def test_logs_endpoint_is_authenticated_read_only_and_bounded(tmp_path):
    from tests.test_web import prepare

    app, c = await client(tmp_path)
    async with c:
        run = await prepare(c)
        root = app.state.store.run_root(run)
        log = Diagnostics(root / "logs/driver.jsonl", console=False)
        log.emit("driver.test", run_id=run, phase="execute")
        log.close()
        response = await c.get(f"/api/v1/runs/{run}/logs?limit=1")
        assert response.status_code == 200
        assert response.json()["records"][0]["run_id"] == run
        assert not (root / "runtime").exists()
        assert (await c.get(f"/api/v1/runs/{run}/logs?limit=501")).status_code == 422
        assert (await c.get(f"/api/v1/runs/{run}/logs", headers={"Cookie": ""})).status_code == 403


@pytest.mark.asyncio
async def test_application_lifespan_records_start_and_shutdown(tmp_path):
    app, c = await client(tmp_path)
    async with c, app.router.lifespan_context(app):
        assert (await c.get("/api/v1/settings/status")).status_code == 200
    events = [r["event"] for r in tail(tmp_path / "logs/workbench.jsonl")]
    assert events.index("web.application_ready") < events.index("web.application_stopping")
