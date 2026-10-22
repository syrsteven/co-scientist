"""Separate process: original RunService owns all scientific execution."""

import asyncio
import json
import os
import socket
import sys

from co_scientist.release.service import RunService, load

from .store import Store


def main():
    store = Store(sys.argv[1])
    run_id = sys.argv[2]
    lock_fd = int(sys.argv[3])
    root = store.run_root(run_id)
    environment = json.loads(sys.stdin.buffer.read(32768))
    plan = load(root / "plan.json")
    if plan["mode"] == "MOCK_ONLY":
        environment = {}

        def deny(*args, **kwargs):
            raise RuntimeError("MOCK_ONLY: real sockets forbidden")

        socket.socket.connect = deny
        socket.socket.connect_ex = deny
    try:
        store.job(run_id, pid=os.getpid(), state="running")
        asyncio.run(RunService(environment=environment).execute(root))
        store.job(run_id, pid=os.getpid(), state="finished")
    except Exception:  # noqa: BLE001 -- isolate driver faults, preserve native recoverable history
        # Do not expose provider exception/body or mutate native history. A
        # nonterminal native Run is explicitly interrupted and needs native resume.
        store.job(run_id, pid=os.getpid(), state="interrupted_needs_review")
    finally:
        environment.clear()
        os.close(lock_fd)


if __name__ == "__main__":
    main()
