"""Workspace material reuse with original acquisition provenance, not evidence grading."""

import hashlib
import json

from .store import encode, now


class ResearchLibrary:
    def __init__(self, store):
        self.store = store

    def initialize(self):
        self.store.db.executescript("""
        CREATE TABLE IF NOT EXISTS library_materials (
          source_ref TEXT NOT NULL, requested_access TEXT NOT NULL,
          content_sha256 TEXT NOT NULL, origin_task_id TEXT NOT NULL REFERENCES tasks(id),
          result TEXT NOT NULL, acquired_at TEXT NOT NULL,
          PRIMARY KEY(source_ref, requested_access, content_sha256));
        CREATE TABLE IF NOT EXISTS library_aliases (
          source_ref TEXT NOT NULL, kind TEXT NOT NULL, value TEXT NOT NULL,
          PRIMARY KEY(source_ref,kind,value));
        """)

    def lookup(self, source_ref, access):
        rows = self.store.rows(
            "SELECT * FROM library_materials WHERE source_ref=? AND requested_access=? ORDER BY acquired_at DESC LIMIT 1",
            (source_ref, access),
        )
        if not rows:
            return None
        row = rows[0]
        result = json.loads(row["result"])
        if (
            hashlib.sha256((result["acquisition"].get("text") or "").encode()).hexdigest()
            != row["content_sha256"]
        ):
            raise ValueError("Library content hash mismatch")
        return {
            **result,
            "reuse": {
                "origin_task_id": row["origin_task_id"],
                "acquired_at": row["acquired_at"],
                "content_sha256": row["content_sha256"],
                "freshness": "saved snapshot; not newly fetched",
            },
        }

    def save(self, task_id, request, result):
        a = result.get("acquisition", {})
        if a.get("status") == "failed" or not a.get("source"):
            return
        content_hash = hashlib.sha256((a.get("text") or "").encode()).hexdigest()
        metadata = result.get("details", {}).get("metadata", {})
        with self.store.db:
            self.store.db.execute(
                "INSERT OR IGNORE INTO library_materials VALUES(?,?,?,?,?,?)",
                (
                    request["source_ref"],
                    request["desired_access"],
                    content_hash,
                    task_id,
                    encode(result),
                    a.get("acquired_at") or now(),
                ),
            )
            for key in ("doi", "pmid", "pmcid"):
                if metadata.get(key):
                    self.store.db.execute(
                        "INSERT OR IGNORE INTO library_aliases VALUES(?,?,?)",
                        (request["source_ref"], key, str(metadata[key])),
                    )
