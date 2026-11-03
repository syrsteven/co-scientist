"""M14a/M15a: append-only inputs and transactional execution facts.

One active Store per database (POSIX lock), one process/thread at a time. Direct
SQL mutation is outside the supported API. No compatibility with G3 databases.
"""

import fcntl
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .contracts import JSON


def encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def now():
    return datetime.now(UTC).isoformat()


def identity():
    return uuid4().hex


class Store:
    def __init__(self, path: str | Path):
        path = Path(path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = open(str(path) + ".lock", "a")  # noqa: SIM115 -- Store owns lock lifetime
        try:
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._lock.close()
            raise RuntimeError("Database already has an active runtime") from None
        try:
            self.db = sqlite3.connect(path)
            self.db.row_factory = sqlite3.Row
            self.db.execute("PRAGMA foreign_keys=ON")
            self.db.execute("PRAGMA synchronous=FULL")
            app_id = self.db.execute("PRAGMA application_id").fetchone()[0]
            tables = self.db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if app_id != 0x43534E31 and (tables or app_id):
                raise ValueError("Not a Co-Scientist Next W0 database")
            self.db.execute("PRAGMA application_id=1129532977")
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS brief_revisions (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
                    previous_id TEXT REFERENCES brief_revisions(id),
                    content TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
                    revision_id TEXT NOT NULL REFERENCES brief_revisions(id),
                    policy_ref TEXT NOT NULL, goal_context_ref TEXT,
                    plan TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
                    step INTEGER NOT NULL, module TEXT NOT NULL, input TEXT NOT NULL,
                    status TEXT NOT NULL, error TEXT, UNIQUE(run_id, step)
                );
                CREATE TABLE IF NOT EXISTS results (
                    task_id TEXT PRIMARY KEY REFERENCES tasks(id), output TEXT NOT NULL,
                    applied_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS attempts (
                    id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id),
                    call_key TEXT NOT NULL, target TEXT NOT NULL, request TEXT NOT NULL,
                    ordinal INTEGER NOT NULL, previous_id TEXT REFERENCES attempts(id),
                    status TEXT NOT NULL, response TEXT, error TEXT,
                    usage TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT,
                    retry_authorization TEXT, UNIQUE(task_id, call_key, ordinal)
                );
                CREATE TABLE IF NOT EXISTS goal_contexts (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL UNIQUE REFERENCES runs(id),
                    revision_id TEXT NOT NULL REFERENCES brief_revisions(id),
                    content TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS goal_run_config (
                    run_id TEXT PRIMARY KEY REFERENCES runs(id), config TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS literature_actions (
                    request_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
                    task_id TEXT NOT NULL UNIQUE REFERENCES tasks(id),
                    request TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS material_views (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
                    acquisition_task_id TEXT NOT NULL REFERENCES tasks(id),
                    content TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS background_actions (
                    request_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
                    task_id TEXT NOT NULL UNIQUE REFERENCES tasks(id), operation TEXT NOT NULL,
                    seed_id TEXT, request TEXT NOT NULL, input TEXT NOT NULL,
                    config TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS execution_facts (
                    id INTEGER PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id),
                    kind TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL
                );
            """)
        except BaseException:
            if hasattr(self, "db"):
                self.db.close()
            self._lock.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        self.db.close()
        self._lock.close()

    def one(self, sql, params=()):
        row = self.db.execute(sql, params).fetchone()
        if row is None:
            raise KeyError("Record not found")
        return dict(row)

    def rows(self, sql, params=()):
        return [dict(row) for row in self.db.execute(sql, params)]

    def fact(self, task_id, kind, detail):
        self.db.execute(
            "INSERT INTO execution_facts(task_id,kind,detail,created_at) VALUES(?,?,?,?)",
            (task_id, kind, encode(detail), now()),
        )

    def create_project(self, name: str) -> str:
        project_id = identity()
        with self.db:
            self.db.execute("INSERT INTO projects VALUES(?,?,?)", (project_id, name, now()))
        return project_id

    def revise_brief(self, project_id: str, content: JSON, previous_id: str | None = None):
        # Explicit parent supports branches; there is no mutable "latest" Run input.
        if previous_id is not None:
            parent = self.one("SELECT * FROM brief_revisions WHERE id=?", (previous_id,))
            if parent["project_id"] != project_id:
                raise ValueError("Revision parent belongs to another Project")
        revision_id = identity()
        with self.db:
            self.db.execute(
                "INSERT INTO brief_revisions VALUES(?,?,?,?,?)",
                (revision_id, project_id, previous_id, encode(content), now()),
            )
        return revision_id

    def create_run(
        self,
        revision_id: str,
        modules: list[str],
        *,
        policy_ref: str,
        goal_context_ref: str | None = None,
        goal_config: JSON | None = None,
    ):
        if not modules or not all(isinstance(m, str) and m for m in modules):
            raise ValueError("A nonempty explicit module plan is required")
        if not policy_ref:
            raise ValueError("A fixed policy reference is required")
        revision = self.one("SELECT * FROM brief_revisions WHERE id=?", (revision_id,))
        run_id = identity()
        with self.db:
            self.db.execute(
                "INSERT INTO runs VALUES(?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    revision["project_id"],
                    revision_id,
                    policy_ref,
                    goal_context_ref,
                    encode(modules),
                    "ready",
                    now(),
                ),
            )
            if goal_config is not None:
                self.db.execute(
                    "INSERT INTO goal_run_config VALUES(?,?)", (run_id, encode(goal_config))
                )
            self._create_task(run_id, 0, None)
        return run_id

    def _create_task(self, run_id, step, previous_result):
        run = self.run(run_id)
        revision = self.one("SELECT * FROM brief_revisions WHERE id=?", (run["revision_id"],))
        task_id = identity()
        inputs = {
            "task_id": task_id,
            "run_id": run_id,
            "brief_revision_id": revision["id"],
            "brief": json.loads(revision["content"]),
            "policy_ref": run["policy_ref"],
            "goal_context_ref": run["goal_context_ref"],
            "previous_result": previous_result,
        }
        self.db.execute(
            "INSERT INTO tasks VALUES(?,?,?,?,?,?,?)",
            (
                task_id,
                run_id,
                step,
                json.loads(run["plan"])[step],
                encode(inputs),
                "ready",
                None,
            ),
        )

    def run(self, run_id):
        return self.one("SELECT * FROM runs WHERE id=?", (run_id,))

    def tasks(self, run_id):
        return self.rows("SELECT * FROM tasks WHERE run_id=? ORDER BY step", (run_id,))

    def submit_result(
        self, task_id: str, output: JSON, *, stop_status=None, goal_context=None
    ) -> bool:
        """Commit result, its application, successor and run state atomically."""
        payload = encode(output)
        with self.db:
            task = self.one("SELECT * FROM tasks WHERE id=?", (task_id,))
            old = self.rows("SELECT output FROM results WHERE task_id=?", (task_id,))
            if old:
                if old[0]["output"] != payload:
                    raise ValueError("Conflicting result for an already applied Task")
                return False
            if task["status"] != "running":
                raise ValueError("Only an executing Task can submit its first result")
            unresolved = self.rows(
                """SELECT a.id FROM attempts a WHERE a.task_id=?
                AND a.status IN ('in_flight','uncertain') AND NOT EXISTS (
                    SELECT 1 FROM attempts newer WHERE newer.task_id=a.task_id
                    AND newer.call_key=a.call_key AND newer.ordinal>a.ordinal)""",
                (task_id,),
            )
            if unresolved:
                from .contracts import UncertainCall

                raise UncertainCall("Cannot apply a result with unresolved external effects")
            self.db.execute("INSERT INTO results VALUES(?,?,?)", (task_id, payload, now()))
            self.db.execute("UPDATE tasks SET status='succeeded',error=NULL WHERE id=?", (task_id,))
            self.fact(task_id, "result_applied", {})
            run = self.run(task["run_id"])
            if goal_context is not None:
                goal_id = "goal-" + task_id
                self.db.execute(
                    "INSERT INTO goal_contexts VALUES(?,?,?,?,?)",
                    (
                        goal_id,
                        run["id"],
                        run["revision_id"],
                        encode(goal_context),
                        now(),
                    ),
                )
                self.db.execute(
                    "UPDATE runs SET goal_context_ref=? WHERE id=?", (goal_id, run["id"])
                )
            next_step = task["step"] + 1
            if stop_status is not None:
                status = stop_status
            elif next_step < len(json.loads(run["plan"])):
                self._create_task(run["id"], next_step, json.loads(payload))
                status = "ready"
            else:
                status = "completed"
            self.db.execute("UPDATE runs SET status=? WHERE id=?", (status, run["id"]))
        return True

    def retry_task(self, task_id: str, reason: str):
        if not reason.strip():
            raise ValueError("Recovery reason required")
        with self.db:
            task = self.one("SELECT * FROM tasks WHERE id=?", (task_id,))
            if task["status"] not in ("failed", "blocked"):
                raise ValueError("Only failed/blocked tasks can be retried")
            self.fact(task_id, "task_retry", {"reason": reason, "previous_error": task["error"]})
            self.db.execute("UPDATE tasks SET status='ready' WHERE id=?", (task_id,))
            self.db.execute("UPDATE runs SET status='ready' WHERE id=?", (task["run_id"],))

    def recover(self, run_id=None):
        """Call once after exclusively opening a database in a new runtime.

        Running modules may execute again: they must put external effects through
        Calls. No external request is repeated just because a process restarted.
        """
        with self.db:
            query = """SELECT * FROM tasks WHERE (status='running' OR id IN (
                SELECT task_id FROM attempts WHERE status='in_flight'))"""
            params = ()
            if run_id is not None:
                query += " AND run_id=?"
                params = (run_id,)
            for task in self.rows(query, params):
                inflight = self.rows(
                    "SELECT id FROM attempts WHERE task_id=? AND status='in_flight'", (task["id"],)
                )
                for attempt in inflight:
                    self.db.execute(
                        "UPDATE attempts SET status='uncertain',error=?,finished_at=? WHERE id=?",
                        (
                            encode(
                                {"type": "ProcessInterrupted", "message": "Response not persisted"}
                            ),
                            now(),
                            attempt["id"],
                        ),
                    )
                status = "blocked" if inflight else "ready"
                self.db.execute("UPDATE tasks SET status=? WHERE id=?", (status, task["id"]))
                self.db.execute("UPDATE runs SET status=? WHERE id=?", (status, task["run_id"]))
                self.fact(task["id"], "process_recovery", {"status": status})

    def authorize_uncertain_retry(self, attempt_id: str, reason: str):
        """Operator accepts duplicate-effect risk; does not assert prior failure."""
        if not reason.strip():
            raise ValueError("Explicit recovery reason required")
        with self.db:
            attempt = self.one("SELECT * FROM attempts WHERE id=?", (attempt_id,))
            latest = self.one(
                """SELECT id FROM attempts WHERE task_id=? AND call_key=?
                                 ORDER BY ordinal DESC LIMIT 1""",
                (attempt["task_id"], attempt["call_key"]),
            )
            if attempt["status"] != "uncertain" or latest["id"] != attempt_id:
                raise ValueError("Only the latest uncertain Attempt can be authorized")
            if attempt["retry_authorization"]:
                raise ValueError("Retry already authorized")
            self.db.execute(
                "UPDATE attempts SET retry_authorization=? WHERE id=?", (reason, attempt_id)
            )
            self.fact(
                attempt["task_id"],
                "uncertain_retry_authorized",
                {"attempt_id": attempt_id, "reason": reason},
            )

    def usage(self, *, run_id: str, task_id: str | None = None):
        """Partial totals retain an unknown count, never treat unknown as zero."""
        query = """SELECT a.usage FROM attempts a JOIN tasks t ON t.id=a.task_id
                   WHERE t.run_id=?"""
        params = [run_id]
        if task_id:
            query += " AND t.id=?"
            params.append(task_id)
        usages = [json.loads(row["usage"]) for row in self.rows(query, params)]
        return {
            key: {
                "known_total": (
                    sum(u[key] for u in usages if u[key] is not None)
                    if any(u[key] is not None for u in usages)
                    else None
                ),
                "unknown_attempts": sum(u[key] is None for u in usages),
            }
            for key in ("input_tokens", "output_tokens", "cost", "tool_units")
        }
