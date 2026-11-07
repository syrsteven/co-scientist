"""One explicitly confirmed v3 successor per failed legacy Goal Run. Never sends."""

import json

from .background import digest
from .goal import PREPARE, PREPARE_V3
from .policy_catalog import choices, resolve
from .research_config import DEFAULT_VERSION, DEFAULTS
from .store import encode, now


def initialize(store):
    store.db.execute("""CREATE TABLE IF NOT EXISTS goal_restarts (
      source_run_id TEXT PRIMARY KEY REFERENCES runs(id),
      successor_run_id TEXT UNIQUE NOT NULL REFERENCES runs(id),
      preview_hash TEXT NOT NULL, preview TEXT NOT NULL,
      confirmation TEXT NOT NULL, created_at TEXT NOT NULL)""")
    store.db.commit()


def preview(controller, source):
    s = controller.store
    old = s.rows("SELECT * FROM goal_restarts WHERE source_run_id=?", (source,))
    if old:
        return {
            **json.loads(old[0]["preview"]),
            "preview_hash": old[0]["preview_hash"],
            "successor_run_id": old[0]["successor_run_id"],
        }
    if s.rows("SELECT source_run_id FROM goal_restarts WHERE successor_run_id=?", (source,)):
        raise ValueError("A successor cannot automatically restart again; review its saved failure")
    run = s.run(source)
    state = controller.row(source)
    task = s.one("SELECT * FROM tasks WHERE run_id=? AND module=?", (source, PREPARE))
    result = json.loads(
        s.one("SELECT output FROM results WHERE task_id=?", (task["id"],))["output"]
    )
    attempt = s.one(
        "SELECT * FROM attempts WHERE task_id=? ORDER BY ordinal DESC LIMIT 1", (task["id"],)
    )
    config = controller.goal.config(source)
    if (
        state["status"] != "blocked"
        or result.get("execution_status") != "invalid_output"
        or attempt["status"] != "succeeded"
        or config["prompt_version"] not in ("w0-t4-goal-v1", "v6-goal-focus-v2")
    ):
        raise ValueError(
            "Restart requires a saved invalid legacy preparation response, not uncertain sending or screening rejection"
        )
    selection = choices(controller.goal.development_test)[0]
    body = {
        "source_run_id": source,
        "source_task_id": task["id"],
        "source_attempt_id": attempt["id"],
        "source_response_hash": digest(attempt["response"]),
        "revision_id": run["revision_id"],
        "brief_hash": digest(
            json.loads(
                s.one("SELECT content FROM brief_revisions WHERE id=?", (run["revision_id"],))[
                    "content"
                ]
            )
        ),
        "old_prompt_version": config["prompt_version"],
        "new_prompt_version": PREPARE_V3,
        "old_config": state["config"],
        "new_config": dict(DEFAULTS),
        "defaults_version": DEFAULT_VERSION,
        "configuration_changes": {
            k: {"before": state["config"].get(k), "after": v}
            for k, v in DEFAULTS.items()
            if state["config"].get(k) != v
        },
        "profiles": controller.profiles(),
        "policy_selection": selection,
        "policies": resolve(selection, controller.goal.development_test),
        "authorization_scope": "One successor Run: Goal, bounded literature, seeds, P08, Candidate Ethics and pass-only R0. No R1. Nonproduction policies. Costs unknown; no dollar guarantee.",
    }
    return {**body, "preview_hash": digest(body), "successor_run_id": None}


def confirm(controller, source, preview_hash, authorized):
    if authorized is not True:
        raise ValueError("Explicit bounded successor execution authorization required")
    s = controller.store
    # Outer transaction includes unique source reservation, new Run, Task and Start.
    with s.db:
        s.db.execute("BEGIN IMMEDIATE")
        p = preview(controller, source)
        if p["preview_hash"] != preview_hash:
            raise ValueError(
                "Restart preview changed; review the current configuration before confirming"
            )
        if p["successor_run_id"]:
            return p["successor_run_id"]
        run = controller.start(
            p["revision_id"],
            "goal-v3-restart-" + source,
            p["new_config"],
            p["policies"],
            policy_selection=p["policy_selection"],
            defaults_version=p["defaults_version"],
            commit=False,
        )
        s.db.execute(
            "INSERT INTO goal_restarts VALUES(?,?,?,?,?,?)",
            (
                source,
                run,
                p["preview_hash"],
                encode(p),
                encode(
                    {
                        "authorized": True,
                        "scope": p["authorization_scope"],
                        "new_execution_not_old_retry": True,
                    }
                ),
                now(),
            ),
        )
        controller.event(
            run,
            None,
            "goal_restart_authorized",
            {
                "source_run_id": source,
                "source_task_id": p["source_task_id"],
                "source_attempt_id": p["source_attempt_id"],
                "prompt_version": PREPARE_V3,
                "preview_hash": p["preview_hash"],
            },
        )
    return run
