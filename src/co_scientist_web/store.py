"""Separate Web catalog; never writes native scientific tables."""

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


def now():
    return datetime.now(UTC).isoformat()


def identifier(value):
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,159}", value):
        raise ValueError("invalid logical identifier")
    return value


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS objects (
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (
                    run_id TEXT PRIMARY KEY, pid INTEGER, state TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS job_diagnostics (
                    run_id TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)

    @contextmanager
    def db(self):
        with sqlite3.connect(self.root / "web.sqlite3", timeout=10) as db:
            db.row_factory = sqlite3.Row
            yield db

    def path(self, *parts):
        target = self.root.joinpath(*parts).resolve()
        if not target.is_relative_to(self.root):
            raise ValueError("path outside data root")
        return target

    def save(self, kind, value, key=None):
        key = identifier(key or f"{kind}-{uuid4().hex}")
        record = {**value, "id": key, "updated_at": now()}
        with self.db() as db:
            db.execute(
                "INSERT INTO objects VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET value=excluded.value",
                (key, kind, json.dumps(record, ensure_ascii=False)),
            )
        return record

    def get(self, kind, key):
        identifier(key)
        with self.db() as db:
            row = db.execute(
                "SELECT value FROM objects WHERE kind=? AND id=?", (kind, key)
            ).fetchone()
        if row is None:
            raise KeyError("unknown logical identifier")
        return json.loads(row[0])

    def list(self, kind):
        with self.db() as db:
            return [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT value FROM objects WHERE kind=? ORDER BY rowid DESC", (kind,)
                )
            ]

    def run_root(self, key):
        self.get("run", key)
        return self.path("runs", identifier(key))

    def job(self, key, *, pid=None, state=None, diagnostic=None):
        identifier(key)
        with self.db() as db:
            if state is not None:
                db.execute(
                    "INSERT INTO jobs VALUES (?,?,?) ON CONFLICT(run_id) DO UPDATE SET pid=excluded.pid,state=excluded.state",
                    (key, pid, state),
                )
            row = db.execute("SELECT * FROM jobs WHERE run_id=?", (key,)).fetchone()
            if diagnostic is not None:
                db.execute("INSERT INTO job_diagnostics VALUES (?,?) ON CONFLICT(run_id) "
                           "DO UPDATE SET value=excluded.value", (key, json.dumps(diagnostic)))
            detail = db.execute("SELECT value FROM job_diagnostics WHERE run_id=?", (key,)).fetchone()
        result = dict(row) if row else {"run_id": key, "pid": None, "state": "not_started"}
        result["diagnostic"] = json.loads(detail[0]) if detail else None
        return result

    def observed_exit(self, key, pid, diagnostic, *, expected_state=None):
        """An old reaper must not overwrite a newer explicitly resumed driver."""
        identifier(key)
        with self.db() as db:
            changed = db.execute(
                "UPDATE jobs SET state='interrupted_needs_review' WHERE run_id=? AND pid IS ? "
                "AND (? IS NULL OR state=?)",
                (key, pid, expected_state, expected_state),
            ).rowcount
            if changed:
                db.execute("INSERT INTO job_diagnostics VALUES (?,?) ON CONFLICT(run_id) "
                           "DO UPDATE SET value=excluded.value", (key, json.dumps(diagnostic)))
        return bool(changed)
