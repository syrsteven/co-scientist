"""Read-only Goal diagnostics. Never sends, applies a result or changes a Run."""

import hashlib
import json

from .goal import PREPARE, PREPARE_PROMPT_V3, PREPARE_V3, SYSTEM, parse_prepare
from .store import encode


def inspect_goal(store, run_id):
    tasks = store.rows(
        "SELECT * FROM tasks WHERE run_id=? AND module IN ('goal.prepare.v1','goal.screen.v1') ORDER BY step",
        (run_id,),
    )
    if not tasks:
        return None
    task = tasks[-1]
    rows = store.rows("SELECT output FROM results WHERE task_id=?", (task["id"],))
    result = json.loads(rows[0]["output"]) if rows else {}
    attempts = store.rows("SELECT * FROM attempts WHERE task_id=? ORDER BY ordinal", (task["id"],))
    attempt = attempts[-1] if attempts else None
    status = result.get("execution_status", task["status"])
    if result.get("ethics", {}).get("completed") and result["ethics"].get("decision") == "reject":
        status = "rejected"
    elif attempt and attempt["status"] == "uncertain":
        status = "uncertain"
    stage = "preparation" if task["module"] == PREPARE else "screening"
    invalid = status == "invalid_output"
    title = (
        f"Research {stage} unsuccessful" if invalid else f"Goal {stage}: {status.replace('_', ' ')}"
    )
    response = (json.loads(attempt["response"]) or {}) if attempt and attempt["response"] else {}
    return {
        "stage": stage,
        "status": status,
        "title": title,
        "message": f"The {stage} response could not be validated."
        if invalid
        else "See the saved execution state; no automatic retry is authorized.",
        "literature_started": bool(
            store.rows("SELECT task_id FROM literature_actions WHERE run_id=?", (run_id,))
        ),
        "reason": result.get("parse_error", result.get("reason")),
        "next_step": f"Review the saved {stage} response in diagnostics. A corrected screening format can be checked offline; no automatic new request is authorized."
        if invalid
        else "Resolve the saved issue before any further execution.",
        "task_id": task["id"],
        "attempt_id": attempt["id"] if attempt else None,
        "attempt_status": attempt["status"] if attempt else None,
        "finish_reason": response.get("finish_reason"),
        "http_status": response.get("http_status"),
        "provider_usage": response.get("provider_usage"),
        "recovery_action": None,
        "restart_eligible": stage == "preparation" and invalid and json.loads(store.one("SELECT config FROM goal_run_config WHERE run_id=?", (run_id,))["config"]).get("prompt_version") in ("w0-t4-goal-v1", "v6-goal-focus-v2"),
    }


def preparation_proposal(store, run_id):
    """Export only: semantics changed, so this is NOT a retry of the old request."""
    task = store.one("SELECT * FROM tasks WHERE run_id=? AND module=?", (run_id, PREPARE))
    attempt = store.one(
        "SELECT * FROM attempts WHERE task_id=? ORDER BY ordinal DESC LIMIT 1", (task["id"],)
    )
    result = json.loads(store.one("SELECT output FROM results WHERE task_id=?", (task["id"],))["output"])
    if attempt["status"] != "succeeded" or result.get("execution_status") != "invalid_output":
        raise ValueError("Proposal requires a saved successful response and invalid preparation result")
    request = json.loads(attempt["request"])
    payload = json.loads(request["messages"][-1]["content"])
    response = json.loads(attempt["response"])
    raw = json.loads(response["raw_response"])["choices"][0]["message"]["content"]
    value = json.loads(raw)
    errors = []
    try:
        parse_prepare(raw, payload)
    except (ValueError, TypeError, KeyError) as exc:
        errors.append(str(exc))
    # Normalizing JSONPath syntax alone is insufficient if field classification changed.
    extra = [
        item
        for item in value.get("hard_requirements", [])
        if not item.get("input_locator", "").removeprefix("$.").startswith("explicit_constraints[")
    ]
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "developer", "content": PREPARE_PROMPT_V3},
        {"role": "user", "content": encode(payload)},
    ]
    actual = json.loads(encode(request["actual_request"]))
    actual["body"]["messages"] = messages
    return {
        "format": "goal-recovery-proposal-v1",
        "executable": False,
        "reason": "Semantic reclassification requires a new authorized call; no discarded extra requirements or inferred completion.",
        "run_id": run_id,
        "source_task_id": task["id"],
        "source_attempt_id": attempt["id"],
        "source_response_sha256": hashlib.sha256(response["raw_response"].encode()).hexdigest(),
        "source_request_sha256": hashlib.sha256(attempt["request"].encode()).hexdigest(),
        "original_parse_errors": errors,
        "additional_requirement_count": len(extra),
        "prompt_version": PREPARE_V3,
        "messages": messages,
        "model_config": request["model_config"],
        "actual_request": actual,
        "execution_authorized": False,
        "science_validated": False,
    }
