"""Read exported facts only; standard library, no database/model/client/network access."""

import base64
import gzip
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
    hashes = 0
    for line in (HERE / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ", 1)
        path = (HERE / name).resolve()
        assert path.is_relative_to(HERE) and not (HERE / name).is_symlink()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, name
        hashes += 1
    config = read("model-config.json")
    assert config["model"] == "gpt-6.1-sol" and config["timeout_seconds"] == 600
    assert config["parameters"] == {
        "reasoning_effort": "high",
        "max_completion_tokens": 32768,
        "response_format": {"type": "json_object"},
    }
    summary = read("execution-summary.json")
    assert summary["new_real_requests"] == 2 and summary["automatic_retries"] == 0
    raw_models, view_texts = {}, {}
    for name, request_id, view_id in [
        ("control", "p04-v2-control-single", "75bf96a0e25b4e6aa10e54f6781a5382"),
        ("complement", "p04-v2-complement-single", "876e76bb00f84e928a89cbea813dacad"),
    ]:
        records = read(name + ".attempts.json")
        assert len(records) == 1
        record = records[0]
        assert (
            record["ordinal"] == 1
            and record["previous_id"] is None
            and record["status"] == "succeeded"
        )
        action = read(name + ".action.json")
        assert action["request_id"] == request_id and action["operation"] == "P04"
        assert (
            action["prompt_version"]
            == record["request"]["prompt_version"]
            == "w1-l2-p04-context-v2"
        )
        request = record["request"]
        reviewed = read(name + ".reviewed-planned-http.json")
        assert request["actual_request"] == reviewed
        assert request["messages"] == read(name + ".reviewed-p04-messages.json")
        assert (
            json.loads(request["messages"][-1]["content"])
            == action["input"]
            == read(name + ".reviewed-p04-input.json")
        )
        assert set(action["input"]) == {"goal_context", "source_view", "seed_brief"}
        assert reviewed["body"] == {
            "model": config["model"],
            "messages": request["messages"],
            **config["parameters"],
            "n": 1,
            "stream": False,
            "store": False,
        }
        assert reviewed["timeout_seconds"] == 600
        assert "Codex 初审" not in json.dumps(request["messages"], ensure_ascii=False)
        view = read(f"views/{name}.json")
        text = (HERE / f"views/{name}.txt").read_text()
        obtained = gzip.decompress(
            (HERE / f"acquisition/{name}.obtained-text.txt.gz").read_bytes()
        ).decode()
        start, end = view["character_range"]
        assert obtained[start:end] == text == view["text"]
        assert action["input"]["source_view"] == view and view["id"] == view_id
        raw_bytes = (HERE / f"{name}.original-response.json").read_bytes()
        response = record["response"]
        assert raw_bytes == base64.b64decode(response["body_base64"])
        assert hashlib.sha256(raw_bytes).hexdigest() == response["body_sha256"]
        envelope = json.loads(raw_bytes)
        assert envelope["model"] == config["model"]
        assert envelope["choices"][0]["finish_reason"] == response["finish_reason"] == "stop"
        assert envelope["usage"] == response["provider_usage"] == read(name + ".usage.json")
        content = envelope["choices"][0]["message"]["content"]
        assert content == (HERE / f"{name}.model-content.txt").read_text() and content.strip()
        raw = json.loads(content)
        parsed = read(name + ".parsed-result.json")
        assert (
            parsed == action["result"]
            and parsed["background_status"] == "saved"
            and parsed["science_validated"] is False
        )
        for i, card in enumerate(raw["finding_cards"]):
            assert card["source_view_ref"] == view_id and card["supporting_quote"] in text
            assert all(q in text for q in card["negative_quotes"])
            assert all(parsed["artifact"]["finding_cards"][i][k] == v for k, v in card.items())
        raw_models[name], view_texts[name] = raw, text
    totals = summary["total_usage"]
    assert totals["prompt_tokens"] == sum(
        read(n + ".usage.json")["prompt_tokens"] for n in raw_models
    )
    assert totals["completion_tokens"] == sum(
        read(n + ".usage.json")["completion_tokens"] for n in raw_models
    )
    assert totals["reasoning_tokens"] == sum(
        read(n + ".usage.json")["completion_tokens_details"]["reasoning_tokens"] for n in raw_models
    )
    assert totals["total_tokens"] == totals["prompt_tokens"] + totals["completion_tokens"]
    assert totals["cost"] is None
    facts = read("run-facts.json")
    assert facts["table_counts"]["background_actions"] == 2
    assert all(
        t["module"]
        in {
            "goal.prepare.v1",
            "goal.screen.v1",
            "literature.search.v1",
            "literature.fetch.v1",
            "background.P04",
        }
        for t in facts["task_statuses"]
    )
    baseline = read("baseline-v1/model-content.txt")
    old_source = json.loads(read("baseline-v1/messages.json")[-1]["content"])["source_view"]["text"]
    assert old_source == view_texts["control"]
    review = read("codex-review.json")
    assert review["status"] == "Codex 初审，待独立人工复核" and review["science_validated"] is False
    for row in review["rows"]:
        name = row["material"]
        for source in row["source_fragments"]:
            start, end = source["view_character_range"]
            assert view_texts[name][start:end] == source["text"]
            offset = read(f"views/{name}.json")["character_range"][0]
            assert source["obtained_text_character_range"] == [offset + start, offset + end]
        for field in row["actual_p04_fields"]:
            assert pointer(raw_models[name], field["json_pointer"]) == field["value"]
    for item in review["v1_v2_comparison"]:
        assert pointer(baseline, item["v1"]["json_pointer"]) == item["v1"]["value"]
        assert pointer(raw_models["control"], item["v2"]["json_pointer"]) == item["v2"]["value"]
    print(
        f"Verified {hashes} hashes; two single Attempts, exact reviewed requests, raw usage/results and {len(review['rows'])} review rows. No execution. science_validated=false"
    )


if __name__ == "__main__":
    main()
