"""Recoverable project lifecycle and durable launch lookup; no provider actions."""

import json

from .store import now


def initialize(store):
    store.db.executescript("""
    CREATE TABLE IF NOT EXISTS project_lifecycle (
      project_id TEXT PRIMARY KEY REFERENCES projects(id), state TEXT NOT NULL,
      updated_at TEXT NOT NULL);
    """)


def projects(store):
    result = []
    for p in store.rows(
        "SELECT p.*,COALESCE(l.state,'active') AS lifecycle FROM projects p LEFT JOIN project_lifecycle l ON p.id=l.project_id ORDER BY p.created_at DESC"
    ):
        revisions = store.rows(
            "SELECT * FROM brief_revisions WHERE project_id=? ORDER BY created_at DESC", (p["id"],)
        )
        p["latest_revision"] = (
            {**revisions[0], "content": json.loads(revisions[0]["content"])} if revisions else None
        )
        p["runs"] = store.rows(
            "SELECT id,status,revision_id FROM runs WHERE project_id=? ORDER BY created_at DESC",
            (p["id"],),
        )
        result.append(p)
    return result


def change(store, project_id, action, name=None):
    store.one("SELECT id FROM projects WHERE id=?", (project_id,))
    if action not in ("rename", "archive", "trash", "restore"):
        raise ValueError("Unknown project action")
    with store.db:
        if action == "rename":
            if not isinstance(name, str) or not 0 < len(name.strip()) <= 300:
                raise ValueError("A bounded project name is required")
            store.db.execute("UPDATE projects SET name=? WHERE id=?", (name.strip(), project_id))
        else:
            if action in ("trash", "archive"):
                # Stop scheduling before hiding; restoration never resumes execution.
                store.db.execute(
                    "UPDATE research_runs SET status='stopped',reason='Project hidden by user; remote work is not cancelled',updated_at=? WHERE run_id IN (SELECT id FROM runs WHERE project_id=?) AND status IN ('running','paused')",
                    (now(), project_id),
                )
            store.db.execute(
                "INSERT INTO project_lifecycle VALUES(?,?,?) ON CONFLICT(project_id) DO UPDATE SET state=excluded.state,updated_at=excluded.updated_at",
                (
                    project_id,
                    {"archive": "archived", "trash": "trash", "restore": "active"}[action],
                    now(),
                ),
            )
    return {"project_id": project_id, "action": action}
