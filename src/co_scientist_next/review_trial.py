"""One nonproduction real-review trial: prepare offline; separately authorized POST/GET only."""

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

from .candidate_review import CandidateReviewService
from .candidate_review_ops import SYSTEM, VERSION, digest, prompt
from .generation_migration import ReadOnlyStore
from .reading_model import load_credential
from .responses_model import OpenAIResponses
from .store import Store, encode

RUN = "cea909fe8a004010b1896df1c1d98e02"
GENERATION = "planned-p08-responses-migration-single"
CANDIDATE = "planned-p08-direct-responses"
IDS = {"P09": "p09-real-nonprod-single-v1", "P10": "p10-real-nonprod-single-v1"}
MARKER = "candidate_review_trial_prepared"


def read(path):
    return json.loads(Path(path).read_text())


def write(directory, name, value):
    (Path(directory) / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inventory(store):
    return {
        row["name"]: store.rows('SELECT * FROM "' + row["name"] + '" ORDER BY rowid')
        for row in store.rows(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def checksums(directory):
    directory = Path(directory)
    (directory / "SHA256SUMS").write_text(
        "".join(
            sha_file(p) + "  " + p.name + "\n"
            for p in sorted(directory.iterdir())
            if p.is_file() and p.name != "SHA256SUMS"
        )
    )


def prepare(source_db, database, policies, output):
    source_db, database = Path(source_db).resolve(), Path(database).resolve()
    policies, output = Path(policies), Path(output)
    if database.exists() or Path(str(database) + ".lock").exists() or source_db == database:
        raise ValueError(
            "Use one NEW isolated trial database; source/existing databases are forbidden"
        )
    model = read(policies / "model-config.json")
    adapter = OpenAIResponses(model)  # No credential, no authorization, never sends.
    use = (policies / "intended-use.txt").read_text().strip()
    p09 = {
        "operation": "P09",
        "generation_ref": GENERATION,
        "intended_use": use,
        "policy": read(policies / "candidate-ethics-policy.json"),
        "decision_policy": read(policies / "decision-policy.json"),
    }
    p10 = {
        "operation": "P10",
        "generation_ref": GENERATION,
        "ethics_ref": IDS["P09"],
        "policy": read(policies / "r0-policy.json"),
    }
    if p09["policy"]["mode"] != "development" or p10["policy"]["mode"] != "development":
        raise ValueError("This trial policy must remain nonproduction")
    if p09["decision_policy"]["routes"] != {
        "pass": "continue",
        "reject": "stop",
        "incomplete": "hold",
    }:
        raise ValueError("This trial requires explicit pass/reject/incomplete routes")
    before = sha_file(source_db)
    with ReadOnlyStore(source_db) as source:
        if source.rows(
            "SELECT name FROM sqlite_master WHERE name='candidate_review_actions'"
        ) and source.rows("SELECT request_id FROM candidate_review_actions WHERE run_id=?", (RUN,)):
            raise ValueError(
                "Source already has candidate review facts; inspect instead of importing another execution"
            )
        if source.rows(
            "SELECT id FROM execution_facts WHERE kind IN ('development_candidate_import',?)",
            (MARKER,),
        ):
            raise ValueError("Use original saved scientific facts, not a fixture or another trial")
        action, candidate, goal, generated = CandidateReviewService(source).candidate(
            RUN, GENERATION
        )
        if candidate["candidate_id"] != CANDIDATE:
            raise ValueError("Wrong target candidate")
        original = inventory(source)
        database.parent.mkdir(parents=True, exist_ok=True)
        with database.open("xb"):
            pass
        destination = sqlite3.connect(database)
        try:
            source.db.backup(destination)
        finally:
            destination.close()
    if sha_file(source_db) != before:
        raise ValueError("Source changed during snapshot; inspect before proceeding")
    views = generated["actual_frozen_seed_background_packet"]["source_views"]
    frozen = {
        "version": "candidate-review-nonprod-trial-v1",
        "run_id": RUN,
        "goal_ref": json.loads(action["binding"])["goal_ref"],
        "generation_ref": GENERATION,
        "candidate_id": CANDIDATE,
        "candidate_sha256": digest(candidate),
        "goal_sha256": digest(goal),
        "source_views_sha256": digest(views),
        "p09_request": p09,
        "p10_request": p10,
        "request_ids": IDS,
        "model_config": model,
        "prompt_version": VERSION,
        "fixed_prompts": {"system": SYSTEM, "P09": prompt("P09"), "P10": prompt("P10")},
    }
    preparation_hash = digest(frozen)
    with Store(database) as s:
        for table, rows in original.items():
            if s.rows('SELECT * FROM "' + table + '" ORDER BY rowid') != rows:
                raise ValueError("Snapshot changed historical facts")
        service = CandidateReviewService(s, adapter, development=True)
        payload, binding = service.ready_input(RUN, p09)
        messages = service.messages(payload, VERSION)
        actual = adapter.request(messages)
        if len(encode(actual).encode()) > model["max_request_bytes"]:
            raise ValueError(
                "Complete P09 request exceeds configured capacity; nothing cropped or sent"
            )
        with s.db:
            s.fact(
                action["task_id"],
                MARKER,
                {
                    "preparation_sha256": preparation_hash,
                    "source_database_sha256": before,
                    "source_database": str(source_db),
                    "frozen": frozen,
                    "paid_execution_authorized": False,
                    "scientific_records_unchanged": True,
                    "execution_scope": "real_model_only_nonproduction_policy",
                },
            )
        if s.rows("SELECT * FROM candidate_review_actions WHERE run_id=?", (RUN,)):
            raise ValueError("Preparation must not create review tasks or decisions")
    output.mkdir(parents=True, exist_ok=True)
    write(output, "trial.json", frozen)
    write(output, "P09.actual-input.json", payload)
    write(
        output,
        "P09.unsent-request.json",
        {
            "operation": "P09",
            "request_id": IDS["P09"],
            "binding": binding,
            "prompt_version": VERSION,
            "model_config": model,
            "messages": messages,
            "actual_request": actual,
            "status": "prepared_not_authorized",
            "model_requests": 0,
            "policy_mode": "development",
            "proposed_execution_mode": "real_model",
        },
    )
    write(
        output,
        "P10.input-template.json",
        {
            "executable": False,
            "reason": "No real completed P09 pass exists; never substitute fixture pass",
            "request_id": IDS["P10"],
            "input_template": {
                "goal_context": goal,
                "fixed_candidate": candidate,
                "passed_candidate_ethics_record": None,
                "actual_visible_source_views": views,
                "r0_policy_version": p10["policy"],
            },
            "assembly": {
                "requires": "saved real Responses P09 completed/pass with matching candidate/Goal/Run/use/policy and M15 provenance",
                "record": IDS["P09"],
                "no_placeholder_pass": True,
            },
        },
    )
    write(
        output,
        "origin.json",
        {
            "source_database": str(source_db),
            "source_database_sha256_before": before,
            "source_database_sha256_after": sha_file(source_db),
            "isolated_database": str(database),
            "isolated_snapshot_sha256": sha_file(database),
            "preparation_sha256": preparation_hash,
            "source_run_id": RUN,
            "source_goal_ref": frozen["goal_ref"],
            "source_candidate_id": CANDIDATE,
            "candidate_sha256": frozen["candidate_sha256"],
            "source_views_sha256": frozen["source_views_sha256"],
            "source_rows_preserved": {
                k: {"count": len(v), "sha256": digest(v)} for k, v in original.items()
            },
            "new_review_tasks": 0,
            "new_review_attempts": 0,
            "P09_decision": None,
            "P10_executable": False,
            "model_credentials_read": False,
            "model_requests": 0,
            "science_validated": False,
        },
    )
    checksums(output)
    return {
        "prepared": True,
        "preparation_sha256": preparation_hash,
        "candidate_sha256": digest(candidate),
        "p09_request_bytes": len(encode(actual).encode()),
        "P10_executable": False,
        "model_requests": 0,
    }


def validate_package(store, package):
    package = Path(package)
    frozen = read(package / "trial.json")
    origin = read(package / "origin.json")
    actual_db = Path(store.one("PRAGMA database_list")["file"]).resolve()
    if actual_db != Path(origin["isolated_database"]).resolve():
        raise ValueError("Use the designated trial database, not another snapshot copy")
    marker = store.rows("SELECT detail FROM execution_facts WHERE kind=?", (MARKER,))
    if (
        len(marker) != 1
        or json.loads(marker[0]["detail"])["frozen"] != frozen
        or json.loads(marker[0]["detail"])["preparation_sha256"] != digest(frozen)
    ):
        raise ValueError("Trial package/database provenance mismatch")
    for line in (package / "SHA256SUMS").read_text().splitlines():
        expected, name = line.split("  ", 1)
        p = (package / name).resolve()
        if not p.is_relative_to(package.resolve()) or sha_file(p) != expected:
            raise ValueError("Prepared package checksum mismatch")
    if frozen["fixed_prompts"] != {"system": SYSTEM, "P09": prompt("P09"), "P10": prompt("P10")}:
        raise ValueError("Prepared Prompt content changed; new review/authorization required")
    adapter = OpenAIResponses(frozen["model_config"])
    g = CandidateReviewService(store, adapter, development=True)
    payload, binding = g.ready_input(frozen["run_id"], frozen["p09_request"])
    exported = read(package / "P09.unsent-request.json")
    if (
        exported["messages"] != g.messages(payload, frozen["prompt_version"])
        or exported["actual_request"] != adapter.request(exported["messages"])
        or exported["binding"] != binding
    ):
        raise ValueError("Prepared complete P09 input/request changed")
    return frozen, g


def assemble_p10(database, package, output):
    with ReadOnlyStore(database) as store:
        frozen, service = validate_package(store, package)
        payload, binding = service.ready_input(frozen["run_id"], frozen["p10_request"])
        messages = service.messages(payload, frozen["prompt_version"])
        actual = service.adapter.request(messages)
        if len(encode(actual).encode()) > frozen["model_config"]["max_request_bytes"]:
            raise ValueError("Complete P10 exceeds configured capacity; nothing sent or cropped")
        output = Path(output)
        output.mkdir(parents=True, exist_ok=True)
        write(
            output,
            "P10.unsent-request.json",
            {
                "operation": "P10",
                "request_id": frozen["request_ids"]["P10"],
                "binding": binding,
                "messages": messages,
                "actual_request": actual,
                "policy_mode": "development",
                "proposed_execution_mode": "real_model",
                "status": "assembled_not_authorized",
                "prompt_version": frozen["prompt_version"],
                "model_config": frozen["model_config"],
                "model_requests": 0,
            },
        )
    return {
        "assembled": True,
        "actual_request_bytes": len(encode(actual).encode()),
        "model_requests": 0,
    }


# Narrow scope: this one prepared P09 only, never P08/P10 or another Run/task.
RECOVERY_TASK = "250e3e6dea7a430fb07e71080c20a345"
RECOVERY_ATTEMPT = "da49fb3eb36c4e8aadee6f34e0757d15"
RECOVERY_ACKS = frozenset({"prior_execution_unknown", "duplicate_execution_charge", "store_true"})
RECOVERY_REASON = "Explicit user authorization: prior P09 may have executed/charged; accept one additional identical POST and duplicate execution/charge risk, store=true. No third submit."
RECOVERY_MARKER = "p09_single_retry_reserved"


def recovery_scope(service, frozen, original_id):
    if original_id != RECOVERY_ATTEMPT:
        raise ValueError("Only the named original P09 Attempt is authorized")
    action = service.store.one(
        "SELECT * FROM candidate_review_actions WHERE request_id=?",
        (frozen["request_ids"]["P09"],),
    )
    if action["task_id"] != RECOVERY_TASK or action["operation"] != "P09":
        raise ValueError("Only the named same-Task P09 recovery is authorized")
    original = service.store.one(
        "SELECT * FROM attempts WHERE id=? AND task_id=?", (original_id, RECOVERY_TASK)
    )
    payload, binding = service.ready_input(frozen["run_id"], frozen["p09_request"])
    from .candidate_review import RemoteReview

    expected = RemoteReview(service).request_record(action, payload, binding)
    if (
        original["status"] != "uncertain"
        or original["call_key"] != "responses.submit"
        or original["target"] != service.adapter.target + "/create"
        or original["request"] != encode(expected)
        or action["input"] != encode(payload)
        or action["binding"] != encode(binding)
        or not service.config_matches(action)
    ):
        raise ValueError("Frozen original request/input/config/Prompt/policy binding changed")
    return action, original


def p09_retry_allowed(service, action, previous, request):
    if (
        action["task_id"] != RECOVERY_TASK
        or action.get("operation") != "P09"
        or previous["id"] != RECOVERY_ATTEMPT
        or previous["status"] != "uncertain"
        or previous["retry_authorization"] != RECOVERY_REASON
        or previous["request"] != encode(request)
    ):
        return False
    markers = service.store.rows(
        "SELECT detail FROM execution_facts WHERE task_id=? AND kind=?",
        (RECOVERY_TASK, RECOVERY_MARKER),
    )
    attempts = service.store.rows(
        "SELECT id FROM attempts WHERE task_id=? AND call_key='responses.submit'", (RECOVERY_TASK,)
    )
    return (
        len(markers) == 1
        and len(attempts) == 1
        and json.loads(markers[0]["detail"])["original_attempt_id"] == RECOVERY_ATTEMPT
        and json.loads(markers[0]["detail"])["request_sha256"] == digest(request)
    )


def reserve_p09_retry(service, frozen, original_id):
    """Offline only. Original retry_authorization is the only permitted row change."""
    s = service.store
    a, old = recovery_scope(service, frozen, original_id)
    attempts = s.rows(
        "SELECT * FROM attempts WHERE task_id=? AND call_key='responses.submit' ORDER BY ordinal",
        (RECOVERY_TASK,),
    )
    jobs = s.rows("SELECT * FROM remote_generations WHERE task_id=?", (RECOVERY_TASK,))
    if jobs or len(attempts) > 1:
        # A committed second in-flight fact is already the single authorized send.
        # On restart scope recovery to this Task, never globally reset other calls.
        if any(p["status"] == "in_flight" for p in attempts[1:]):
            s.recover(run_id=a["run_id"], task_id=RECOVERY_TASK)
        return False
    if old["response"] is not None:
        raise ValueError("Saved original response needs inspection/recovery, never a new POST")
    service.clear_calls(a["run_id"], RECOVERY_TASK)
    markers = s.rows(
        "SELECT detail FROM execution_facts WHERE task_id=? AND kind=?",
        (RECOVERY_TASK, RECOVERY_MARKER),
    )
    detail = {
        "original_attempt_id": original_id,
        "task_id": RECOVERY_TASK,
        "call_key": old["call_key"],
        "request_sha256": digest(json.loads(old["request"])),
        "preparation_sha256": digest(frozen),
        "acknowledgements": sorted(RECOVERY_ACKS),
        "additional_post_limit": 1,
        "original_row_sha256_before_authorization": digest(
            {k: v for k, v in old.items() if k != "retry_authorization"}
        ),
    }
    if markers and (len(markers) != 1 or json.loads(markers[0]["detail"]) != detail):
        raise ValueError("Retry reservation changed")
    if old["retry_authorization"] not in (None, RECOVERY_REASON):
        raise ValueError("Different retry authorization requires inspection")
    # Single Store writer. Marker and M15 authorization commit together; a crash
    # before task_retry is safe: another explicit command resumes the same grant.
    if not markers:
        with s.db:
            s.fact(RECOVERY_TASK, RECOVERY_MARKER, detail)
            s.authorize_uncertain_retry(original_id, RECOVERY_REASON)
    task = s.one("SELECT status FROM tasks WHERE id=?", (RECOVERY_TASK,))
    if task["status"] == "blocked":
        s.retry_task(RECOVERY_TASK, RECOVERY_REASON)
    return True


def recover_p09(
    database,
    package,
    original_id,
    *,
    acknowledgements=(),
    credential_env=None,
    credential_file=None,
):
    if frozenset(acknowledgements) != RECOVERY_ACKS:
        raise ValueError(
            "Explicit prior-unknown, duplicate-charge and store=true acknowledgements required"
        )
    with ReadOnlyStore(database) as readonly:
        frozen, service = validate_package(readonly, package)
        recovery_scope(service, frozen, original_id)
    with Store(database) as store:
        frozen, service = validate_package(store, package)
        if not reserve_p09_retry(service, frozen, original_id):
            jobs = store.rows("SELECT * FROM remote_generations WHERE task_id=?", (RECOVERY_TASK,))
            if jobs and jobs[0]["status"] not in ("queued", "in_progress", "unknown"):
                from .candidate_review import RemoteReview

                action = store.one(
                    "SELECT * FROM candidate_review_actions WHERE task_id=?", (RECOVERY_TASK,)
                )
                RemoteReview(service).execute(action, recover=True)  # Local apply, no key/send.
            return {
                "sent": False,
                "reason": "Single retry already attempted or saved response ID exists; inspect/query only",
                "review_records": service.snapshot(frozen["run_id"]),
            }
        adapter = OpenAIResponses(
            frozen["model_config"],
            load_credential(env_name=credential_env, credential_file=credential_file),
            authorized=True,
        )
        service = CandidateReviewService(store, adapter, development=True)
        return {
            "recovery": "single_identical_P09_retry",
            "review_records": service.execute(frozen["request_ids"]["P09"], recover=True),
        }


def operate(
    database, package, operation, *, query=False, credential_env=None, credential_file=None
):
    """Future explicit operator action only; preparation/assembly never call this."""
    # Reject the original/another database before any schema initialization or write.
    with ReadOnlyStore(database) as readonly:
        validate_package(readonly, package)
    with Store(database) as store:
        frozen, service = validate_package(store, package)
        ref = frozen["request_ids"][operation]
        request = frozen["p09_request"] if operation == "P09" else frozen["p10_request"]
        service.ready_input(
            frozen["run_id"], request
        )  # P10 real-pass gate BEFORE any credential load.
        existing = store.rows("SELECT * FROM candidate_review_actions WHERE request_id=?", (ref,))
        if existing:
            a = existing[0]
            attempts = store.rows("SELECT id FROM attempts WHERE task_id=?", (a["task_id"],))
            jobs = store.rows("SELECT * FROM remote_generations WHERE task_id=?", (a["task_id"],))
            if not query and attempts:
                return {
                    "sent": False,
                    "reason": "Prior submission exists; never resend. Query only saved ID if available.",
                    "remote": [
                        {"response_id": j["response_id"], "status": j["status"]} for j in jobs
                    ],
                }
            if query and (
                not jobs or jobs[0]["status"] not in ("queued", "in_progress", "unknown")
            ):
                return {"sent": False, "reason": "No pending saved ID; no submission or query sent"}
        elif query:
            raise ValueError("No saved task/response ID; query cannot create a submission")
        adapter = OpenAIResponses(
            frozen["model_config"],
            load_credential(env_name=credential_env, credential_file=credential_file),
            authorized=True,
        )
        service = CandidateReviewService(store, adapter, development=True)
        if query:
            snapshot = service.query_remote(ref)
        else:
            action = service.submit(frozen["run_id"], ref, request)
            with store.db:
                store.fact(
                    action["task_id"],
                    "nonproduction_trial_post_explicitly_authorized",
                    {
                        "operation": operation,
                        "preparation_sha256": digest(frozen),
                        "scope": "one POST for this task only; nonproduction policy",
                        "store_true_acknowledged": True,
                    },
                )
            snapshot = service.execute(ref)
        a = next(a for a in snapshot["actions"] if a["request_id"] == ref)
        return {
            "request_id": ref,
            "task_status": a["task_status"],
            "remote": a["remote"],
            "review_status": (a["result"] or {}).get("review_status"),
            "decision": (a["result"] or {}).get("artifact"),
            "policy_mode": "development",
            "execution_mode": "real_model",
            "science_validated": False,
        }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "command",
        choices=[
            "prepare",
            "inspect",
            "assemble-p10",
            "submit-p09",
            "query-p09",
            "submit-p10",
            "query-p10",
            "recover-p09",
        ],
    )
    p.add_argument("--db", required=True)
    p.add_argument("--package", required=True)
    p.add_argument("--source-db")
    p.add_argument("--policies")
    p.add_argument("--output")
    p.add_argument("--credential-env")
    p.add_argument("--credential-file")
    p.add_argument("--original-attempt")
    p.add_argument("--accept-unknown-prior-execution", action="store_true")
    p.add_argument("--accept-duplicate-charge", action="store_true")
    p.add_argument("--accept-store-true", action="store_true")
    p.add_argument("--authorize-paid-post", action="store_true")
    p.add_argument("--authorize-same-id-query", action="store_true")
    a = p.parse_args()
    network = a.command.startswith(("submit-", "query-", "recover-"))
    if not network and (
        a.credential_env or a.credential_file or a.authorize_paid_post or a.authorize_same_id_query
    ):
        p.error(
            "Preparation/read-only commands do not accept credentials or model execution authorization"
        )
    try:
        if a.command == "recover-p09":
            if not a.authorize_paid_post or not (
                a.accept_unknown_prior_execution
                and a.accept_duplicate_charge
                and a.accept_store_true
            ):
                raise ValueError("Separate explicit P09 retry authorization and all risks required")
            result = recover_p09(
                a.db,
                a.package,
                a.original_attempt,
                acknowledgements=RECOVERY_ACKS,
                credential_env=a.credential_env,
                credential_file=a.credential_file,
            )
        elif a.command == "prepare":
            if not a.source_db or not a.policies:
                raise ValueError("Explicit original source DB and versioned policies required")
            result = prepare(a.source_db, a.db, a.policies, a.package)
        elif a.command == "assemble-p10":
            if not a.output:
                raise ValueError("Explicit output directory required for conditional P10 assembly")
            result = assemble_p10(a.db, a.package, a.output)
        elif a.command == "inspect":
            with ReadOnlyStore(a.db) as store:
                frozen, g = validate_package(store, a.package)
                result = {
                    "preparation_sha256": digest(frozen),
                    "review_records": g.snapshot(frozen["run_id"]),
                    "model_requests": 0,
                }
        else:
            if a.command.startswith("submit-") and not a.authorize_paid_post:
                raise ValueError("Separate explicit one-POST paid authorization required")
            if a.command.startswith("query-") and not a.authorize_same_id_query:
                raise ValueError("Explicit same-saved-ID query authorization required")
            result = operate(
                a.db,
                a.package,
                "P09" if a.command.endswith("p09") else "P10",
                query=a.command.startswith("query-"),
                credential_env=a.credential_env,
                credential_file=a.credential_file,
            )
    except (ValueError, KeyError, OSError, sqlite3.Error):
        p.exit(
            2,
            "Trial preflight/gate not satisfied; no implicit resend or fallback. Inspect saved facts/policy/binding; no secret details printed.\n",
        )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
