"""Offline-only export of the reviewed DIRECT scientific messages; never loads credentials."""

import hashlib
import json
from pathlib import Path

from co_scientist_next.generation import GenerationService
from co_scientist_next.responses_model import OpenAIResponses
from co_scientist_next.store import encode

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/preparations/responses-background"


def main():
    source = ROOT / "docs/preparations/p08-unexecuted"
    config = json.loads((OUT / "model-config.json").read_text())
    messages = json.loads((source / "direct.messages.json").read_text())
    inputs = json.loads((source / "direct.input.json").read_text())
    assert messages == GenerationService.messages(inputs)
    adapter = OpenAIResponses(config)  # Unconfigured, unauthorized; only constructs a dict.
    actual = adapter.request(messages)
    assert json.loads(actual["body"]["input"][-1]["content"]) == inputs
    assert len(encode(actual).encode()) <= config["max_request_bytes"]
    value = {
        "operation": "P08",
        "prompt_version": "w1-p08-single-v1",
        "messages": messages,
        "actual_request": actual,
        "model_config": config,
        "binding": json.loads((source / "direct.binding.json").read_text()),
        "execution_notice": "UNEXECUTED export, not a migration authorization or a new live Task",
    }
    (OUT / "direct.actual-request.json").write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    )
    manifest = {
        "baseline": "db37b47598c167d586b743f51f6a078e3c2b0cf6",
        "executed": False,
        "science_validated": False,
        "actual_request_bytes": len(encode(actual).encode()),
        "original_messages_sha256": hashlib.sha256(
            (source / "direct.messages.json").read_bytes()
        ).hexdigest(),
        "original_input_sha256": hashlib.sha256(
            (source / "direct.input.json").read_bytes()
        ).hexdigest(),
        "scientific_messages_equal": True,
        "six_field_user_equal": True,
        "model_requests": 0,
        "credential_loaded": False,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    files = ["model-config.json", "direct.actual-request.json", "manifest.json"]
    (OUT / "SHA256SUMS").write_text(
        "".join(hashlib.sha256((OUT / f).read_bytes()).hexdigest() + "  " + f + "\n" for f in files)
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
