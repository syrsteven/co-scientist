"""Explicit per-seed scheduling isolation; never resolves or retries an Attempt."""

import json


def task_seed(store, task_id):
    tables = {r["name"] for r in store.rows("SELECT name FROM sqlite_master WHERE type='table'")}
    if "background_actions" in tables:
        rows = store.rows("SELECT seed_id FROM background_actions WHERE task_id=?", (task_id,))
        if rows:
            return rows[0]["seed_id"]
    if "generation_actions" in tables:
        rows = store.rows("SELECT binding FROM generation_actions WHERE task_id=?", (task_id,))
        if rows:
            return json.loads(rows[0]["binding"]).get("seed_id")
    if "candidate_review_actions" in tables:
        rows = store.rows(
            "SELECT g.binding FROM candidate_review_actions a JOIN generation_actions g ON g.request_id=a.generation_ref WHERE a.task_id=?",
            (task_id,),
        )
        if rows:
            return json.loads(rows[0]["binding"]).get("seed_id")
    if "literature_actions" in tables:
        rows = store.rows("SELECT request FROM literature_actions WHERE task_id=?", (task_id,))
        if rows:
            return json.loads(rows[0]["request"]).get("background_context", {}).get("seed_id")
    return None


def isolated_task(store, run, task_id):
    # Only a persisted controller disposition allows independent siblings to proceed.
    if not store.rows("SELECT name FROM sqlite_master WHERE name='research_seed_holds'"):
        return False
    rows = store.rows(
        "SELECT seed_id FROM research_seed_holds WHERE run_id=? AND task_id=?", (run, task_id)
    )
    if not rows or task_seed(store, task_id) != rows[0]["seed_id"]:
        return False
    state = json.loads(store.one("SELECT state FROM research_runs WHERE run_id=?", (run,))["state"])
    active = state.get("seed_id")
    return bool(active and active != rows[0]["seed_id"])


def blocking_attempts(store, run, attempts):
    return [
        a
        for a in attempts
        if not isolated_task(
            store, run, store.one("SELECT task_id FROM attempts WHERE id=?", (a["id"],))["task_id"]
        )
    ]
