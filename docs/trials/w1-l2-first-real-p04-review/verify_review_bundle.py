"""Portable, read-only audit of this exported trial. Standard library only; no network."""

import base64
import gzip
import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree as ET

HERE = Path(__file__).resolve().parent


def read(name):
    return json.loads((HERE / name).read_text())


def main():
    checked = 0
    for line in (HERE / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ", 1)
        path = (HERE / name).resolve()
        assert path.is_relative_to(HERE) and not (HERE / name).is_symlink()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, name
        checked += 1
    text = (HERE / "material-original.txt").read_text()
    source = read("source-provenance.json")
    provider_raw = gzip.decompress((HERE / "saved-provider-response.json.gz").read_bytes())
    assert hashlib.sha256(provider_raw).hexdigest() == source["source_response_sha256"]
    markup = json.loads(provider_raw)["result"]["abstractText"]
    assert markup == (HERE / "provider-original-abstract.html").read_text()
    assert " ".join(ET.fromstring("<abstract>" + markup + "</abstract>").itertext()).strip() == text
    payload = read("p04-input.json")
    messages = read("p04-messages.json")
    request = read("actual-http-request.confirmed.json")
    config = read("model-config.confirmed.json")
    assert set(payload) == {"goal_context", "source_view", "seed_brief"}
    assert payload["source_view"] == read("material-view.json")
    assert payload["source_view"]["text"] == text and len(text) == 2746
    assert payload["source_view"]["access"] == "abstract"
    assert payload["source_view"]["character_range"] == [0, len(text)]
    assert (
        hashlib.sha256(text.encode()).hexdigest() == payload["source_view"]["original_text_sha256"]
    )
    assert json.loads(messages[-1]["content"]) == payload
    assert request["body"] == read("actual-http-body.json")
    assert request["body"] == {
        "model": "gpt-6.1-sol",
        "messages": messages,
        "reasoning_effort": "high",
        "max_completion_tokens": 32768,
        "response_format": {"type": "json_object"},
        "n": 1,
        "stream": False,
        "store": False,
    }
    assert config["timeout_seconds"] == request["timeout_seconds"] == 600
    assert request["body"]["model"] == config["model"]
    assert all(request["body"][k] == v for k, v in config["parameters"].items())
    visible = json.dumps(messages, ensure_ascii=False)
    for marker in ["REVIEW_FORM_OPERATOR_ONLY_DO_NOT_SEND", "Codex 初审，待独立人工复核"]:
        assert marker not in visible
    actual = read("trial-attempt.json")
    assert actual["request"]["actual_request"] == request
    assert actual["request"]["messages"] == messages
    assert actual["request"]["operation"] == "P04"
    assert actual["ordinal"] == 1 and actual["previous_id"] is None
    record = read("trial-response-record.json")
    assert actual["response"] == record
    raw_bytes = (HERE / "trial-original-response.json").read_bytes()
    assert raw_bytes == base64.b64decode(record["body_base64"])
    assert hashlib.sha256(raw_bytes).hexdigest() == record["body_sha256"]
    assert raw_bytes.decode() == record["raw_response"]
    response = json.loads(raw_bytes)
    assert response["usage"] == record["provider_usage"] == read("usage.json")
    assert response["choices"][0]["finish_reason"] == record["finish_reason"] == "stop"
    content = response["choices"][0]["message"]["content"]
    assert content == (HERE / "trial-model-content.txt").read_text() and content.strip()
    model = json.loads(content)
    result = read("trial-p04-result.json")
    assert result["background_status"] == "saved" and result["science_validated"] is False
    for index, card in enumerate(model["finding_cards"]):
        assert card["supporting_quote"] in text
        assert card["source_view_ref"] == payload["source_view"]["id"]
        parsed = result["artifact"]["finding_cards"][index]
        assert all(parsed[key] == value for key, value in card.items())
        assert parsed["negative_state"] == "not_reported_in_view"
    review = read("codex-initial-review.json")
    assert review["status"] == "Codex 初审，待独立人工复核"
    for row in review["rows"]:
        start, end = row["source"]["character_range"]
        assert text[start:end] == row["source"]["text"]
        for field in row["p04_fields"]:
            value = model
            for part in field["json_pointer"].strip("/").split("/"):
                value = value[int(part)] if isinstance(value, list) else value[part]
            assert value == field["value"]
    print(
        f"Verified {checked} hashes, source/request/response/usage bindings, {len(review['rows'])} review rows; no calls. science_validated=false"
    )


if __name__ == "__main__":
    main()
