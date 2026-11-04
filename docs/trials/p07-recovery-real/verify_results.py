"""Portable recovery audit; no model, network, credential discovery or DB writes."""

import base64
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASK = "55bc66f3e1a44070babcf67db99b0bac"
OLD = "0d9e7d5fd9da4bbea3ddc42608e0c184"


def read(name):
    return json.loads((HERE / name).read_text())


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()


def main():
    for line in (HERE / "SHA256SUMS").read_text().splitlines():
        sha, name = line.split("  ", 1)
        path = (HERE / name).resolve()
        assert path.is_relative_to(HERE) and not path.is_symlink()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == sha, name
    before = read("before.json")
    after = read("attempts-after.json")
    assert len(after) == 2 and before["attempt"]["id"] == OLD
    original = dict(before["attempt"])
    for key in ["request", "response", "error", "usage"]:
        original[key] = json.loads(original[key]) if original[key] else None
    assert {k: v for k, v in after[0].items() if k != "retry_authorization"} == {
        k: v for k, v in original.items() if k != "retry_authorization"
    }
    assert after[0]["status"] == "uncertain" and after[0]["response"] is None
    assert all(v is None for v in after[0]["usage"].values())
    assert after[0]["retry_authorization"] == read("retry-authorization.json")["reason"]
    assert after[1]["previous_id"] == OLD and after[1]["ordinal"] == 2
    assert after[1]["task_id"] == after[0]["task_id"] == TASK
    assert after[1]["call_key"] == after[0]["call_key"] == "model"
    assert after[1]["target"] == after[0]["target"]
    assert after[1]["request"] == after[0]["request"] == read("frozen-call-request.json")
    assert after[1]["retry_authorization"] is None
    before_action = before["action"]
    action = read("action-after.json")
    for key in [
        "request_id",
        "run_id",
        "task_id",
        "operation",
        "seed_id",
        "created_at",
        "prompt_version",
    ]:
        assert action[key] == before_action[key]
    for key in ["request", "input", "config"]:
        assert action[key] == json.loads(before_action[key])
    frozen = read("frozen-call-request.json")
    wire = read("frozen-http-request.json")
    config = read("model-config.json")
    assert wire == frozen["actual_request"]
    assert json.loads(frozen["messages"][-1]["content"]) == action["input"]
    assert wire["body"] == {
        "model": "gpt-6.1-sol",
        "messages": frozen["messages"],
        "reasoning_effort": "high",
        "max_completion_tokens": 32768,
        "response_format": {"type": "json_object"},
        "n": 1,
        "stream": False,
        "store": False,
    }
    assert wire["timeout_seconds"] == config["timeout_seconds"] == 600
    assert len(canonical(wire)) == 148027 <= config["max_request_bytes"] == 262144
    consistency = read("request-consistency-before-send.json")
    assert (
        consistency["old_http_sha256"]
        == consistency["new_http_sha256"]
        == hashlib.sha256(canonical(wire)).hexdigest()
    )
    assert after[1]["status"] == "succeeded" and action["task_status"] == "succeeded"
    response = after[1]["response"]
    raw = (HERE / "original-response.json").read_bytes()
    assert raw == base64.b64decode(response["body_base64"])
    assert hashlib.sha256(raw).hexdigest() == response["body_sha256"]
    original_response = json.loads(raw)
    assert original_response["choices"][0]["finish_reason"] == response["finish_reason"] == "stop"
    assert (
        original_response["choices"][0]["message"]["content"]
        == (HERE / "model-content.txt").read_text()
    )
    assert original_response["usage"] == response["provider_usage"] == read("usage.json")
    result = read("parsed-result.json")
    assert (
        result == action["result"]
        and result["background_status"] == "saved"
        and result["science_validated"] is False
    )
    assert result["artifact"]["decision"] == "ready"
    allowed = set(action["input"]["available_record_refs"])
    review = read("readiness-evidence-and-review.json")
    assert len(review["rows"]) == len(result["artifact"]["checks"]) == 6
    for check, reviewed in zip(result["artifact"]["checks"], review["rows"]):
        assert check["criterion"] == reviewed["criterion"]
        assert set(check["record_refs"]) <= allowed
        assert [e["record_ref"] for e in reviewed["resolved_evidence"]] == check["record_refs"]
        assert reviewed["model_why"] == check["why"]
    facts_before, facts_after = read("facts-before.json"), read("facts-after.json")
    assert all(f in facts_after for f in facts_before)
    assert sum(f["kind"] == "uncertain_retry_authorized" for f in facts_after) == 1
    assert sum(f["kind"] == "task_retry" for f in facts_after) == 1
    outcome = read("outcome.json")
    assert outcome["new_attempt_count"] == 1 and outcome["old_error_unchanged"]
    assert outcome["no_new_run_task_search_fetch_view"] == {
        "runs": 1,
        "tasks": 23,
        "background_actions": 11,
        "literature_actions": 10,
        "material_views": 5,
    }
    assert outcome["run_status"] == "awaiting_generation" and outcome["science_validated"] is False
    assert read("unassociated-response-inspection.json")["complete_response_candidates"] == []
    print(
        "Verified SHA256,unchanged original uncertain error/usage,one authorized previous_id retry,same task/key/frozen request,full response/usage,6resolved readiness criteria,and no new Run/Task/search/view. Science not validated."
    )


if __name__ == "__main__":
    main()
