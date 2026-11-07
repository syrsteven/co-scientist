"""Dedicated short annotation transactions; never reserves scientific calls."""

import json
import sqlite3
from pathlib import Path

from .store import Store
from .workspace_records import WorkspaceRecords, digest


def save_annotation(path, data):
    # Borrow Store's read helpers, without acquiring its runtime/scheduler lock.
    store = Store.__new__(Store)
    store.db = sqlite3.connect(Path(path).resolve(), timeout=3)
    store.db.row_factory = sqlite3.Row
    store.db.execute("PRAGMA foreign_keys=ON")
    try:
        with store.db:
            store.db.execute("BEGIN IMMEDIATE")
            key = data.get("submission_id")
            if not isinstance(key, str) or not 8 <= len(key) <= 120:
                raise ValueError("Stable annotation submission identity required")
            fingerprint = digest({k: v for k, v in data.items() if k != "submission_id"})
            old = store.rows("SELECT * FROM annotation_submissions WHERE id=?", (key,))
            if old:
                if old[0]["input_hash"] != fingerprint:
                    raise ValueError("Submission identity reused with different content")
                row = store.one(
                    "SELECT * FROM human_annotations WHERE id=?", (old[0]["annotation_id"],)
                )
                row["observations"] = json.loads(row["observations"])
                return row
            result = WorkspaceRecords(store).save(data["run_id"], data, commit=False)
            store.db.execute(
                "INSERT INTO annotation_submissions VALUES(?,?,?)", (key, fingerprint, result["id"])
            )
            return result
    finally:
        store.db.close()
