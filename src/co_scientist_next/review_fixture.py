"""Explicit isolated development import from PUBLIC committed trial files; no live DB access."""

import argparse
import json
from pathlib import Path

from .candidate_review_ops import digest
from .store import Store, encode, identity, now


def create_fixture(database, trial_directory):
    database = Path(database).resolve()
    if database.exists() or database.with_suffix(database.suffix + ".lock").exists():
        raise ValueError(
            "Fixture import requires a NEW isolated database; never overwrite or open a real DB"
        )
    directory = Path(trial_directory)
    payload = json.loads((directory / "frozen-input.json").read_text())
    action = json.loads((directory / "successor-action.json").read_text())
    result = json.loads((directory / "parsed-result.json").read_text())
    candidate = json.loads((directory / "candidate.json").read_text())
    if (
        result["candidate"] != candidate
        or payload["candidate_id_from_caller"] != candidate["candidate_id"]
    ):
        raise ValueError("Public trial candidate identity/content mismatch")
    binding = json.loads(action["binding"])
    run_id, goal_id = binding["run_id"], binding["goal_ref"]
    revision_id = payload["goal_context"]["brief_revision_id"]
    original_task_input = json.loads(
        json.loads((directory / "historical-before.json").read_text())["task"]["input"]
    )
    database.parent.mkdir(parents=True, exist_ok=True)
    with database.open("xb"):
        pass  # Atomic reservation: never race an existing/live database.
    with Store(database) as s:
        project = s.create_project(
            "DEVELOPMENT FIXTURE — copied real DIRECT candidate; no real review"
        )
        policy_ref = "OFFLINE-GOAL@fixture"
        with s.db:
            s.db.execute(
                "INSERT INTO brief_revisions VALUES(?,?,?,?,?)",
                (revision_id, project, None, encode(original_task_input["brief"]), now()),
            )
            s.db.execute(
                "INSERT INTO runs VALUES(?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    project,
                    revision_id,
                    policy_ref,
                    goal_id,
                    encode(["goal.prepare.v1", "goal.screen.v1", "generation.P08"]),
                    "awaiting_candidate_ethics",
                    now(),
                ),
            )
            s.db.execute(
                "INSERT INTO goal_contexts VALUES(?,?,?,?,?)",
                (goal_id, run_id, revision_id, encode(payload["goal_context"]), now()),
            )
            s.db.execute(
                "INSERT INTO goal_run_config VALUES(?,?)",
                (
                    run_id,
                    encode(
                        {
                            "development_test": True,
                            "policy": {
                                "id": "OFFLINE-GOAL",
                                "version": "fixture",
                                "text": "Development Goal fixture only",
                            },
                            "adapter_target": "development-test",
                        }
                    ),
                ),
            )
            for step, module in enumerate(["goal.prepare.v1", "goal.screen.v1", "generation.P08"]):
                task_id = action["task_id"] if step == 2 else identity()
                inp = {
                    **original_task_input,
                    "task_id": task_id,
                    "run_id": run_id,
                    "goal_context_ref": goal_id,
                    "policy_ref": policy_ref,
                }
                s.db.execute(
                    "INSERT INTO tasks VALUES(?,?,?,?,?,?,?)",
                    (task_id, run_id, step, module, encode(inp), "succeeded", None),
                )
                if step == 0:
                    output = {"goal_context": payload["goal_context"], "development_test": True}
                elif step == 1:
                    output = {
                        "execution_status": "screened",
                        "development_test": True,
                        "ethics": {
                            "completed": True,
                            "decision": "pass",
                            "policy_refs": [policy_ref],
                            "rationale": "OFFLINE development Goal fixture; not actual ethics review",
                            "limitations": ["No scientific or ethical validation"],
                        },
                    }
                else:
                    output = {
                        **result,
                        "execution_mode": "development_fixture_import",
                        "source_real_call_provenance": result["call_provenance"],
                        "call_provenance": {"fixture_import": True},
                        "development_test": True,
                    }
                s.db.execute("INSERT INTO results VALUES(?,?,?)", (task_id, encode(output), now()))
            config = {
                **json.loads(action["config"]),
                "execution_mode": "development_fixture_import",
            }
            s.db.execute(
                "INSERT INTO generation_actions VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    action["request_id"],
                    run_id,
                    action["task_id"],
                    candidate["candidate_id"],
                    action["request"],
                    encode(payload),
                    action["binding"],
                    encode(config),
                    action["prompt_version"],
                ),
            )
            s.fact(
                action["task_id"],
                "development_candidate_import",
                {
                    "source_trial_directory": str(directory),
                    "source_run_id": run_id,
                    "source_candidate_id": candidate["candidate_id"],
                    "source_candidate_sha256": digest(candidate),
                    "same_ids_in_ISOLATED_fixture_only": True,
                    "no_real_database_read": True,
                    "no_original_attempts_imported": True,
                    "science_validated": False,
                },
            )
    return {
        "run_id": run_id,
        "generation_ref": action["request_id"],
        "candidate_id": candidate["candidate_id"],
        "candidate_sha256": digest(candidate),
        "development_fixture": True,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", required=True)
    p.add_argument("--trial-directory", required=True)
    a = p.parse_args()
    print(json.dumps(create_fixture(a.db, a.trial_directory)))


if __name__ == "__main__":
    main()
