"""Narrow P08 scheduling over saved P07/P05, existing M15 and immutable Results."""

import json
import re

from .background import IDLE, BackgroundService
from .contracts import ModuleResult
from .generation_ops import MODES, PROMPT, PROMPT_VERSION, SYSTEM, USER_FIELDS, parse_candidate
from .scheduler import Registry, Scheduler
from .store import encode

MODULE = "generation.P08"


def generation_route(output):
    return (
        "awaiting_candidate_ethics"
        if output["generation_status"] == "generated"
        else "generation_problem"
    )


class GenerationService:
    def __init__(self, store, adapter=None):
        self.store, self.adapter = store, adapter
        self.background = BackgroundService(store)

    def config(self):
        return (
            self.adapter.public_config() if self.adapter else {"execution_mode": "not_configured"}
        )

    def clear_calls(self, run_id, exclude_task=None):
        unresolved = self.store.rows(
            """SELECT p.id FROM attempts p JOIN tasks t ON t.id=p.task_id
            WHERE t.run_id=? AND (? IS NULL OR t.id!=?) AND p.status IN ('in_flight','uncertain')
            AND NOT EXISTS (SELECT 1 FROM attempts n WHERE n.task_id=p.task_id
                AND n.call_key=p.call_key AND n.ordinal>p.ordinal)""",
            (run_id, exclude_task, exclude_task),
        )
        if unresolved:
            raise ValueError(
                "Unresolved external call requires explicit recovery before generation"
            )

    def ready_input(self, run_id, request):
        run = self.background.literature.passed_goal(run_id)
        goal = self.background.goal(run_id)
        seed = self.background.seed(run_id, request["seed_id"])
        ready = self.background.action(run_id, request["readiness_ref"], "P07")
        packet = self.background.action(run_id, request["packet_ref"], "P05")
        binding = {"run_id": run_id, "goal_ref": run["goal_context_ref"], "seed_id": seed["id"]}
        if (
            ready["task_status"] != "succeeded"
            or packet["task_status"] != "succeeded"
            or ready["seed_id"] != seed["id"]
            or packet["seed_id"] != seed["id"]
            or ready["request"]["packet_ref"] != packet["request_id"]
            or ready["result"]["binding"] != binding
            or packet["result"]["binding"] != binding
            or ready["result"]["artifact"]["decision"] != "ready"
            or ready["input"]["goal_context"] != goal
            or ready["input"]["packet"] != packet["result"]["artifact"]
            or packet["result"]["artifact"]["mode"] != "SEED_PACKET"
        ):
            raise ValueError("Completed ready must bind this Run/Goal/seed and exact frozen packet")
        seed_brief = {
            k: seed[k]
            for k in ("id", "kind", "question", "unresolved_relationship", "known_anchor_refs")
        }
        if ready["input"]["seed_brief"] != seed_brief:
            raise ValueError("Readiness seed input mismatch")
        payload = {
            "goal_context": ready["input"]["goal_context"],
            "seed_brief": ready["input"]["seed_brief"],
            "readiness_record": ready["result"]["artifact"],
            "actual_frozen_seed_background_packet": ready["input"]["packet"],
            "mode": request["mode"],
            "candidate_id_from_caller": request["candidate_id"],
        }
        assert set(payload) == USER_FIELDS
        return payload, binding

    @staticmethod
    def messages(payload, version=PROMPT_VERSION):
        if version != PROMPT_VERSION:
            raise ValueError("Unknown fixed P08 prompt version")
        return [
            {"role": "system", "content": SYSTEM},
            {"role": "developer", "content": PROMPT},
            {"role": "user", "content": encode(payload)},
        ]

    def submit(self, run_id, request_id, request):
        if (
            not isinstance(request_id, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", request_id)
            or not isinstance(request, dict)
            or set(request) != {"seed_id", "readiness_ref", "packet_ref", "mode", "candidate_id"}
            or request["mode"] not in MODES
            or not isinstance(request["candidate_id"], str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}", request["candidate_id"])
        ):
            raise ValueError(
                "Explicit P08 references, caller identity and supported single-call mode required"
            )
        old = self.store.rows("SELECT * FROM generation_actions WHERE request_id=?", (request_id,))
        if old:
            if old[0]["run_id"] != run_id or old[0]["request"] != encode(request):
                raise ValueError("Request identity reused with different input")
            return old[0]
        if self.store.rows(
            "SELECT request_id FROM generation_actions WHERE candidate_id=?",
            (request["candidate_id"],),
        ):
            raise ValueError(
                "Candidate identity already reserved; modifications require a new identity"
            )
        payload, binding = self.ready_input(run_id, request)
        run = self.store.run(run_id)
        if run["status"] not in IDLE | {"awaiting_candidate_ethics", "generation_problem"}:
            raise ValueError("Run has an unfinished or blocked action")
        self.clear_calls(run_id)
        config = self.config()
        if self.adapter:
            self.adapter.preflight({"input": payload, "config": config})
        with self.store.db:
            plan = json.loads(run["plan"])
            step = len(plan)
            plan.append(MODULE)
            self.store.db.execute(
                "UPDATE runs SET plan=?,status='ready' WHERE id=?", (encode(plan), run_id)
            )
            self.store._create_task(run_id, step, None)
            task = self.store.one("SELECT id FROM tasks WHERE run_id=? AND step=?", (run_id, step))
            self.store.db.execute(
                "INSERT INTO generation_actions VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    request_id,
                    run_id,
                    task["id"],
                    request["candidate_id"],
                    encode(request),
                    encode(payload),
                    encode(binding),
                    encode(config),
                    PROMPT_VERSION,
                ),
            )
        return self.store.one("SELECT * FROM generation_actions WHERE request_id=?", (request_id,))

    def execute(self, request_id, *, recover=False):
        action = self.store.one(
            "SELECT * FROM generation_actions WHERE request_id=?", (request_id,)
        )
        if (
            self.store.one("SELECT status FROM tasks WHERE id=?", (action["task_id"],))["status"]
            == "succeeded"
        ):
            return self.snapshot(action["run_id"])
        if json.loads(action["config"]) != self.config():
            raise ValueError("Recovery requires frozen model configuration/mode")
        self.clear_calls(action["run_id"], action["task_id"])
        if recover:
            self.store.recover(run_id=action["run_id"])
        if (
            self.store.one("SELECT status FROM tasks WHERE id=?", (action["task_id"],))["status"]
            == "ready"
        ):
            registry = Registry()
            registry.register(MODULE, self.perform)
            Scheduler(self.store, registry).step(action["run_id"])
        return self.snapshot(action["run_id"])

    def perform(self, inputs, calls):
        a = self.store.one("SELECT * FROM generation_actions WHERE task_id=?", (inputs.task_id,))
        payload, binding = self.ready_input(inputs.run_id, json.loads(a["request"]))
        if payload != json.loads(a["input"]) or binding != json.loads(a["binding"]):
            raise ValueError("Frozen generation input/provenance changed")
        config = json.loads(a["config"])
        base = {
            "binding": {
                **binding,
                **{
                    k: json.loads(a["request"])[k]
                    for k in ("packet_ref", "readiness_ref", "mode", "candidate_id")
                },
            },
            "prompt_version": a["prompt_version"],
            "model_config": config,
            "execution_mode": config["execution_mode"],
            "science_validated": False,
        }
        if not self.adapter or not self.adapter.configured:
            return ModuleResult({**base, "generation_status": "model_not_configured"})
        if config["execution_mode"] == "real_model" and not self.adapter.authorized:
            return ModuleResult({**base, "generation_status": "model_call_not_authorized"})
        messages = self.messages(payload, a["prompt_version"])
        actual = self.adapter.request(messages)
        request = {
            "operation": "P08",
            "prompt_version": a["prompt_version"],
            "messages": messages,
            "actual_request": actual,
            "model_config": config,
            "binding": base["binding"],
        }
        self.adapter.preflight(request)
        size = len(encode(actual).encode())
        if size > config["max_request_bytes"]:
            return ModuleResult(
                {
                    **base,
                    "generation_status": "capacity_exceeded",
                    "request_bytes": size,
                    "limit": config["max_request_bytes"],
                }
            )
        response = calls.execute("model", self.adapter.target, request, self.adapter)
        try:
            candidate = parse_candidate(self.adapter.text(response.output), payload)
        except (ValueError, TypeError, KeyError, IndexError):
            # Raw response stays in M15; don't copy provider text into diagnostic messages.
            return ModuleResult(
                {
                    **base,
                    "generation_status": "invalid_output",
                    "parse_error": "P08 response incomplete or candidate contract invalid; inspect saved raw response",
                }
            )
        return ModuleResult(
            {
                **base,
                "generation_status": "generated",
                "candidate": candidate,
                "candidate_status": "generated_pending_candidate_ethics_r0",
                "call_provenance": {
                    "task_id": inputs.task_id,
                    "request_id": a["request_id"],
                    "call_key": "model",
                    "attempt_id": self.store.one(
                        "SELECT id FROM attempts WHERE task_id=? AND call_key='model' ORDER BY ordinal DESC LIMIT 1",
                        (inputs.task_id,),
                    )["id"],
                },
            }
        )

    def actions(self, run_id):
        rows = self.store.rows(
            """SELECT a.*,t.status AS task_status,t.error,r.output FROM generation_actions a
            JOIN tasks t ON t.id=a.task_id LEFT JOIN results r ON r.task_id=a.task_id
            WHERE a.run_id=? ORDER BY t.step""",
            (run_id,),
        )
        for row in rows:
            for key in ("request", "input", "binding", "config", "error"):
                row[key] = json.loads(row[key]) if row[key] else None
            output = row.pop("output")
            row["result"] = json.loads(output) if output else None
            row["attempts"] = self.store.rows(
                "SELECT id,status,usage,error,previous_id,started_at,finished_at FROM attempts WHERE task_id=? ORDER BY ordinal",
                (row["task_id"],),
            )
        return rows

    def snapshot(self, run_id):
        self.store.run(run_id)
        choices = []
        for a in self.background.successful(run_id, "P07"):
            try:
                request = {
                    "seed_id": a["seed_id"],
                    "packet_ref": a["request"]["packet_ref"],
                    "readiness_ref": a["request_id"],
                    "mode": "DIRECT",
                    "candidate_id": "preview",
                }
                self.ready_input(run_id, request)
            except (KeyError, ValueError):
                continue
            choices.append(
                {
                    "seed_id": a["seed_id"],
                    "readiness_ref": a["request_id"],
                    "packet_ref": a["request"]["packet_ref"],
                    "allowed_specificity": a["result"]["artifact"]["allowed_specificity"],
                    "question": a["input"]["seed_brief"]["question"],
                }
            )
        reason = None
        try:
            self.clear_calls(run_id)
        except ValueError as exc:
            reason = str(exc)
        idle = self.store.run(run_id)["status"] in IDLE | {
            "awaiting_candidate_ethics",
            "generation_problem",
        }
        return {
            "can_submit": bool(choices) and idle and reason is None,
            "blocked_reason": reason
            if reason
            else (None if idle else "Run has an unfinished or blocked task"),
            "ready_records": choices,
            "actions": self.actions(run_id),
            "model_config": self.config(),
            "prompt_version": PROMPT_VERSION,
            "real_calls_authorized": bool(self.adapter and self.adapter.authorized),
            "science_validated": False,
        }
