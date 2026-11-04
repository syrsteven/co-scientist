"""Portable read-only audit of one uncertain P08 and a deliberately unexecuted mode."""

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


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
    config = read("model-config.json")
    assert config["model"] == "gpt-6.1-sol" and config["timeout_seconds"] == 600
    assert config["max_request_bytes"] == 262144
    assert config["parameters"] == {
        "reasoning_effort": "high",
        "max_completion_tokens": 32768,
        "response_format": {"type": "json_object"},
    }
    fields = {
        "goal_context",
        "seed_brief",
        "readiness_record",
        "actual_frozen_seed_background_packet",
        "mode",
        "candidate_id_from_caller",
    }
    scientific = []
    for name, mode in [("direct", "DIRECT"), ("assumption_structured", "ASSUMPTION_STRUCTURED")]:
        payload, messages, wire = [
            read(name + suffix)
            for suffix in [".input.json", ".messages.json", ".planned-http.json"]
        ]
        assert set(payload) == fields and payload["mode"] == mode
        assert json.loads(messages[-1]["content"]) == payload
        assert wire["body"] == {
            "model": config["model"],
            "messages": messages,
            **config["parameters"],
            "n": 1,
            "stream": False,
            "store": False,
        }
        assert wire["timeout_seconds"] == 600
        assert len(canonical(wire)) <= config["max_request_bytes"]
        scientific.append(
            {k: v for k, v in payload.items() if k not in ["mode", "candidate_id_from_caller"]}
        )
        assert payload["readiness_record"]["decision"] == "ready"
    assert scientific[0] == scientific[1]
    attempts = read("direct.attempts.json")
    assert len(attempts) == 1
    a = attempts[0]
    assert (
        a["id"] == "5ad8cea64b1146c7bf2eb80e194e0798"
        and a["task_id"] == "c1119e1ab4ed431daca848c01811fc37"
    )
    assert a["status"] == "uncertain" and a["response"] is None
    assert a["ordinal"] == 1 and a["previous_id"] is None and a["retry_authorization"] is None
    assert all(v is None for v in a["usage"].values())
    assert a["error"]["diagnostic"] == {
        "category": "http_protocol",
        "phase": "request_open",
        "code": "REMOTE_DISCONNECTED",
    }
    assert a["request"]["actual_request"] == read("direct.planned-http.json")
    assert a["request"]["messages"] == read("direct.messages.json")
    assert (
        a["request"]["operation"] == "P08" and a["request"]["prompt_version"] == "w1-p08-single-v1"
    )
    action = read("direct.action.json")
    assert action["input"] == read("direct.input.json") and action["request"] == read(
        "direct.request.json"
    )
    assert (
        action["request"]["readiness_ref"] == "directed-seed-p07-readiness-single"
        and action["request"]["packet_ref"] == "directed-seed-p05-packet-single"
    )
    assert action["task_status"] == "blocked" and action["result"] is None
    assert read("direct.usage.json") is None
    assert read("assumption_structured.not-executed.json")["new_attempts"] == 0
    for name in [
        "direct.candidate.json",
        "direct.parsed-result.json",
        "direct.original-response.json",
        "assumption_structured.attempts.json",
        "assumption_structured.candidate.json",
    ]:
        assert not (HERE / name).exists(), name
    before, after = read("run-before.json"), read("run-after.json")
    assert after["status"] == "blocked"
    assert json.loads(after["plan"]) == json.loads(before["plan"]) + ["generation.P08"]
    assert {k: v for k, v in before.items() if k not in ["plan", "status"]} == {
        k: v for k, v in after.items() if k not in ["plan", "status"]
    }
    audit = read("runtime-audit.json")
    assert (
        audit["model_attempts_new"] == 1
        and audit["candidate_count"] == 0
        and not audit["assumption_task_created"]
    )
    for table, entries in read("protected-row-hashes-before.json").items():
        assert audit["protected_original_rows_unchanged"][table] == len(entries)
    review = read("codex-review.json")
    assert len(review["criteria"]) == 7 and all(
        c["assessment"] == "not_assessable" for c in review["criteria"]
    )
    assert review["science_validated"] is False
    print(
        "Verified hashes,exact approved six-field inputs,one uncertain DIRECT with unknown usage,no retry/candidate/second task,protected historical-row audit,and no unsupported scientific comparison."
    )


if __name__ == "__main__":
    main()
