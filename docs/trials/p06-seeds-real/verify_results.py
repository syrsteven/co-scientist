"""Portable artifact audit: no credentials, network, database or model execution."""

import base64
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
    p05 = read("source-p05.parsed-result.json")["artifact"]
    config = read("model-config.execution-approved.json")
    assert config["max_request_bytes"] == 65536 and config["timeout_seconds"] == 600
    assert config["parameters"] == {
        "reasoning_effort": "high",
        "max_completion_tokens": 32768,
        "response_format": {"type": "json_object"},
    }
    for name, kind in [("directed", "directed"), ("open", "open")]:
        payload, messages, wire = [
            read(name + suffix)
            for suffix in [".input.json", ".messages.json", ".planned-http.json"]
        ]
        assert json.loads(messages[-1]["content"]) == payload
        assert wire["body"] == {
            "model": "gpt-6.1-sol",
            "messages": messages,
            **config["parameters"],
            "n": 1,
            "stream": False,
            "store": False,
        }
        assert (
            wire["timeout_seconds"] == 600 and len(canonical(wire)) <= config["max_request_bytes"]
        )
        attempts = read(name + ".attempts.json")
        assert len(attempts) == 1 and attempts[0]["status"] == "succeeded"
        assert (
            attempts[0]["request"]["actual_request"] == wire
            and attempts[0]["request"]["messages"] == messages
        )
        response = attempts[0]["response"]
        raw = (HERE / (name + ".original-response.json")).read_bytes()
        assert raw == base64.b64decode(response["body_base64"])
        assert hashlib.sha256(raw).hexdigest() == response["body_sha256"]
        original = json.loads(raw)
        assert original["choices"][0]["finish_reason"] == response["finish_reason"] == "stop"
        assert (
            original["choices"][0]["message"]["content"]
            == (HERE / (name + ".model-content.txt")).read_text()
        )
        parsed = read(name + ".parsed-result.json")
        assert parsed["background_status"] == "saved" and parsed["science_validated"] is False
        assert original["usage"] == read(name + ".usage.json") == response["provider_usage"]
        model_result = json.loads(original["choices"][0]["message"]["content"])
        seed = parsed["artifact"]["seeds"][0]
        assert len(parsed["artifact"]["seeds"]) == len(model_result["questions"]) == 1
        assert seed["kind"] == kind and seed["orientation_ref"] == "p05-neutral-15cards-single"
        assert seed["run_id"] == read("preflight.json")["run_id"]
        assert seed["goal_ref"] == parsed["binding"]["goal_ref"]
        for key, value in model_result["questions"][0].items():
            assert seed[key] == value
        assert parsed["artifact"]["limitations"] == model_result["limitations"]
    directed, opened = read("directed.input.json"), read("open.input.json")
    assert directed["neutral_orientation"] == p05
    assert set(opened) == {
        "goal_context",
        "neutral_overview",
        "source_discovery_capabilities",
        "generic_search_constraints",
    }
    assert opened["neutral_overview"] == {
        k: p05[k] for k in ["overview", "competing_explanations", "limitations"]
    }
    assert opened["goal_context"] == directed["goal_context"]
    assert opened["generic_search_constraints"] == {"no_sibling_inputs": True, "requested_count": 1}
    assert read("open.parsed-result.json")["artifact"]["seeds"][0]["known_anchor_refs"] == []
    assert read("open.outcome.json")["input_matches_pre_directed_export"] is True
    for anchor in read("directed-anchor-evidence.json"):
        view = next(v for v in read("source-views.json") if v["id"] == anchor["source_view_id"])
        start, end = anchor["view_characters"]
        assert view["text"][start:end] == anchor["original_quote"]
    audit = read("runtime-audit.json")
    assert audit["source_before_sha256"] == audit["source_after_sha256"]
    assert audit["background_operations"] == ["P04", "P04", "P05", "P06_DIRECTED", "P06_OPEN"]
    assert (
        audit["strictly_sequential"]
        and audit["new_model_requests"] == 2
        and audit["new_search_requests"] == 0
    )
    assert len(read("codex-review.json")["rows"]) == 9
    print(
        "Verified SHA256, exact requests/raw responses/usage, one bound seed per call, OPEN isolation, anchor quotes and saved runtime audit. Science not validated."
    )


if __name__ == "__main__":
    main()
