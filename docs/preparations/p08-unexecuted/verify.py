"""Offline verification of unexecuted real-background P08 inputs. No credentials/DB/network."""

import hashlib
import json
from pathlib import Path

from co_scientist_next.generation import GenerationService
from co_scientist_next.generation_ops import PROMPT_VERSION, USER_FIELDS
from co_scientist_next.reading_model import OpenAIChat
from co_scientist_next.store import encode

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def read(name):
    return json.loads((HERE / name).read_text())


def main():
    for line in (HERE / "SHA256SUMS").read_text().splitlines():
        sha, name = line.split("  ", 1)
        assert hashlib.sha256((HERE / name).read_bytes()).hexdigest() == sha
    config = read("model-config.json")
    p07 = json.loads((ROOT / "docs/trials/p07-recovery-real/parsed-result.json").read_text())
    original_input = json.loads((ROOT / "docs/trials/p07-recovery-real/input.json").read_text())
    assert p07["artifact"]["decision"] == "ready"
    values = []
    for name, mode in [("direct", "DIRECT"), ("assumption_structured", "ASSUMPTION_STRUCTURED")]:
        payload = read(name + ".input.json")
        messages = read(name + ".messages.json")
        wire = read(name + ".planned-http.json")
        assert set(payload) == USER_FIELDS
        assert payload["mode"] == mode and payload["readiness_record"] == p07["artifact"]
        assert payload["actual_frozen_seed_background_packet"] == original_input["packet"]
        assert payload["goal_context"] == original_input["goal_context"]
        assert payload["seed_brief"] == original_input["seed_brief"]
        assert messages == GenerationService.messages(payload, PROMPT_VERSION)
        assert wire == OpenAIChat(config, None, authorized=False).request(messages)
        assert len(encode(wire).encode()) <= config["max_request_bytes"]
        assert wire["timeout_seconds"] == 600 and "temperature" not in wire["body"]
        values.append(
            {k: v for k, v in payload.items() if k not in ("mode", "candidate_id_from_caller")}
        )
    assert values[0] == values[1]
    assert read("manifest.json")["model_sends"] == 0
    print(
        "Verified2unexecuted six-field inputs: exact saved ready/packet/Goal/seed, fixed Prompt/config, full capacity, no examples/reviews/sibling candidates. RealP08calls0."
    )


if __name__ == "__main__":
    main()
