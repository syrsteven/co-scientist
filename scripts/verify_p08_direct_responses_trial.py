"""Read-only/offline checks of the committed single DIRECT trial; no DB or network."""

import base64
import hashlib
import json
from datetime import datetime
from pathlib import Path

from co_scientist_next.generation_ops import USER_FIELDS, parse_candidate
from co_scientist_next.store import encode

ROOT = Path(__file__).resolve().parents[1]
TRIAL = ROOT / "docs/trials/p08-direct-responses-real"


def read(name):
    return json.loads((TRIAL / name).read_text())


def main():
    for line in (TRIAL / "SHA256SUMS").read_text().splitlines():
        expected, name = line.split("  ", 1)
        path = (TRIAL / name).resolve()
        assert path.is_relative_to(TRIAL)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, name
    preview = read("preflight/preview.json")
    prepared = json.loads(
        (ROOT / "docs/preparations/p08-explicit-migration/preview.json").read_text()
    )
    assert preview == prepared
    action = read("successor-action.json")
    payload = read("frozen-input.json")
    assert payload == json.loads(action["input"]) and set(payload) == USER_FIELDS
    assert payload["mode"] == "DIRECT"
    original = json.loads(read("historical-before.json")["action"]["input"])
    assert payload == {
        **original,
        "candidate_id_from_caller": "planned-p08-direct-responses",
    }
    attempts = sorted(
        [json.loads(p.read_text()) for p in (TRIAL / "attempts").glob("*/attempt.json")],
        key=lambda a: a["started_at"],
    )
    assert len(attempts) == 5
    summary = read("summary.json")
    submits = [a for a in attempts if a["call_key"] == "responses.submit"]
    queries = [a for a in attempts if a["call_key"].startswith("responses.query.")]
    assert len(submits) == 1 and len(queries) == 4
    assert all(a["status"] == "succeeded" for a in attempts)
    submit = json.loads(submits[0]["request"])
    actual = submit["actual_request"]
    assert submit == preview["actual_submission"]
    assert actual == read("actual-http-request.json")
    request_bytes = len(encode(actual).encode())
    assert request_bytes == 145411 and request_bytes <= 262144
    body = actual["body"]
    assert body["model"] == "gpt-6.1-sol"
    assert body["reasoning"] == {"effort": "high"}
    assert body["max_output_tokens"] == 32768
    assert body["text"]["format"] == {"type": "json_object"}
    assert body["background"] and body["store"]
    assert body["truncation"] == "disabled" and "temperature" not in body
    assert actual["timeout_seconds"] == actual["total_wait_seconds"] == 600
    assert (TRIAL / "actual-http-body.json").read_bytes() == encode(body).encode()
    assert read("historical-before.json") == read("historical-after.json")
    assert all(a["status"] == "uncertain" for a in read("historical-after.json")["attempts"])
    assert all(
        json.loads(a["usage"])
        == dict.fromkeys(["cost", "input_tokens", "output_tokens", "tool_units"])
        for a in read("historical-after.json")["attempts"]
    )
    assert all(
        v["all_original_rows_unchanged"] for v in read("historical-preservation.json").values()
    )
    statuses = []
    start = datetime.fromisoformat(submits[0]["started_at"])
    for i, attempt in enumerate(attempts):
        request = json.loads(attempt["request"])
        response = json.loads(attempt["response"])
        raw = base64.b64decode(response["body_base64"])
        assert hashlib.sha256(raw).hexdigest() == response["body_sha256"]
        assert raw.decode() == response["raw_response"]
        provider = json.loads(raw)
        assert provider["id"] == summary["response_id"]
        assert response["provider_usage"] == provider.get("usage")
        assert not response["truncated"] and not response["credential_redactions"]
        statuses.append(provider["status"])
        if i:
            assert request["actual_request"]["method"] == "GET"
            assert request["response_id"] == summary["response_id"]
            assert request["actual_request"]["endpoint"].endswith("/" + summary["response_id"])
            assert (datetime.fromisoformat(attempt["started_at"]) - start).total_seconds() < 1200
        if i > 1:
            gap = datetime.fromisoformat(attempt["started_at"]) - datetime.fromisoformat(
                attempts[i - 1]["finished_at"]
            )
            assert gap.total_seconds() >= 15
    assert statuses == ["queued", "in_progress", "in_progress", "in_progress", "completed"]
    assert summary["generation_status"] == "generated" and summary["science_validated"] is False
    final = read("final-provider-response.json")
    assert not final["error"] and not final["incomplete_details"]
    assert final["usage"] == read("final-provider-usage.json") == summary["provider_usage"]
    text = (TRIAL / "candidate-model-text.json").read_text()
    assert parse_candidate(text, payload) == read("candidate.json")
    assert read("parsed-result.json")["candidate"] == read("candidate.json")
    review = read("review-comparison.json")
    views = {v["id"]: v for v in payload["actual_frozen_seed_background_packet"]["source_views"]}
    for row in review["rows"]:
        if row["view_character_range"]:
            lo, hi = row["view_character_range"]
            assert views[row["source_view_ref"]]["text"][lo:hi] == row["source_excerpt"]
    page = read("page-readonly-verification.json")
    assert page["new_sends"] == 0
    assert page["database_sha256_before"] == page["database_sha256_after"]
    assert page["total_attempt_count_before"] == page["total_attempt_count_after"]
    print(
        "PASS: hashes, one POST/four same-ID GETs, frozen science, history, usage, candidate,22 review locators and read-only refresh"
    )


if __name__ == "__main__":
    main()
