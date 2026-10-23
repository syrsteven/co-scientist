"""Bounded incremental committed-event reads; no snapshots/artifact scans."""

import json
import sqlite3

from co_scientist.release.service import load


def event_page(root, after=0, limit=1000):
    path = root / "runtime/co-scientist.db"
    if not path.exists():
        return []
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=0.2) as db:
        return [{"sequence": s, "event_type": t, "payload": json.loads(p), "occurred_at": d}
                for s, t, p, d in db.execute(
                    "SELECT sequence,event_type,payload_json,occurred_at FROM events "
                    "WHERE sequence>? ORDER BY sequence LIMIT ?", (after, limit))]


def monitor_page(root, run_id, after):
    events = event_page(root, after)
    manifest = load(root / "manifest.json") if after == 0 else None
    return {"run_id": run_id, "events": events,
            "source_sequence": events[-1]["sequence"] if events else after,
            "has_more": len(events) == 1000,
            "manifest": {"goal": manifest["goal"],
                         "effective_execution_config": manifest["effective_execution_config"]}
            if manifest else None}
