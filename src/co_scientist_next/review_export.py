"""Read-only export of UNSENT Responses rendering of saved DEVELOPMENT review actions."""

import argparse
import hashlib
import json
from pathlib import Path

from .candidate_review import CandidateReviewService
from .candidate_review_ops import digest
from .generation_migration import ReadOnlyStore
from .responses_model import OpenAIResponses
from .store import encode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-db", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--model-config", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    config = json.loads(Path(args.model_config).read_text())
    adapter = OpenAIResponses(config)  # No credential read or send authorization.
    with ReadOnlyStore(args.fixture_db) as s:
        reviews = CandidateReviewService(s, development=True)
        actions = reviews.actions(args.run_id)
        if not s.rows("SELECT id FROM execution_facts WHERE kind='development_candidate_import'"):
            raise ValueError("Export accepts only explicit isolated imported development fixture")
        manifest = {
            "scope": "UNSENT_DEVELOPMENT_POLICY_ONLY",
            "credentials_read": False,
            "model_requests": 0,
            "production_policy_configured": False,
            "production_candidate_ethics_pass_exists": False,
            "production_P10_executable": False,
            "science_validated": False,
            "actions": [],
        }
        for operation in ("P09", "P10"):
            action = next(a for a in reversed(actions) if a["operation"] == operation)
            if not action["result"] or not action["result"]["development"]:
                raise ValueError("Saved development action/result required, no fabricated pass")
            payload, binding = reviews.ready_input(args.run_id, action["request"])
            if payload != action["input"] or binding != action["binding"]:
                raise ValueError("Saved fixture changed")
            messages = reviews.messages(payload, action["prompt_version"])
            actual = adapter.request(messages)
            size = len(encode(actual).encode())
            if size > config["max_request_bytes"]:
                raise ValueError("Complete unsent input exceeds configured capacity, no cropping")
            value = {
                "scope": manifest["scope"],
                "operation": operation,
                "binding": binding,
                "prompt_version": action["prompt_version"],
                "model_config": adapter.public_config(),
                "messages": messages,
                "actual_request": actual,
                "fixture_result_ref": action["request_id"],
                "source_candidate_sha256": digest(payload["fixed_candidate"]),
                "not_paid_authorization": True,
            }
            (out / (operation + ".unsent-request.json")).write_text(
                json.dumps(value, ensure_ascii=False, indent=2) + "\n"
            )
            (out / (operation + ".actual-input.json")).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
            )
            (out / (operation + ".fixture-result.json")).write_text(
                json.dumps(action["result"], ensure_ascii=False, indent=2) + "\n"
            )
            manifest["actions"].append(
                {
                    "operation": operation,
                    "actual_request_bytes": size,
                    "candidate_sha256": value["source_candidate_sha256"],
                    "binding": binding,
                }
            )
        (out / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        )
    (out / "SHA256SUMS").write_text(
        "".join(
            hashlib.sha256(p.read_bytes()).hexdigest() + "  " + p.name + "\n"
            for p in sorted(out.iterdir())
            if p.is_file() and p.name != "SHA256SUMS"
        )
    )
    print(json.dumps(manifest))


if __name__ == "__main__":
    main()
