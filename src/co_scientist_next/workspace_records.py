"""Local human annotations and read-only export; never consumed by scientific modules."""

import hashlib
import json

from .store import encode, identity, now


def digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


class WorkspaceRecords:
    def __init__(self, store):
        self.store = store

    def target(self, run_id, kind, ref):
        s = self.store
        run = s.run(run_id)
        if kind == "run" and ref == run_id:
            brief = json.loads(
                s.one("SELECT content FROM brief_revisions WHERE id=?", (run["revision_id"],))[
                    "content"
                ]
            )
            goal = s.rows("SELECT content FROM goal_contexts WHERE run_id=?", (run_id,))
            return {
                "revision_id": run["revision_id"],
                "brief": brief,
                "goal": json.loads(goal[0]["content"]) if goal else None,
            }
        if kind == "material_view":
            rows = s.rows(
                "SELECT content FROM material_views WHERE id=? AND run_id=?", (ref, run_id)
            )
            if rows:
                return json.loads(rows[0]["content"])
        if kind == "candidate":
            rows = s.rows(
                "SELECT r.output FROM generation_actions a JOIN results r ON r.task_id=a.task_id WHERE a.run_id=? AND a.candidate_id=?",
                (run_id, ref),
            )
            if rows and json.loads(rows[0]["output"]).get("candidate"):
                return json.loads(rows[0]["output"])["candidate"]
        raise ValueError("Annotation target must be saved content in this Run")

    def targets(self, run_id):
        refs = [("run", run_id, "研究整体 / 检索覆盖")]
        refs += [
            ("material_view", r["id"], json.loads(r["content"])["source_ref"])
            for r in self.store.rows("SELECT * FROM material_views WHERE run_id=?", (run_id,))
        ]
        refs += [
            (
                "candidate",
                r["candidate_id"],
                json.loads(r["output"])["candidate"]["title"]
                + " · "
                + json.loads(r["request"])["mode"],
            )
            for r in self.store.rows(
                "SELECT a.candidate_id,a.request,r.output FROM generation_actions a JOIN results r ON r.task_id=a.task_id WHERE a.run_id=?",
                (run_id,),
            )
            if json.loads(r["output"]).get("candidate")
        ]
        return [
            {"kind": k, "ref": ref, "label": label, "sha256": digest(self.target(run_id, k, ref))}
            for k, ref, label in refs
        ]

    def list(self, run_id):
        self.store.run(run_id)
        if not self.store.rows("SELECT name FROM sqlite_master WHERE name='human_annotations'"):
            return []
        return [
            {**r, "observations": json.loads(r["observations"])}
            for r in self.store.rows(
                "SELECT * FROM human_annotations WHERE run_id=? ORDER BY created_at,id", (run_id,)
            )
        ]

    def save(self, run_id, data):
        value = self.target(run_id, data["target_kind"], data["target_ref"])
        content_hash = digest(value)
        if data.get("target_sha256") != content_hash:
            raise ValueError("Content version changed; select the saved target again")
        if data.get("category") not in ("retrieval", "reading", "generation", "note"):
            raise ValueError("Explicit human assessment category required")
        observations, note = data.get("observations", {}), data.get("note", "")
        if (
            not isinstance(observations, dict)
            or len(observations) > 12
            or any(
                not isinstance(k, str) or not isinstance(v, str) for k, v in observations.items()
            )
            or not isinstance(note, str)
            or len(encode(data).encode()) > 30_000
            or not (note.strip() or any(v.strip() for v in observations.values()))
        ):
            raise ValueError("A bounded text note or assessment is required")
        row = {
            "id": identity(),
            "run_id": run_id,
            "target_kind": data["target_kind"],
            "target_ref": data["target_ref"],
            "target_sha256": content_hash,
            "category": data["category"],
            "observations": encode(observations),
            "note": note,
            "created_at": now(),
        }
        with self.store.db:
            self.store.db.execute(
                "INSERT INTO human_annotations VALUES(?,?,?,?,?,?,?,?,?)", tuple(row.values())
            )
        return {**row, "observations": observations}

    def export(self, run_id):
        s = self.store
        run = s.run(run_id)
        task_ids = [t["id"] for t in s.tasks(run_id)]
        tables = {r["name"] for r in s.rows("SELECT name FROM sqlite_master WHERE type='table'")}
        result = {
            "format": "co-scientist-stage-export-v1",
            "scope": "one saved Run; human annotations are separate and never automatically sent to models",
            "science_validated": False,
            "run": run,
            "project": s.one("SELECT * FROM projects WHERE id=?", (run["project_id"],)),
            "brief_revisions": s.rows(
                "SELECT * FROM brief_revisions WHERE project_id=?", (run["project_id"],)
            ),
            "tasks": s.tasks(run_id),
            "human_annotations": self.list(run_id),
        }
        for table in (
            "goal_contexts",
            "goal_run_config",
            "literature_actions",
            "material_views",
            "background_actions",
            "generation_actions",
            "candidate_review_actions",
            "generation_migrations",
            "research_runs",
            "research_events",
        ):
            result[table] = (
                s.rows("SELECT * FROM " + table + " WHERE run_id=?", (run_id,))
                if table in tables
                else []
            )
        for table in ("results", "attempts", "execution_facts", "remote_generations"):
            result[table] = (
                s.rows(
                    "SELECT * FROM "
                    + table
                    + " WHERE task_id IN (SELECT id FROM tasks WHERE run_id=?)",
                    (run_id,),
                )
                if table in tables and task_ids
                else []
            )
        return result
