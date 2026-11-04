"""DIRECT Chat -> Responses migration: preview, atomic reservation, scoped authority.

No HTTP or credential loading. Preview can operate on SQLite mode=ro; writes
are allowed only in confirm/authorize_execution against an already opened Store.
"""

import hashlib
import json
import re
import sqlite3
from pathlib import Path

from .generation import MODULE, GenerationService
from .reading_model import ENDPOINT as CHAT_ENDPOINT
from .reading_model import OpenAIChat
from .responses_model import OpenAIResponses
from .store import Store, encode, now

ACKS = {
    "old_calls_may_have_executed_and_charged",
    "accept_duplicate_execution_and_charge_risk",
    "accept_store_true_retention",
    "creation_is_not_paid_execution_authorization",
}
RISK = {
    "old_calls_may_have_executed_and_charged": True,
    "old_outcomes_and_costs_remain_unknown": True,
    "new_api_is_not_an_identical_request_retry": True,
    "new_store": True,
    "retention_notice": "Explicit store=true; standard provider retention at least 30 days subject to exceptions; project policy unverified",
    "no_send_during_migration": True,
    "paid_execution_authorized_by_migration": False,
}
FIELDS = {
    "source_task_id",
    "source_attempt_ids",
    "seed_id",
    "packet_ref",
    "readiness_ref",
    "request_id",
    "candidate_id",
}


def digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def profile(config):
    return {k: v for k, v in config.items() if k != "credential_configured"}


def existing(store, *, source=None, successor=None):
    # Historical real DBs may not yet have this additive table; GET/CLI never create it.
    if not store.rows(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='generation_migrations'"
    ):
        return None
    key, value = (
        ("source_task_id", source) if source is not None else ("successor_task_id", successor)
    )
    rows = store.rows(f"SELECT * FROM generation_migrations WHERE {key}=?", (value,))
    return rows[0] if rows else None


class MigrationService:
    def __init__(self, store, config):
        self.store = store
        self.adapter = OpenAIResponses(config)  # No key, no authorization, no fallback.
        self.generation = GenerationService(store)

    def preview(self, run_id, request):
        if not isinstance(request, dict) or set(request) != FIELDS:
            raise ValueError("Exact migration source, references and new identities required")
        for name in ("request_id", "candidate_id"):
            value = request[name]
            if not isinstance(value, str) or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_-]{7,99}", value
            ):
                raise ValueError("Explicit new request/candidate identities required")
        s = self.store
        source = s.one(
            "SELECT * FROM generation_actions WHERE task_id=?", (request["source_task_id"],)
        )
        task = s.one("SELECT * FROM tasks WHERE id=?", (source["task_id"],))
        old_request = json.loads(source["request"])
        if (
            source["run_id"] != run_id
            or task["run_id"] != run_id
            or task["module"] != MODULE
            or task["status"] != "blocked"
            or old_request["mode"] != "DIRECT"
            or any(request[k] != old_request[k] for k in ("seed_id", "packet_ref", "readiness_ref"))
        ):
            raise ValueError(
                "Migration must use the same Run/seed/ready/packet and blocked DIRECT Task"
            )
        if (
            request["candidate_id"] == source["candidate_id"]
            or request["request_id"] == source["request_id"]
        ):
            raise ValueError(
                "A distinct candidate and request identity must reference the original"
            )
        attempts = s.rows(
            "SELECT * FROM attempts WHERE task_id=? ORDER BY ordinal", (source["task_id"],)
        )
        if (
            len(attempts) != 2
            or request["source_attempt_ids"] != [a["id"] for a in attempts]
            or [a["ordinal"] for a in attempts] != [1, 2]
            or attempts[1]["previous_id"] != attempts[0]["id"]
            or any(a["status"] != "uncertain" or a["call_key"] != "model" for a in attempts)
            or s.rows("SELECT task_id FROM results WHERE task_id=?", (source["task_id"],))
        ):
            raise ValueError(
                "Exactly the two original linked uncertain model Attempts are required"
            )
        frozen = json.loads(source["input"])
        payload, binding = self.generation.ready_input(run_id, old_request)
        if frozen != payload or json.loads(source["binding"]) != binding:
            raise ValueError(
                "Original frozen scientific input/binding differs from saved ready/packet"
            )
        messages = self.generation.messages(frozen, source["prompt_version"])
        old_config = profile(json.loads(source["config"]))
        old_config.pop("execution_mode", None)
        if (
            old_config.get("endpoint") != CHAT_ENDPOINT
            or old_config.get("model") != "gpt-6.1-sol"
            or old_config.get("parameters") != self.adapter.config["parameters"]
        ):
            raise ValueError(
                "Only the explicit unchanged Sol/high/32768/JSON Chat profile can migrate"
            )
        old_actual = OpenAIChat(old_config, None).request(messages)
        for a in attempts:
            wire = json.loads(a["request"])
            if (
                a["target"] != "openai/chat/gpt-6.1-sol"
                or wire.get("actual_request") != old_actual
                or wire.get("messages") != messages
                or wire.get("prompt_version") != source["prompt_version"]
                or wire.get("operation") != "P08"
                or wire.get("binding")
                != {
                    **binding,
                    **{
                        k: old_request[k]
                        for k in ("packet_ref", "readiness_ref", "mode", "candidate_id")
                    },
                }
            ):
                raise ValueError("Original actual request/Prompt/scientific input mismatch")
        if attempts[0]["request"] != attempts[1]["request"]:
            raise ValueError("The two source frozen requests differ")
        new_input = {**frozen, "candidate_id_from_caller": request["candidate_id"]}
        new_request = {**old_request, "candidate_id": request["candidate_id"]}
        new_config = profile(self.adapter.public_config())
        new_messages = self.generation.messages(new_input, source["prompt_version"])
        actual = self.adapter.request(new_messages)
        if len(encode(actual).encode()) > new_config["max_request_bytes"]:
            raise ValueError("Full new request exceeds capacity; no input truncated")
        preview = {
            "version": "p08-chat-responses-migration-v1",
            "run_id": run_id,
            "request": request,
            "source_task": {
                k: task[k] for k in ("id", "run_id", "module", "step", "status", "error")
            },
            "source_request_id": source["request_id"],
            "source_task_sha256": digest(task),
            "source_action_sha256": digest(source),
            "source_attempts": [
                {
                    **{
                        k: a[k]
                        for k in (
                            "id",
                            "target",
                            "call_key",
                            "status",
                            "previous_id",
                            "ordinal",
                            "started_at",
                            "finished_at",
                        )
                    },
                    "error": json.loads(a["error"]) if a["error"] else None,
                    "usage": json.loads(a["usage"]),
                    "row_sha256": digest(a),
                    "frozen_request_sha256": hashlib.sha256(a["request"].encode()).hexdigest(),
                }
                for a in attempts
            ],
            "source_input_sha256": digest(frozen),
            "source_messages_sha256": digest(messages),
            "new_config": new_config,
            "new_config_sha256": digest(new_config),
            "new_input_sha256": digest(new_input),
            "new_messages_sha256": digest(new_messages),
            "prompt_version": source["prompt_version"],
            "science_input_equal_except_candidate_id": True,
            "system_developer_prompt_equal": True,
            "identity_relation": {
                "original_candidate_id": source["candidate_id"],
                "successor_candidate_id": request["candidate_id"],
                "relation": "new_execution_proposed_replacement_not_resolution",
            },
            "risk": RISK,
            "science_validated": False,
            "successor_action": {
                "request": new_request,
                "input": new_input,
                "binding": binding,
                "config": new_config,
                "prompt_version": source["prompt_version"],
            },
            "actual_submission": {
                "operation": "P08",
                "prompt_version": source["prompt_version"],
                "messages": new_messages,
                "actual_request": actual,
                "model_config": new_config,
                "binding": {**binding, **new_request},
            },
        }
        return {**preview, "preview_hash": digest(preview)}

    def confirm(self, run_id, request, preview_hash, acknowledgements):
        if (
            not isinstance(acknowledgements, dict)
            or set(acknowledgements) != ACKS
            or not all(v is True for v in acknowledgements.values())
        ):
            raise ValueError(
                "Explicit duplicate charge, storage and no-paid-authorization acknowledgements required"
            )
        s = self.store
        with s.db:
            # Reserve against the current facts, never trust an imported client preview.
            s.db.execute("BEGIN IMMEDIATE")
            preview = self.preview(run_id, request)
            if preview["preview_hash"] != preview_hash:
                raise ValueError("Stale or changed migration preview; nothing reserved")
            old = existing(s, source=request["source_task_id"])
            if old:
                if old["preview_hash"] != preview_hash or json.loads(old["preview"]) != preview:
                    raise ValueError(
                        "Source already has a different successor; repeated migration forbidden"
                    )
                return self.record(old)
            self.generation.clear_calls_for_migration(run_id, request["source_attempt_ids"])
            run = s.run(run_id)
            if run["status"] != "blocked" or s.tasks(run_id)[-1]["id"] != request["source_task_id"]:
                raise ValueError("Only this blocked latest source Task can acquire a successor")
            if s.rows(
                "SELECT request_id FROM generation_actions WHERE request_id=? OR candidate_id=?",
                (request["request_id"], request["candidate_id"]),
            ):
                raise ValueError("Successor request/candidate identity already reserved")
            plan = json.loads(run["plan"])
            step = len(plan)
            plan.append(MODULE)
            s.db.execute("UPDATE runs SET plan=?,status='ready' WHERE id=?", (encode(plan), run_id))
            s._create_task(run_id, step, None)
            task_id = s.one("SELECT id FROM tasks WHERE run_id=? AND step=?", (run_id, step))["id"]
            a = preview["successor_action"]
            s.db.execute(
                "INSERT INTO generation_actions VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    request["request_id"],
                    run_id,
                    task_id,
                    request["candidate_id"],
                    encode(a["request"]),
                    encode(a["input"]),
                    encode(a["binding"]),
                    encode(a["config"]),
                    a["prompt_version"],
                ),
            )
            migration_id = "migration-" + preview_hash
            s.db.execute(
                "INSERT INTO generation_migrations VALUES(?,?,?,?,?,?,?,?,NULL)",
                (
                    migration_id,
                    run_id,
                    request["source_task_id"],
                    task_id,
                    encode(preview),
                    preview_hash,
                    encode(acknowledgements),
                    now(),
                ),
            )
            s.fact(
                task_id,
                "migration_reserved_without_send",
                {
                    "migration_id": migration_id,
                    "source_task_id": request["source_task_id"],
                    "source_attempt_ids": request["source_attempt_ids"],
                    "preview_hash": preview_hash,
                    "paid_execution_authorized": False,
                },
            )
            return self.record(existing(s, successor=task_id))

    @staticmethod
    def record(row):
        row = dict(row)
        for key in ("preview", "confirmation", "execution_authorization"):
            row[key] = json.loads(row[key]) if row[key] else None
        return row


def scoped_exemptions(store, run_id, successor):
    """Validate the persisted scope and unchanged historical rows on every continuation."""
    migration = existing(store, successor=successor)
    if not migration:
        return set()
    preview = json.loads(migration["preview"])
    if migration["preview_hash"] != digest(
        {k: v for k, v in preview.items() if k != "preview_hash"}
    ):
        raise ValueError("Migration record hash mismatch")
    if (
        migration["run_id"] != run_id
        or migration["source_task_id"] != preview["request"]["source_task_id"]
    ):
        raise ValueError("Migration Run/source scope mismatch")
    source_task = store.one("SELECT * FROM tasks WHERE id=?", (migration["source_task_id"],))
    source_action = store.one(
        "SELECT * FROM generation_actions WHERE task_id=?", (source_task["id"],)
    )
    if (
        digest(source_task) != preview["source_task_sha256"]
        or digest(source_action) != preview["source_action_sha256"]
    ):
        raise ValueError("Historical Task/action changed; migration scope no longer valid")
    successor_action = store.one("SELECT * FROM generation_actions WHERE task_id=?", (successor,))
    a = preview["successor_action"]
    if (
        successor_action["run_id"] != run_id
        or successor_action["request_id"] != preview["request"]["request_id"]
        or successor_action["candidate_id"] != preview["request"]["candidate_id"]
        or any(
            json.loads(successor_action[k]) != a[k]
            for k in ("request", "input", "binding", "config")
        )
        or successor_action["prompt_version"] != a["prompt_version"]
    ):
        raise ValueError("Successor identity/frozen content changed")
    for record in preview["source_attempts"]:
        row = store.one("SELECT * FROM attempts WHERE id=?", (record["id"],))
        if digest(row) != record["row_sha256"] or row["task_id"] != source_task["id"]:
            raise ValueError("Historical Attempt changed; migration scope no longer valid")
    return set(preview["request"]["source_attempt_ids"])


def authorize_execution(generation, action, explicit):
    """Migration consent does not authorize a paid POST. Separate explicit operation required."""
    s = generation.store
    row = existing(s, successor=action["task_id"])
    if not row:
        return
    scoped_exemptions(s, action["run_id"], action["task_id"])
    if row["execution_authorization"]:
        return
    if (
        explicit is not True
        or not generation.adapter
        or not generation.adapter.configured
        or not generation.adapter.authorized
    ):
        raise ValueError(
            "Migration created no paid authorization; separately authorize this successor execution"
        )
    with s.db:
        authorization = {
            "task_id": action["task_id"],
            "migration_id": row["id"],
            "config_sha256": digest(json.loads(action["config"])),
            "accept_paid_execution_risk": True,
            "at": now(),
        }
        s.db.execute(
            "UPDATE generation_migrations SET execution_authorization=? WHERE id=?",
            (encode(authorization), row["id"]),
        )
        s.fact(action["task_id"], "migration_successor_execution_authorized", authorization)


class ReadOnlyStore(Store):
    """Only for offline preview/export; no Store initialization, lock file or migrations."""

    def __init__(self, path):
        self.db = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA query_only=ON")
        if self.db.execute("PRAGMA application_id").fetchone()[0] != 0x43534E31:
            self.db.close()
            raise ValueError("Not a Co-Scientist Next database")

    def close(self):
        self.db.close()
