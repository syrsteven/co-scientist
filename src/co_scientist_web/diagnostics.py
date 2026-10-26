"""Local, allowlisted diagnostics. Never format exception text, locals or bodies.

These records are observations, not scientific events or recovery authority.
Only this module's structured fields reach the sinks, even in DEBUG mode.
"""

import json
import logging
import os
import re
import select
import sys
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from uuid import uuid4

request_id = ContextVar("workbench_request_id", default=None)
# Object identity is registered only during our synchronous handler call. No
# LogRecord attribute (including extra.safe_record or a logger name) grants trust.
_INTERNAL_RECORDS: dict[int, tuple[logging.LogRecord, dict]] = {}
_RECORD_LOCK = threading.RLock()
FIELDS = {
    "request_id", "error_id", "run_id", "phase", "code", "exception_type",
    "exception_module", "frames", "causes", "route", "method", "status",
    "duration_ms", "sequence", "event_type", "native_state", "pid", "exit_code",
    "stream", "bytes", "task_id", "source", "port", "live_enabled", "hint",
}
HINTS = {
    "tokenizer missing; run co-scientist ideation resources before creating a Run":
        "TOKENIZER_MISSING_RUN_EXPLICIT_RESOURCE_INSTALL",
    "TOKENIZER_IDENTITY_MISMATCH": "TOKENIZER_SHA_MISMATCH",
    "custom profile differs from frozen release configuration": "FROZEN_PROFILE_MISMATCH",
    "frozen Run/code/budget identity mismatch": "FROZEN_IDENTITY_MISMATCH",
}


def token(value):
    """Identifiers only, not a general-purpose secret redactor."""
    return value if isinstance(value, str) and re.fullmatch(r"[\w.:/-]{1,240}", value) else "omitted"


def exception_detail(error):
    def describe(exc):
        frames = []
        tb = exc.__traceback__
        while tb is not None:
            code = tb.tb_frame.f_code
            frames.append({"file": token(Path(code.co_filename).name),
                           "module": token(tb.tb_frame.f_globals.get("__name__", "unknown")),
                           "function": token(code.co_name), "line": tb.tb_lineno})
            tb = tb.tb_next
        return {"exception_type": token(type(exc).__name__),
                "exception_module": token(type(exc).__module__), "frames": frames[-24:]}

    detail = describe(error)
    # Exact known local messages only; never output arbitrary exception arguments.
    if (type(error) is ValueError and len(error.args) == 1 and isinstance(error.args[0], str)
            and (hint := HINTS.get(error.args[0]))):
        detail["hint"] = hint
    causes, seen = [], {id(error)}
    cause = error.__cause__ or (None if error.__suppress_context__ else error.__context__)
    while cause is not None and id(cause) not in seen and len(causes) < 4:
        seen.add(id(cause))
        causes.append(describe(cause))
        cause = cause.__cause__ or (None if cause.__suppress_context__ else cause.__context__)
    detail["causes"] = causes
    return detail


class PrivateRotatingFile(RotatingFileHandler):
    def _open(self):
        fd = os.open(self.baseFilename, os.O_WRONLY | os.O_APPEND | os.O_CREAT |
                     getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.fchmod(fd, 0o600)
        return os.fdopen(fd, "a", encoding="utf-8")


class SafeFormatter(logging.Formatter):
    def format(self, record):
        # Never call getMessage/formatException: even third-party messages may
        # contain Authorization, HTTP query parameters or an entire model body.
        with _RECORD_LOCK:
            registered = _INTERNAL_RECORDS.get(id(record))
            data = registered[1] if registered is not None and registered[0] is record else None
        if data is None:
            data = {"event": "library.log_omitted", "source": token(record.name),
                    "frames": [{"file": token(Path(record.pathname).name),
                                "function": token(record.funcName), "line": record.lineno}]}
            if record.exc_info and record.exc_info[1]:
                data.update(exception_detail(record.exc_info[1]))
        return json.dumps({"time": datetime.now(UTC).isoformat(),
                           "level": record.levelname, **data}, ensure_ascii=True)


class QuietStream(logging.StreamHandler):
    def handleError(self, record):
        # A detached driver's parent may have exited. File logging continues;
        # logging failure must never alter native execution or print the record.
        pass


@contextmanager
def capture_output(log, run_id):
    """Driver-process only: keep real Python streams, drain local POSIX pipes.

    TextIOWrapper/fileno/buffer/reconfigure and fd-level or subprocess writes retain
    their interfaces. Neither the Web parent's lifetime nor a secret-redaction regex
    is involved: only byte counts leave these driver-local readers.
    """
    stopped = threading.Event()
    captures = []

    def drain(fd, name):
        try:
            while True:
                if select.select([fd], [], [], .2)[0]:
                    data = os.read(fd, 8192)
                    if not data:
                        break
                    log.emit("driver.output_omitted", level="WARNING", run_id=run_id,
                             phase="driver_output", stream=name, bytes=len(data))
                elif stopped.is_set():
                    break
        finally:
            os.close(fd)

    sys.stdout.flush()
    sys.stderr.flush()
    try:
        for number, name in ((1, "stdout"), (2, "stderr")):
            saved = os.dup(number)
            try:
                reader, writer = os.pipe()
                try:
                    os.dup2(writer, number)
                finally:
                    os.close(writer)
            except OSError:
                os.close(saved)
                raise
            thread = threading.Thread(target=drain, args=(reader, name), daemon=True)
            captures.append((number, saved, thread))
            thread.start()
        yield
    finally:
        # Flush while driver-local readers still exist, before restoring fds.
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.flush()
            except (OSError, ValueError):
                pass  # A library may have closed its own output stream.
        for number, saved, _ in captures:
            os.dup2(saved, number)
            os.close(saved)
        stopped.set()
        for _, _, thread in captures:
            thread.join(timeout=2)


class Diagnostics:
    def __init__(self, path, *, level="INFO", console=True, stream=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Per-app ownership avoids cross-data-root leaks and accumulating global
        # handlers in embedded apps/tests. Deliberately not in logging's registry.
        self.logger = logging.Logger("workbench.observation", level=level)  # noqa: LOG001
        self.logger.propagate = False
        file = PrivateRotatingFile(self.path, maxBytes=5_000_000, backupCount=4)
        self.logger.addHandler(file)
        if console:
            self.logger.addHandler(QuietStream(stream or sys.stderr))
        for handler in self.logger.handlers:
            handler.setFormatter(SafeFormatter())

    def emit(self, event, *, level="INFO", **fields):
        data = {"event": event, "pid": os.getpid()}
        if request_id.get():
            data["request_id"] = request_id.get()
        data.update({k: v for k, v in fields.items() if k in FIELDS and v is not None})
        number = getattr(logging, level)
        if not self.logger.isEnabledFor(number):
            return
        record = logging.LogRecord(self.logger.name, number, __file__, 0, "", (), None)
        with _RECORD_LOCK:
            _INTERNAL_RECORDS[id(record)] = (record, data)
        try:
            self.logger.handle(record)
        finally:
            with _RECORD_LOCK:
                del _INTERNAL_RECORDS[id(record)]

    def error(self, error, *, phase, run_id=None, code="OPERATION_FAILED"):
        error_id = "err-" + uuid4().hex
        self.emit("operation.failed", level="ERROR", error_id=error_id,
                  phase=phase, run_id=run_id, code=code, **exception_detail(error))
        return error_id

    def close(self):
        for handler in self.logger.handlers[:]:
            self.logger.removeHandler(handler)
            handler.close()


def configure_libraries(diagnostics):
    """CLI-owned root only. Third party messages are replaced, not regex-cleaned."""
    root = logging.getLogger()
    root.handlers[:] = diagnostics.logger.handlers
    root.setLevel(logging.WARNING)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True


def tail(path, limit=100):
    """Bounded JSONL read; no raw/provider artifacts and no directory traversal."""
    if not path.is_file():
        return []
    with path.open("rb") as handle:
        handle.seek(max(0, path.stat().st_size - 256_000))
        if handle.tell():
            handle.readline()
        rows = handle.read(256_000).splitlines()
    result = []
    for line in rows[-limit:]:
        try:
            result.append(json.loads(line))
        except (ValueError, UnicodeDecodeError):
            continue  # A concurrent writer may not have completed its last line.
    return result
