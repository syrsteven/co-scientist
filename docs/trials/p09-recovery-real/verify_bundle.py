"""Portable offline audit; no database access, credentials or provider requests."""

import base64
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def read(path):
    return json.loads((ROOT / path).read_text())


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


def main():
    for line in (ROOT / "SHA256SUMS").read_text().splitlines():
        expected, name = line.split("  ", 1)
        path = (ROOT / name).resolve()
        assert path.is_relative_to(ROOT)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, name
    before, after = read("original-attempt-before.json"), read("original-attempt-after.json")
    assert before["status"] == after["status"] == "uncertain"
    assert {k: v for k, v in before.items() if k != "retry_authorization"} == {
        k: v for k, v in after.items() if k != "retry_authorization"
    }
    assert after["retry_authorization"]
    frozen = read("prepared/package/trial.json")
    summary = read("summary.json")
    assert digest(frozen) == summary["preparation_sha256"]
    assert digest(read("candidate.json")) == frozen["candidate_sha256"]
    assert digest(read("source-views.json")) == frozen["source_views_sha256"]
    assert digest(read("goal-context.json")) == frozen["goal_sha256"]
    assert not summary["science_validated"]
    for stage in summary["stages"]:
        op = stage["operation"]
        attempts = [
            json.loads(p.read_text()) for p in sorted((ROOT / op / "attempts").glob("*.json"))
        ]
        submit = next(a for a in attempts if a["id"] == stage["submission_attempt_id"])
        if op == "P09":
            assert submit["previous_id"] == before["id"]
            assert submit["request"] == before["request"]
            assert submit["task_id"] == before["task_id"]
            assert len([a for a in attempts if a["call_key"] == "responses.submit"]) == 2
        else:
            assert len([a for a in attempts if a["call_key"] == "responses.submit"]) == 1
            payload = read("P10/input.json")
            assert payload["passed_candidate_ethics_record"] == read("P09/result.json")
            assert payload["actual_visible_source_views"] == read("source-views.json")
        assert digest(json.loads(submit["request"])) == stage["request_sha256"]
        actual = read(op + "/actual-request.json")
        body = actual["body"]
        assert body["model"] == "gpt-6.1-sol" and body["reasoning"] == {"effort": "high"}
        assert body["max_output_tokens"] == 32768 and "temperature" not in body
        assert body["background"] and body["store"] and body["truncation"] == "disabled"
        assert actual["timeout_seconds"] == actual["total_wait_seconds"] == 600
        assert len(json.dumps(actual, sort_keys=True, ensure_ascii=False).encode()) <= 262144
        final = read(op + "/raw-final-response.json")
        raw = base64.b64decode(final["body_base64"])
        assert hashlib.sha256(raw).hexdigest() == final["body_sha256"]
        assert raw.decode() == final["raw_response"]
        provider = json.loads(final["raw_response"])
        assert provider["status"] == "completed" and provider["id"] == stage["response_id"]
        assert provider["usage"] == stage["usage_once_per_response_id"]
        assert stage["finish_reason_reported"] == ("finish_reason" in provider)
        assert stage["cost"] is None and stage["queries"] <= 60
        assert all(v >= 15 for v in stage["original_query_intervals_seconds"])
        assert read(op + "/result.json")["review_status"] == "completed"
    assert read("P09/artifact.json")["decision_per_approved_policy"] == "pass"
    assert read("P10/artifact.json")["disposition"] == "proceed_to_R1"
    assert read("page/persistence.json")["all_logical_rows_before_after_identical"]
    assert read("preservation.json")["canonical_unchanged"]
    print(
        "Verified frozen identical retry, lineage, real P09/P10 binding, raw responses, usage and preservation"
    )


if __name__ == "__main__":
    main()
