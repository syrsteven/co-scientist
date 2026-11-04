"""Portable read-only result audit. No model client, credentials, DB writes or network."""

import base64
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def read(name):
    return json.loads((HERE / name).read_text())


def pointer(value, path):
    for part in path.strip("/").split("/"):
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def main():
    checked = 0
    for line in (HERE / "SHA256SUMS").read_text().splitlines():
        sha, name = line.split("  ", 1)
        path = (HERE / name).resolve()
        assert path.is_relative_to(HERE) and not (HERE / name).is_symlink()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == sha, name
        checked += 1
    payload, messages, wire = (
        read("input.json"),
        read("messages.json"),
        read("planned-http-request.json"),
    )
    assert json.loads(messages[-1]["content"]) == payload
    assert wire["body"]["messages"] == messages
    config = read("model-config.json")
    assert wire["body"] == {
        "model": "gpt-6.1-sol",
        "messages": messages,
        "reasoning_effort": "high",
        "max_completion_tokens": 32768,
        "response_format": {"type": "json_object"},
        "n": 1,
        "stream": False,
        "store": False,
    }
    assert config["timeout_seconds"] == wire["timeout_seconds"] == 600
    assert (
        len(json.dumps(wire, sort_keys=True, ensure_ascii=False).encode())
        == 52256
        <= config["max_request_bytes"]
    )
    assert len(payload["reading_records"]) == 2 and len(payload["source_views"]) == 2
    assert (
        payload["mode"] == "NEUTRAL_ORIENTATION"
        and payload["selection_manifest"]["omitted_readings"] == {}
    )
    cards, byid = [], {}
    for name, record in zip(["control", "complement"], payload["reading_records"]):
        source = read(f"sources/p04-{name}.parsed-result.json")
        assert {k: v for k, v in record.items() if k != "record_ref"} == source["artifact"]
        assert source["execution_mode"] == "real_model"
        view = read(f"sources/{name}-view.json")
        assert view in payload["source_views"]
        assert view["text"] == (HERE / f"sources/{name}-view.txt").read_text()
        cards.extend(record["finding_cards"])
    byid = {c["id"]: c for c in cards}
    assert len(cards) == len(byid) == 15
    for marker in ["Codex 初审", "C-08", "M-09", "REVIEW_FORM_OPERATOR_ONLY_DO_NOT_SEND"]:
        assert marker not in json.dumps(messages, ensure_ascii=False)
    records = read("attempts.json")
    assert len(records) == 1
    attempt = records[0]
    assert (
        attempt["ordinal"] == 1
        and attempt["previous_id"] is None
        and attempt["status"] == "succeeded"
    )
    assert (
        attempt["request"]["operation"] == "P05"
        and attempt["request"]["prompt_version"] == "w1-l2-p03-p07-v1"
    )
    assert (
        attempt["request"]["actual_request"] == wire and attempt["request"]["messages"] == messages
    )
    response = attempt["response"]
    original = (HERE / "original-response.json").read_bytes()
    assert base64.b64decode(response["body_base64"]) == original
    assert hashlib.sha256(original).hexdigest() == response["body_sha256"]
    envelope = json.loads(original)
    assert (
        envelope["model"] == "gpt-6.1-sol"
        and envelope["choices"][0]["finish_reason"] == response["finish_reason"] == "stop"
    )
    assert envelope["usage"] == response["provider_usage"] == read("usage.json")
    content = envelope["choices"][0]["message"]["content"]
    assert content.strip() and content == (HERE / "model-content.txt").read_text()
    model = json.loads(content)
    assert set(model["finding_refs"]) == set(byid)
    for edge in model["knowledge_edges"]:
        assert edge["kind"] in {"observation", "author_interpretation", "analogy", "hypothesis"}
        assert set(edge["finding_refs"]) <= set(byid)
    result = read("parsed-result.json")
    assert result == read("action.json")["result"] and result["background_status"] == "saved"
    assert result["artifact"]["retained_contexts"] == payload["reading_records"]
    assert result["artifact"]["source_views"] == payload["source_views"]
    assert result["science_validated"] is False
    audit = read("runtime-audit.json")
    assert (
        audit["p04_preservation_sha256_before"]
        == audit["p04_preservation_sha256_after"]
        == read("p04-preservation-before.json")["sha256"]
    )
    assert (
        audit["background_operations"] == ["P04", "P04", "P05"] and audit["p05_attempt_count"] == 1
    )
    views = {v["source_ref"]: v for v in payload["source_views"]}
    review = read("codex-review.json")
    assert review["status"] == "Codex 初审，待独立人工复核" and review["science_validated"] is False
    for row in review["rows"]:
        for field in row["actual_p05_fields"]:
            assert pointer(model, field["json_pointer"]) == field["value"]
        for source in row["p04_fields"]:
            assert byid[source["finding_id"]][source["field"]] == source["value"]
        for fragment in row["original_fragments"]:
            v = views[fragment["source_ref"]]
            start, end = fragment["view_character_range"]
            assert v["text"][start:end] == fragment["text"]
            assert fragment["obtained_text_character_range"] == [
                v["character_range"][0] + start,
                v["character_range"][0] + end,
            ]
    print(
        f"Verified {checked} hashes; 15 unmodified cards, 2 complete views, one P05 Attempt, raw usage/refs and {len(review['rows'])} review rows; no execution. science_validated=false"
    )


if __name__ == "__main__":
    main()
