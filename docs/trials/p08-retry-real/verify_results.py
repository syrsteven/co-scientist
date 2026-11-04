"""Portable read-only audit of an explicit, unsuccessful, same-task retry."""

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def read(name):
    return json.loads((HERE / name).read_text())


def main():
    for line in (HERE / "SHA256SUMS").read_text().splitlines():
        sha, name = line.split("  ", 1)
        path = (HERE / name).resolve()
        assert path.is_relative_to(HERE) and not path.is_symlink()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == sha
    rows = read("direct.attempts.json")
    assert len(rows) == 2 and [r["status"] for r in rows] == ["uncertain", "uncertain"]
    original = read("before.json")["attempt"]
    for k in ["request", "response", "error", "usage"]:
        original[k] = json.loads(original[k]) if original[k] else None
    assert {k: v for k, v in original.items() if k != "retry_authorization"} == {
        k: v for k, v in rows[0].items() if k != "retry_authorization"
    }
    assert rows[0]["retry_authorization"] == read("retry-authorization.json")["reason"]
    assert rows[1]["id"] == "86948ac23ee2477cac992b24f6016796"
    assert rows[1]["previous_id"] == rows[0]["id"] == "5ad8cea64b1146c7bf2eb80e194e0798"
    assert rows[1]["ordinal"] == 2 and rows[1]["retry_authorization"] is None
    assert rows[1]["task_id"] == rows[0]["task_id"] == "c1119e1ab4ed431daca848c01811fc37"
    assert rows[1]["call_key"] == rows[0]["call_key"] == "model"
    assert rows[1]["request"] == rows[0]["request"]
    for row in rows:
        assert row["response"] is None and all(v is None for v in row["usage"].values())
        assert row["error"]["diagnostic"] == {
            "category": "http_protocol",
            "phase": "request_open",
            "code": "REMOTE_DISCONNECTED",
        }
    payload = read("direct.input.json")
    request = rows[-1]["request"]
    assert json.loads(request["messages"][-1]["content"]) == payload
    assert request["messages"] == read("direct.messages.json")
    assert request["actual_request"] == read("direct.planned-http.json")
    assert request["prompt_version"] == "w1-p08-single-v1"
    config = read("model-config.json")
    assert config["timeout_seconds"] == 600 and config["max_request_bytes"] == 262144
    assert config["parameters"] == {
        "reasoning_effort": "high",
        "max_completion_tokens": 32768,
        "response_format": {"type": "json_object"},
    }
    second = read("assumption_structured.input.json")
    assert {k: v for k, v in payload.items() if k not in ["mode", "candidate_id_from_caller"]} == {
        k: v for k, v in second.items() if k not in ["mode", "candidate_id_from_caller"]
    }
    assert read("assumption_structured.not-executed.json")["new_attempts"] == 0
    audit = read("runtime-audit.json")
    assert (
        audit["new_model_attempts"] == 1
        and audit["candidate_count"] == 0
        and not audit["assumption_task_created"]
    )
    assert read("direct.action.json")["result"] is None
    assert read("direct.outcome.json")["monotonic_execution_seconds"] > 0
    assert read("direct.usage.json") is None
    assert not read("codex-review.json")["candidate_review_possible"]
    for name in [
        "direct.original-response.json",
        "direct.candidate.json",
        "assumption_structured.attempts.json",
    ]:
        assert not (HERE / name).exists()
    print(
        "Verified one explicit previous_id retry,same frozen request/config/task,original uncertainty/error/usage preserved,no response/candidate/second task,all available hashes. Science not validated."
    )


if __name__ == "__main__":
    main()
