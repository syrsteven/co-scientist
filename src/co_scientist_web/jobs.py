"""Detached driver, OS locks and durable Web job metadata (not science state)."""

import builtins
import fcntl
import json
import os
import re
import subprocess
import sys
import threading

from co_scientist.release.service import RunService

from .diagnostics import FIELDS, Diagnostics

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
    log = getattr(store, "diagnostics", None) or Diagnostics(store.path("logs/workbench.jsonl"))
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
        read_fd, write_fd = os.pipe()
        try:
            # Credentials travel only over a private anonymous stdin pipe. Never
            # argv, files, durable job metadata, shell, progress logs or exports.
            child_env = {
                k: v
                for k, v in os.environ.items()
                if k in {"PATH", "PYTHONPATH", "CO_SCIENTIST_RESOURCE_DIR", "LANG", "TMPDIR"}
            }
            child_env["PYTHONDONTWRITEBYTECODE"] = "1"
            child_env["CO_SCIENTIST_DIAGNOSTIC_FD"] = str(write_fd)
            child_env["CO_SCIENTIST_LOG_LEVEL"] = getattr(store, "log_level", "INFO")
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
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                pass_fds=(lock.fileno(), write_fd),
                env=child_env,
            )
            os.close(write_fd)
            write_fd = None
            readers = start_readers(process, read_fd, log, run_id)
            read_fd = None  # Reader owns its descriptor.
            store.job(run_id, pid=process.pid, state="starting")
            process.stdin.write(json.dumps(environment).encode())
            process.stdin.close()
            log.emit("driver.spawned", run_id=run_id, phase="launch", pid=process.pid)
            # Observational reaper only; never restart/retry or mutate native state.
            threading.Thread(target=reap, args=(process, readers, store, run_id, log),
                             daemon=True).start()
            return store.job(run_id)
        except Exception as error:  # noqa: BLE001 -- no native mutation/retry
            if process is not None:
                process.terminate()
            error_id = log.error(error, phase="launch", run_id=run_id, code="DRIVER_LAUNCH_FAILED")
            store.job(run_id, state="launch_failed",
                      diagnostic={"code": "DRIVER_LAUNCH_FAILED", "error_id": error_id,
                                  "phase": "launch"})
            raise ValueError("background launch failed") from None
        finally:
            for fd in (read_fd, write_fd):
                if fd is not None:
                    os.close(fd)
            lock.close()


def start_readers(process, read_fd, log, run_id):
    def forward():
        # Only the dedicated structured pipe is forwarded. Arbitrary provider or
        # library stdout/stderr must never be parsed as trusted diagnostic JSON.
        with os.fdopen(read_fd, "rb") as stream:
            for line in iter(lambda: stream.readline(256_000), b""):
                try:
                    record = json.loads(line)
                    level = record.get("level", "INFO")
                    if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
                        continue
                    log.emit(record["event"], level=level,
                             **{k: v for k, v in record.items() if k in FIELDS})
                except (ValueError, KeyError, TypeError):
                    log.emit("driver.diagnostic_record_invalid", level="WARNING",
                             run_id=run_id, phase="log_forward")

    def output(stream, name):
        total = 0
        pending, frames, exception_type = b"", [], None

        def metadata(line):
            nonlocal exception_type
            # Bootstrap/import errors can occur before the safe logger starts.
            # Recognize traceback *structure* only, never its message/source line.
            text = line.decode("utf-8", errors="replace")
            match = re.fullmatch(r'  File "([^"\n]+)", line ([0-9]+), in ([\w<>]+)', text)
            if match and len(frames) < 24:
                from pathlib import Path

                name = Path(match[1]).name
                frames.append({"file": name if name in {"driver.py", "app.py", "jobs.py",
                               "__main__.py", "diagnostics.py"} else "python_frame",
                               "line": int(match[2]), "function": match[3] if match[3] in {
                                   "main", "run_driver", "launch", "<module>"} else "omitted"})
            match = re.match(r"^([A-Za-z_][\w.]*(?:Error|Exception)):", text)
            if match:
                candidate = getattr(builtins, match[1], None)
                exception_type = (match[1] if isinstance(candidate, type) and
                                  issubclass(candidate, BaseException) else "UnrecognizedException")

        with stream:
            while chunk := stream.read(4096):
                total += len(chunk)
                if name == "stderr":
                    pending += chunk
                    lines = pending.split(b"\n")
                    pending = lines.pop()[-4096:]
                    for line in lines:
                        metadata(line[:4096])
        if pending:
            metadata(pending)
        if total:
            log.emit("driver.output_omitted", level="WARNING", run_id=run_id,
                     phase="driver_output", stream=name, bytes=total, frames=frames,
                     exception_type=exception_type)

    threads = [threading.Thread(target=forward, daemon=True),
               threading.Thread(target=output, args=(process.stdout, "stdout"), daemon=True),
               threading.Thread(target=output, args=(process.stderr, "stderr"), daemon=True)]
    for thread in threads:
        thread.start()
    return threads


def reap(process, readers, store, run_id, log):
    code = process.wait()
    for thread in readers:
        thread.join(timeout=2)
    log.emit("driver.exited", level="WARNING" if code else "INFO", run_id=run_id,
             phase="process_exit", exit_code=code, pid=process.pid)
    if code:
        # SIGKILL cannot run Python handlers. Preserve this Web-only observation;
        # status still reads authoritative native state and OS driver lock.
        previous = store.job(run_id)
        detail = (previous.get("diagnostic") or {}) if previous.get("pid") == process.pid else {}
        if not detail.get("error_id"):
            from uuid import uuid4

            detail = {"code": "DRIVER_PROCESS_EXIT", "phase": "process_exit",
                      "error_id": "err-" + uuid4().hex, "exit_code": code}
        log.emit("driver.abnormal_exit", level="ERROR", run_id=run_id,
                 phase="process_exit", exit_code=code, error_id=detail["error_id"])
        store.observed_exit(run_id, process.pid, detail)
