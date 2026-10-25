"""Separate process: original RunService owns all scientific execution."""

import asyncio
import json
import os
import socket
import sys
from contextlib import redirect_stderr, redirect_stdout
from uuid import uuid4

from co_scientist.release.service import RunService, load

from .diagnostics import Diagnostics, OutputSummary, configure_libraries, exception_detail
from .jobs import TERMINAL
from .progress import Progress
from .store import Store


def run_driver(store, run_id, environment, log=None):
    """Web process observations never replace authoritative Native state."""
    native = RunService(environment=environment)
    root = store.run_root(run_id)
    owned_log = log is None
    log = log or Diagnostics(root / "logs/driver.jsonl")
    error_id, detail = None, {}
    code, phase = "NATIVE_NONTERMINAL_RETURN", "execute"
    log.emit("driver.started", run_id=run_id, phase=phase)
    try:
        store.job(run_id, pid=os.getpid(), state="running")
        with Progress(root, run_id, log):
            asyncio.run(native.execute(root))
        phase = "native_status"
    except Exception as error:  # noqa: BLE001 -- no exception text/body may escape
        code = {ValueError: "NATIVE_EXECUTION_REJECTED", OSError: "LOCAL_IO_FAILURE"}.get(
            type(error), "DRIVER_EXECUTION_FAILED")
        error_id = log.error(error, phase=phase, run_id=run_id, code=code)
        detail = exception_detail(error)
    try:
        status = native.status(root)
    except Exception as error:  # noqa: BLE001 -- status unavailable must remain uncertain
        status_error_id = log.error(error, phase="native_status", run_id=run_id,
                                    code="NATIVE_STATUS_UNAVAILABLE")
        if error_id is None:
            error_id, detail = status_error_id, exception_detail(error)
        status = {"state": "unknown", "events": None}
    terminal = status["state"] in TERMINAL
    if not terminal and error_id is None:
        error_id = "err-" + uuid4().hex
        log.emit("driver.nonterminal_return", level="WARNING", run_id=run_id,
                 phase=phase, code=code, error_id=error_id, sequence=status.get("events"))
    store.job(run_id, pid=os.getpid(), state="finished" if terminal else "interrupted_needs_review",
              diagnostic={"code": "NATIVE_TERMINAL" if terminal else code,
                          "phase": phase, "native_state": status["state"],
                          "last_event_sequence": status.get("events"),
                          "error_id": error_id, **detail})
    log.emit("driver.finished" if terminal else "driver.interrupted", run_id=run_id,
             level="INFO" if terminal else "WARNING", phase=phase, error_id=error_id,
             native_state=status["state"], sequence=status.get("events"))
    if owned_log:
        log.close()


def main():
    store = Store(sys.argv[1])
    run_id = sys.argv[2]
    lock_fd = int(sys.argv[3])
    root = store.run_root(run_id)
    environment = {}
    # A dedicated diagnostics pipe is distinct from untrusted stdout/stderr.
    log_fd = os.environ.get("CO_SCIENTIST_DIAGNOSTIC_FD")
    stream = os.fdopen(int(log_fd), "w", buffering=1) if log_fd else None
    log = Diagnostics(root / "logs/driver.jsonl",
                      level=os.environ.get("CO_SCIENTIST_LOG_LEVEL", "INFO"), stream=stream)
    configure_libraries(log)
    try:
        environment = json.loads(sys.stdin.buffer.read(32768))
        plan = load(root / "plan.json")
        if plan["mode"] == "MOCK_ONLY":
            environment = {}

            def deny(*args, **kwargs):
                raise RuntimeError("MOCK_ONLY: real sockets forbidden")

            socket.socket.connect = deny
            socket.socket.connect_ex = deny
        stdout = OutputSummary(log, run_id, "stdout")
        stderr = OutputSummary(log, run_id, "stderr")
        try:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                run_driver(store, run_id, environment, log)
        finally:
            stdout.flush()
            stderr.flush()
    except Exception as error:  # noqa: BLE001 -- isolate driver faults, preserve native recoverable history
        # Do not expose provider exception/body or mutate native history. A
        # nonterminal native Run is explicitly interrupted and needs native resume.
        error_id = log.error(error, phase="bootstrap", run_id=run_id, code="DRIVER_BOOTSTRAP_FAILED")
        store.job(run_id, pid=os.getpid(), state="interrupted_needs_review", diagnostic={
            "code": "DRIVER_BOOTSTRAP_FAILED", "phase": "bootstrap",
            "last_event_sequence": None, "native_state": "unknown", "error_id": error_id,
            **exception_detail(error)})
    finally:
        environment.clear()
        os.close(lock_fd)
        log.close()
        if stream:
            try:
                stream.close()
            except OSError:
                pass  # Parent disconnected; durable file already closed safely.


if __name__ == "__main__":
    main()
