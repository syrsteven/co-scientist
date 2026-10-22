"""Detached driver, OS locks and durable Web job metadata (not science state)."""

import fcntl
import json
import os
import subprocess
import sys

from co_scientist.release.service import RunService

TERMINAL = {"completed", "completed_partial", "failed", "cancelled"}


def driver_alive(root):
    path = root / "web-job.lock"
    if not path.exists():
        return False
    with path.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
    return False


def launch(store, run_id, environment):
    root = store.run_root(run_id)
    service = RunService(environment=environment)
    service._verify(root)  # Preserve original code/profile/budget checks before any spawn.
    if service.status(root)["state"] in TERMINAL:
        return {**store.job(run_id), "state": "terminal_no_dispatch"}
    with store.path("launch.lock").open("a") as global_lock:
        fcntl.flock(global_lock, fcntl.LOCK_EX)
        lock = (root / "web-job.lock").open("a")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close()
            return store.job(run_id)
        process = None
        try:
            # Credentials travel only over a private anonymous stdin pipe. Never
            # argv, files, durable job metadata, shell, progress logs or exports.
            child_env = {
                k: v
                for k, v in os.environ.items()
                if k in {"PATH", "PYTHONPATH", "CO_SCIENTIST_RESOURCE_DIR", "LANG", "TMPDIR"}
            }
            child_env["PYTHONDONTWRITEBYTECODE"] = "1"
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "co_scientist_web.driver",
                    str(store.root),
                    run_id,
                    str(lock.fileno()),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                pass_fds=(lock.fileno(),),
                env=child_env,
            )
            store.job(run_id, pid=process.pid, state="starting")
            process.stdin.write(json.dumps(environment).encode())
            process.stdin.close()
            # Reap without owning/cancelling the independent driver's lifetime.
            import threading

            threading.Thread(target=process.wait, daemon=True).start()
            return store.job(run_id)
        except Exception:  # noqa: BLE001 -- process-launch boundary; never marks science successful
            if process is not None:
                process.terminate()
            store.job(run_id, state="launch_failed")
            raise ValueError("background launch failed") from None
        finally:
            lock.close()
