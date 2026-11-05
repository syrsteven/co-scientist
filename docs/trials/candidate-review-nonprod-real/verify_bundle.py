"""Offline audit of the exported P09 uncertain trial; never opens a DB or network."""

import hashlib
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent


def read(path):
    return json.loads((BASE / path).read_text())


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


def main():
    for line in (BASE / "SHA256SUMS").read_text().splitlines():
        expected, name = line.split("  ", 1)
        path = (BASE / name).resolve()
        assert path.is_relative_to(BASE)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, name
    summary = read("summary.json")
    frozen = read("prepared/package/trial.json")
    assert digest(frozen) == summary["preparation_sha256"]
    assert digest(read("candidate.json")) == frozen["candidate_sha256"]
    assert digest(read("goal-context.json")) == frozen["goal_sha256"]
    assert digest(read("source-views.json")) == frozen["source_views_sha256"]
    expected = read("prepared/package/P09.unsent-request.json")
    request = read("P09/request-record.json")
    attempt = read("P09/attempt-row.json")
    assert request["actual_request"] == expected["actual_request"]
    assert request["messages"] == expected["messages"]
    assert json.loads(attempt["request"]) == request
    assert read("P09/actual-input.json") == read("prepared/package/P09.actual-input.json")
    actual = request["actual_request"]
    body = actual["body"]
    assert body["model"] == "gpt-6.1-sol" and body["reasoning"] == {"effort": "high"}
    assert body["max_output_tokens"] == 32768
    assert body["text"]["format"] == {"type": "json_object"}
    assert body["background"] and body["store"] and body["truncation"] == "disabled"
    assert "temperature" not in body
    assert actual["timeout_seconds"] == actual["total_wait_seconds"] == 600
    assert len(json.dumps(actual, sort_keys=True, ensure_ascii=False).encode()) <= 262144
    assert attempt["status"] == "uncertain" and attempt["response"] is None
    assert json.loads(attempt["usage"]) == read("P09/usage.json")
    assert all(v is None for v in read("P09/usage.json").values())
    assert read("P09/raw-response.json") is None
    assert read("P09/provider-usage.json") is None
    assert read("P09/parsed-result.json") is None
    assert summary["P09"]["response_id"] is None
    assert summary["P09"]["post_attempts"] == 1 and summary["P09"]["query_attempts"] == 0
    assert not read("P10/not-executed.json")["task_created"]
    assert not summary["science_validated"]
    page = read("page/persistence.json")
    assert (
        page["all_attempts_unchanged"] and page["provider_requests_added_by_page_or_restart"] == 0
    )
    assert read("preservation.json")["original_database_unchanged"]
    print(
        "Verified hashes, frozen request, uncertain/unknown usage, P10 absent and preservation evidence"
    )


if __name__ == "__main__":
    main()
