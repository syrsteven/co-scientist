"""Portable read-only audit; no network, credentials, model client or database."""

import base64
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
STEPS = ["p03", "p04-1", "p04-2", "p04-3", "p05", "p07"]
SEED = "seed-f87361b21b4f44609dedfa2ac9afc7bc-0"
RUN = "cea909fe8a004010b1896df1c1d98e02"


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
    assert config["parameters"] == {
        "reasoning_effort": "high",
        "max_completion_tokens": 32768,
        "response_format": {"type": "json_object"},
    }
    for name in STEPS:
        wire, messages, payload = [
            read(name + suffix)
            for suffix in [".planned-http.json", ".messages.json", ".input.json"]
        ]
        assert wire["body"] == {
            "model": config["model"],
            "messages": messages,
            **config["parameters"],
            "n": 1,
            "stream": False,
            "store": False,
        }
        assert json.loads(messages[-1]["content"]) == payload
        assert (
            wire["timeout_seconds"] == 600 and len(canonical(wire)) <= config["max_request_bytes"]
        )
        assert payload["seed_brief"]["id"] == SEED
        sibling = "seed-0857eed597034cc4b63ecda95e0e6ebe-0"
        assert sibling not in json.dumps(payload) and "Codex 初审" not in json.dumps(
            payload, ensure_ascii=False
        )
        attempts = read(name + ".attempts.json")
        assert len(attempts) == 1
        assert attempts[0]["status"] == ("uncertain" if name == "p07" else "succeeded")
        actual = attempts[0]["request"]
        assert actual["actual_request"] == wire and actual["messages"] == messages
        if name == "p07":
            assert attempts[0]["response"] is None
            assert all(v is None for v in attempts[0]["usage"].values())
            assert read("p07.action.json")["task_status"] == "blocked"
            assert read("p07.action.json")["result"] is None
            assert not (HERE / "p07.parsed-result.json").exists()
            assert not (HERE / "p07.original-response.json").exists()
            continue
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
        assert original["usage"] == response["provider_usage"] == read(name + ".usage.json")
        result = read(name + ".parsed-result.json")
        assert result["background_status"] == "saved" and result["science_validated"] is False
        assert result["binding"]["run_id"] == RUN and result["binding"]["seed_id"] == SEED
    queries = read("p03.parsed-result.json")["artifact"]["queries"]
    assert 1 <= len(queries) <= 3
    for i, query in enumerate(queries, 1):
        action = read(f"search{i}.action.json")
        assert action["request"]["query"] == query["query"] and action["request"]["cursor"] is None
        assert action["request"]["query_origin"] == "model_planned_user_executed"
        context = action["request"]["background_context"]
        assert context == {
            "plan_ref": "directed-seed-p03-plan-single",
            "query_index": i - 1,
            "seed_id": SEED,
        }
        assert len(action["result"]["acquisition"]["items"]) <= 5
    for i in range(1, 4):
        for prefix in ["search", "fetch"]:
            attempts = read(f"{prefix}{i}.attempts.json")
            for a in attempts:
                assert a["status"] == "succeeded"
                response = a["response"]
                data = base64.b64decode(response["body_base64"])
                assert hashlib.sha256(data).hexdigest() == response["sha256"]
                assert data == (HERE / f"{prefix}{i}.{a['call_key']}.response").read_bytes()
                assert not response["truncated"]
        view = read(f"view{i}.json")
        acquisition = read(f"fetch{i}.action.json")["result"]["acquisition"]
        assert view["seed_id"] == SEED and view["text"] == acquisition["text"]
        assert view["access"] == "abstract" and view["cropped"] is False
        assert view["not_read_ranges"] == []
        payload = read(f"p04-{i}.input.json")
        assert payload["source_view"] == view
        artifact = read(f"p04-{i}.parsed-result.json")["artifact"]
        for card in artifact["finding_cards"]:
            assert card["source_view_ref"] == view["id"]
            assert card["supporting_quote"] in view["text"]
            assert all(q in view["text"] for q in card["negative_quotes"])
            assert (
                card["access"] == "abstract"
                and not card["images_seen"]
                and not card["supplements_seen"]
            )
    p05 = read("p05.input.json")
    assert p05["mode"] == "SEED_PACKET"
    assert set(p05["selection_manifest"]["selected_readings"]) == {
        "p04-v2-control-single",
        "p04-v2-complement-single",
        *[f"directed-seed-p04-source-{i}-single" for i in range(1, 4)],
    }
    assert p05["selection_manifest"]["omitted_readings"] == {}
    packet = read("p05.parsed-result.json")["artifact"]
    assert (
        packet["retained_contexts"] == p05["reading_records"]
        and packet["source_views"] == p05["source_views"]
    )
    findings = {c["id"] for r in p05["reading_records"] for c in r["finding_cards"]}
    assert set(packet["finding_refs"]) == findings
    assert read("p07.input.json")["packet"] == packet
    for row in read("source-finding-map.json")["rows"]:
        view = next(v for v in p05["source_views"] if v["id"] == row["source_view_id"])
        start, end = row["view_characters"]
        assert view["text"][start:end] == row["quote"]
        assert view["seed_id"] in (None, SEED)
    assert len(read("source-finding-map.json")["rows"]) == 39
    assert len(read("codex-review.json")["rows"]) == 11
    allowed = set(read("p07.input.json")["available_record_refs"])
    assert set(packet["finding_refs"]) <= allowed
    assert read("p07.transport-status.json")["readiness_decision"] is None
    assert read("p07.transport-status.json")["attempt_status"] == "uncertain"
    audit = read("runtime-audit.json")
    assert (
        audit["new_model_call_attempts"] == 6
        and audit["successful_model_calls"] == 5
        and audit["uncertain_model_calls"] == 1
        and audit["new_searches"] == 3
        and audit["new_fetches"] == 3
    )
    assert audit["original_task_attempt_result_material_goal_brief_unchanged"]
    assert audit["model_operations"] == ["P03", "P04", "P04", "P04", "P05", "P07"]
    print(
        "Verified hashes,5saved+1uncertain model attempts,no retry,3first-page searches,3abstract views,seed scope,available usage,all selected cards,P07 input only with no readiness decision,and preserved original-row audit. Science not validated."
    )


if __name__ == "__main__":
    main()
