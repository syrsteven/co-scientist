"""ONE explicitly authorized real P04 call, never run by tests or server startup."""

import argparse
import json
from pathlib import Path

from .background import BackgroundService
from .reading_model import OpenAIChat, load_credential
from .store import Store, identity


def main():
    parser = argparse.ArgumentParser(
        description="Explicit real P04 trial; may incur provider charges. No default model or fixture fallback."
    )
    parser.add_argument("--db", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--view-id", required=True)
    parser.add_argument("--seed-id")
    parser.add_argument("--config", required=True)
    parser.add_argument("--credential-env")
    parser.add_argument("--credential-file")
    parser.add_argument("--execute-real-call", action="store_true")
    args = parser.parse_args()
    if not args.execute_real_call:
        parser.error(
            "No call authorized. After separate approval, explicitly pass --execute-real-call"
        )
    try:
        adapter = OpenAIChat(
            json.loads(Path(args.config).read_text()),
            load_credential(env_name=args.credential_env, credential_file=args.credential_file),
            authorized=True,
        )
        with Store(args.db) as store:
            service = BackgroundService(store, adapter)
            request = {"view_id": args.view_id}
            if args.seed_id:
                request["seed_id"] = args.seed_id
            request_id = "trial-" + identity()
            service.submit(args.run_id, request_id, "P04", request)
            snapshot = service.execute(request_id)
            action = next(a for a in snapshot["actions"] if a["request_id"] == request_id)
            print(
                json.dumps(
                    {
                        "request_id": request_id,
                        "task_status": action["task_status"],
                        "result_status": (action["result"] or {}).get("background_status"),
                        "execution_mode": "real_model",
                        "usage": store.usage(run_id=args.run_id),
                        "science_validated": False,
                    }
                )
            )
    except (ValueError, KeyError, OSError, RuntimeError):
        parser.error(
            "Trial could not complete; inspect saved execution facts. Credential/input details withheld."
        )


if __name__ == "__main__":
    main()
