"""Separate process: original RunService owns all scientific execution."""

import asyncio
import json
import os
import socket
import sys

from co_scientist.release.service import RunService, load

from .jobs import TERMINAL
from .store import Store


def run_driver(store, run_id, environment):
    """Web process observations never replace authoritative Native state."""
    native = RunService(environment=environment)
    root = store.run_root(run_id)
    code, phase = "NATIVE_NONTERMINAL_RETURN", "execute"
    try:
        store.job(run_id, pid=os.getpid(), state="running")
        asyncio.run(native.execute(root))
        phase = "native_status"
    except Exception as error:  # noqa: BLE001 -- no exception text/body may escape
        code = {ValueError: "NATIVE_EXECUTION_REJECTED", OSError: "LOCAL_IO_FAILURE"}.get(
            type(error), "DRIVER_EXECUTION_FAILED")
    try:
        status = native.status(root)
    except Exception:  # noqa: BLE001 -- status unavailable must remain uncertain
        status = {"state": "unknown", "events": None}
    terminal = status["state"] in TERMINAL
    store.job(run_id, pid=os.getpid(), state="finished" if terminal else "interrupted_needs_review",
              diagnostic={"code": "NATIVE_TERMINAL" if terminal else code,
                          "phase": phase, "native_state": status["state"],
                          "last_event_sequence": status.get("events")})


def main():
    store = Store(sys.argv[1])
    run_id = sys.argv[2]
    lock_fd = int(sys.argv[3])
    root = store.run_root(run_id)
    environment = {}
    try:
        environment = json.loads(sys.stdin.buffer.read(32768))
        plan = load(root / "plan.json")
        if plan["mode"] == "MOCK_ONLY":
            environment = {}

            def deny(*args, **kwargs):
                raise RuntimeError("MOCK_ONLY: real sockets forbidden")

            socket.socket.connect = deny
            socket.socket.connect_ex = deny
        run_driver(store, run_id, environment)
    except Exception:  # noqa: BLE001 -- isolate driver faults, preserve native recoverable history
        # Do not expose provider exception/body or mutate native history. A
        # nonterminal native Run is explicitly interrupted and needs native resume.
        store.job(run_id, pid=os.getpid(), state="interrupted_needs_review", diagnostic={
            "code": "DRIVER_BOOTSTRAP_FAILED", "phase": "bootstrap",
            "last_event_sequence": None, "native_state": "unknown"})
    finally:
        environment.clear()
        os.close(lock_fd)


if __name__ == "__main__":
    main()
