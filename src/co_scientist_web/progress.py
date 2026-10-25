"""Read committed native events without altering scheduling or scientific state."""

import sqlite3
import threading

from co_scientist.domain.execution_config import ROLE_SCHEMAS
from co_scientist.events.contracts import EVENT_SCHEMA_VERSIONS

from .diagnostics import token

IMPORTANT = {"TaskEnqueued", "TaskStarted", "TaskSucceeded", "TaskFailed",
             "TaskCompleted", "RunStarted", "RunCompleted", "RunStopping", "RunFailed",
             "TaskLeaseClaimed", "TaskLeaseAdopted", "TaskOutputRetryRequested",
             "TaskRetryBudgetExhausted", "TaskRequeued", "ExternalCallAttemptFailed",
             "BudgetReserved", "BudgetSettled", "RunResumed"}


class Progress:
    def __init__(self, root, run_id, log):
        self.root, self.run_id, self.log = root, run_id, log
        self.cursor = 0
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self.loop, daemon=True)
        self.read_error_reported = False

    def poll(self):
        path = self.root / "runtime/co-scientist.db"
        if not path.is_file():
            return False
        # Fixed scalar metadata only, never load/serialize full scientific payloads.
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=.2) as db:
            rows = db.execute("SELECT sequence,event_type,"
                              "json_extract(payload_json,'$.task_id'),"
                              "json_extract(payload_json,'$.payload.output_schema_id') "
                              "FROM events WHERE sequence>? "
                              "ORDER BY sequence LIMIT 1000", (self.cursor,)).fetchall()
        for sequence, event, task_id, schema in rows:
            self.cursor = sequence
            if event not in EVENT_SCHEMA_VERSIONS and event not in IMPORTANT:
                continue
            level = "INFO" if (event in IMPORTANT or event.endswith(("V1", "V2")) or
                               event in {"MatchEvaluated", "BayesianRatingProjected"}) else "DEBUG"
            self.log.emit("native.event", level=level, run_id=self.run_id,
                          phase=ROLE_SCHEMAS.get(schema, "native_progress"),
                          sequence=sequence, event_type=token(event),
                          task_id=token(task_id) if isinstance(task_id, str) else None)
        return len(rows) == 1000

    def drain(self):
        try:
            while self.poll():
                pass
        except (sqlite3.Error, OSError) as error:
            if not self.read_error_reported:
                self.log.error(error, phase="progress_read", run_id=self.run_id,
                               code="PROGRESS_READ_UNAVAILABLE")
                self.read_error_reported = True

    def loop(self):
        while not self.stopped.is_set():
            self.drain()
            self.stopped.wait(.5)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stopped.set()
        self.thread.join(timeout=2)
        self.drain()
