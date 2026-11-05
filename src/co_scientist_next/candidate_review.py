"""Two explicit candidate review operations; no R1, retrieval or automatic model calls."""

import json
import re

from .candidate_review_ops import (
    SYSTEM,
    VERSION,
    decision_policy,
    digest,
    parse_review,
    policy,
    prompt,
)
from .contracts import ModuleResult
from .generation import GenerationService
from .generation_migration import profile, scoped_exemptions
from .generation_ops import parse_candidate
from .remote_generation import RemoteP08, remote_snapshot
from .scheduler import Registry, Scheduler
from .store import encode


def review_route(output):
    if output["review_status"] != "completed":
        return "candidate_review_problem"
    artifact = output["artifact"]
    if output["operation"] == "P09":
        return (
            "awaiting_r0"
            if artifact["decision_per_approved_policy"] == "pass"
            else (
                "candidate_ethics_stopped"
                if output["decision_route"] == "stop"
                else "candidate_ethics_hold"
            )
        )
    return "awaiting_r1" if artifact["disposition"] == "proceed_to_R1" else "candidate_r0_blocked"


class CandidateReviewService:
    def __init__(self, store, adapter=None, *, development=False):
        self.store, self.adapter, self.development = store, adapter, development

    def config(self):
        return (
            self.adapter.public_config() if self.adapter else {"execution_mode": "not_configured"}
        )

    def candidate(self, run_id, generation_ref):
        s = self.store
        a = s.one(
            "SELECT * FROM generation_actions WHERE request_id=? AND run_id=?",
            (generation_ref, run_id),
        )
        task = s.one("SELECT * FROM tasks WHERE id=?", (a["task_id"],))
        result = json.loads(
            s.one("SELECT output FROM results WHERE task_id=?", (a["task_id"],))["output"]
        )
        payload, binding = json.loads(a["input"]), json.loads(a["binding"])
        run = s.run(run_id)
        goal = json.loads(
            s.one(
                "SELECT content FROM goal_contexts WHERE id=? AND run_id=?",
                (run["goal_context_ref"], run_id),
            )["content"]
        )
        c = result.get("candidate")
        if (
            task["status"] != "succeeded"
            or result.get("generation_status") != "generated"
            or not c
            or c["candidate_id"] != a["candidate_id"]
            or payload["candidate_id_from_caller"] != c["candidate_id"]
            or binding["run_id"] != run_id
            or binding["goal_ref"] != run["goal_context_ref"]
            or payload["goal_context"] != goal
            or result["binding"]["candidate_id"] != c["candidate_id"]
            or result["binding"]["run_id"] != run_id
            or result["binding"]["goal_ref"] != run["goal_context_ref"]
            or json.loads(a["request"])["candidate_id"] != c["candidate_id"]
        ):
            raise ValueError("Saved candidate/Run/Goal binding invalid")
        parse_candidate(encode(c), payload)
        return a, c, goal, payload

    def ready_input(self, run_id, request):
        op = request["operation"]
        expected = (
            {"operation", "generation_ref", "policy", "intended_use", "decision_policy"}
            if op == "P09"
            else {"operation", "generation_ref", "policy", "ethics_ref"}
        )
        if op not in ("P09", "P10") or set(request) != expected:
            raise ValueError(
                "Exact P09/P10 references required; reviewer/expected/extra fields forbidden"
            )
        a, c, goal, generated = self.candidate(run_id, request["generation_ref"])
        pol = policy(request["policy"]) if request["policy"] is not None else None
        if self.store.rows(
            "SELECT id FROM execution_facts WHERE task_id=? AND kind='development_candidate_import'",
            (a["task_id"],),
        ) and (not self.development or pol and pol["mode"] != "development"):
            raise ValueError("Imported candidate fixture supports development review only")
        trial = self.store.rows(
            "SELECT id FROM execution_facts WHERE task_id=? AND kind='candidate_review_trial_prepared'",
            (a["task_id"],),
        )
        if trial and self.config().get("execution_mode") != "real_model":
            raise ValueError(
                "Prepared real-review trial requires a real-model execution profile, not a fixture"
            )
        if trial:
            detail = json.loads(
                self.store.one("SELECT detail FROM execution_facts WHERE id=?", (trial[0]["id"],))[
                    "detail"
                ]
            )
            frozen = detail["frozen"]
            expected = frozen["p09_request"] if op == "P09" else frozen["p10_request"]
            if (
                request != expected
                or digest(c) != frozen["candidate_sha256"]
                or digest(goal) != frozen["goal_sha256"]
                or digest(generated["actual_frozen_seed_background_packet"]["source_views"])
                != frozen["source_views_sha256"]
            ):
                raise ValueError("Prepared trial candidate/Goal/sources/policy/use changed")
            from .responses_model import OpenAIResponses

            if profile(self.config()) != profile(
                OpenAIResponses(frozen["model_config"]).public_config()
            ):
                raise ValueError("Prepared trial model configuration changed; no fallback")
        if pol and pol["mode"] == "development" and not self.development:
            raise ValueError("Development policy requires explicit development review mode")
        binding = {
            "run_id": run_id,
            "goal_ref": json.loads(a["binding"])["goal_ref"],
            "generation_ref": a["request_id"],
            "candidate_id": c["candidate_id"],
            "candidate_sha256": digest(c),
            "policy_sha256": digest(pol),
        }
        if op == "P09":
            if not isinstance(request["intended_use"], str) or not request["intended_use"].strip():
                raise ValueError("Actual intended use must be explicitly provided")
            decisions = (
                decision_policy(request["decision_policy"])
                if request["decision_policy"] is not None
                else None
            )
            goal_ethics = GenerationService(self.store).background.literature.passed_goal(run_id)
            # Only the saved screening artifact, never a caller's claim of PASS.
            from .goal import SCREEN

            goal_task = self.store.one(
                "SELECT id FROM tasks WHERE run_id=? AND module=?", (run_id, SCREEN)
            )
            goal_record = json.loads(
                self.store.one("SELECT output FROM results WHERE task_id=?", (goal_task["id"],))[
                    "output"
                ]
            )
            assert goal_ethics["id"] == run_id
            payload = {
                "goal_context": goal,
                "fixed_candidate": c,
                "goal_ethics_record": goal_record,
                "intended_use": request["intended_use"],
                "approved_policy_id": {k: pol[k] for k in ("id", "version", "mode")}
                if pol
                else None,
                "approved_policy_text": pol["text"] if pol else None,
                "candidate_ethics_decision_policy": decisions,
            }
            binding.update(
                intended_use_sha256=digest(request["intended_use"]),
                decision_policy_sha256=digest(decisions),
            )
        else:
            passed = self.action(run_id, request["ethics_ref"])
            out = passed["result"]
            if (
                passed["operation"] != "P09"
                or passed["task_status"] != "succeeded"
                or not out
                or out["review_status"] != "completed"
                or out["artifact"]["decision_per_approved_policy"] != "pass"
                or passed["binding"]["candidate_sha256"] != digest(c)
                or passed["binding"]["goal_ref"] != binding["goal_ref"]
                or passed["binding"]["generation_ref"] != a["request_id"]
                or out["binding"] != passed["binding"]
                or not passed["request"]["policy"]
            ):
                raise ValueError(
                    "R0 requires valid completed same-candidate/Goal/Run/content Ethics pass"
                )
            if pol and pol["mode"] == "production" and out["development"]:
                raise ValueError("Development Ethics pass cannot authorize production R0")
            # Reparse and reassemble the saved pass, including policy/use/config identity.
            old_payload, old_binding = self.ready_input(run_id, passed["request"])
            if old_payload != passed["input"] or old_binding != passed["binding"]:
                raise ValueError("Frozen Ethics policy/use/input changed")
            parse_review(encode(out["artifact"]), "P09", old_payload, passed["request"])
            if trial or self.config().get("execution_mode") == "real_model":
                self.require_real_ethics(passed)
            views = generated["actual_frozen_seed_background_packet"]["source_views"]
            if not views or any(
                not isinstance(v.get("text"), str)
                or not v["text"]
                or v.get("access") not in ("abstract", "full_text")
                or v.get("source_origin", "provider_original") != "provider_original"
                or "assistant" in v.get("representation", "").lower()
                or not v.get("locator")
                or not v.get("source_citation")
                for v in views
            ):
                raise ValueError(
                    "Actual source text and access views required, not IDs/cards/paraphrases"
                )
            payload = {
                "goal_context": goal,
                "fixed_candidate": c,
                "passed_candidate_ethics_record": out,
                "actual_visible_source_views": views,
                "r0_policy_version": pol,
            }
            binding.update(
                ethics_ref=passed["request_id"],
                ethics_result_sha256=digest(out),
                intended_use_sha256=passed["binding"]["intended_use_sha256"],
            )
        return payload, binding

    def require_real_ethics(self, passed):
        """Nonproduction policy may be real-model; fixture PASS is never real provenance."""
        from .responses_model import OpenAIResponses

        out, cfg = passed["result"], passed["config"]
        if (
            cfg.get("execution_mode") != "real_model"
            or cfg.get("api_mode") != "responses_background_v1"
        ):
            raise ValueError("Real R0 requires real Responses P09, not fixture pass")
        jobs = self.store.rows(
            "SELECT * FROM remote_generations WHERE task_id=?", (passed["task_id"],)
        )
        if len(jobs) != 1 or jobs[0]["status"] != "completed":
            raise ValueError("Real P09 completed remote record required")
        job = jobs[0]
        submit = self.store.one(
            "SELECT * FROM attempts WHERE id=? AND task_id=?",
            (job["submission_attempt_id"], passed["task_id"]),
        )
        latest = self.store.one(
            "SELECT * FROM attempts WHERE id=? AND task_id=?",
            (job["latest_attempt_id"], passed["task_id"]),
        )
        expected_messages = self.messages(passed["input"], passed["prompt_version"])
        adapter = OpenAIResponses(
            {
                k: v
                for k, v in cfg.items()
                if k not in ("execution_mode", "api_mode", "credential_configured")
            }
        )
        request = json.loads(submit["request"])
        provenance = out.get("call_provenance", {})
        response = json.loads(job["response"])
        if (
            submit["status"] != "succeeded"
            or latest["status"] != "succeeded"
            or submit["call_key"] != "responses.submit"
            or submit["target"] != adapter.target + "/create"
            or latest["target"] not in (adapter.target + "/create", adapter.target + "/retrieve")
            or request.get("operation") != "P09"
            or request.get("actual_request") != adapter.request(expected_messages)
            or request.get("messages") != expected_messages
            or request.get("model_config") != cfg
            or request.get("binding") != {**passed["binding"], **passed["request"]}
            or provenance.get("task_id") != passed["task_id"]
            or provenance.get("submission_attempt_id") != submit["id"]
            or provenance.get("attempt_id") != latest["id"]
            or out.get("remote_response_id") != job["response_id"]
            or json.loads(latest["response"]) != response
            or OpenAIResponses.envelope(response)["id"] != job["response_id"]
            or json.loads(OpenAIResponses.text(response)) != out["artifact"]
        ):
            raise ValueError(
                "Real P09 response/Attempt/input binding invalid; fixture cannot be promoted"
            )

    @staticmethod
    def messages(payload, version):
        operation = "P09" if "goal_ethics_record" in payload else "P10"
        if version != VERSION:
            raise ValueError("Unknown fixed review Prompt version")
        return [
            {"role": "system", "content": SYSTEM},
            {"role": "developer", "content": prompt(operation)},
            {"role": "user", "content": encode(payload)},
        ]

    def clear_calls(self, run_id, exclude_task=None):
        s = self.store
        action = s.one("SELECT * FROM candidate_review_actions WHERE task_id=?", (exclude_task,))
        generation = s.one(
            "SELECT task_id FROM generation_actions WHERE request_id=? AND run_id=?",
            (action["generation_ref"], run_id),
        )
        # Only this successfully generated candidate's validated migration lineage;
        # no global waiver and no mutation of the old uncertain records.
        allowed = scoped_exemptions(s, run_id, generation["task_id"])
        unresolved = s.rows(
            "SELECT p.id FROM attempts p JOIN tasks t ON t.id=p.task_id WHERE t.run_id=? AND t.id!=? AND p.status IN ('in_flight','uncertain') AND NOT EXISTS (SELECT 1 FROM attempts n WHERE n.task_id=p.task_id AND n.call_key=p.call_key AND n.ordinal>p.ordinal)",
            (run_id, exclude_task),
        )
        if any(p["id"] not in allowed for p in unresolved):
            raise ValueError("Other unresolved external call remains blocked")

    def trial_record(self, generation_ref, run_id):
        return self.store.rows(
            "SELECT f.detail FROM execution_facts f JOIN generation_actions a ON a.task_id=f.task_id WHERE a.request_id=? AND a.run_id=? AND f.kind='candidate_review_trial_prepared'",
            (generation_ref, run_id),
        )

    def config_matches(self, action):
        if self.trial_record(action["generation_ref"], action["run_id"]):
            return profile(json.loads(action["config"])) == profile(self.config())
        return json.loads(action["config"]) == self.config()

    def submit(self, run_id, request_id, request):
        if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", request_id):
            raise ValueError("Explicit review request identity required")
        payload, binding = self.ready_input(run_id, request)
        s = self.store
        trial = self.trial_record(request["generation_ref"], run_id)
        if (
            trial
            and request_id
            != json.loads(trial[0]["detail"])["frozen"]["request_ids"][request["operation"]]
        ):
            raise ValueError("Prepared trial reserves only one execution identity per operation")
        old = s.rows("SELECT * FROM candidate_review_actions WHERE request_id=?", (request_id,))
        if old:
            if (
                old[0]["run_id"] != run_id
                or old[0]["request"] != encode(request)
                or old[0]["input"] != encode(payload)
                or old[0]["binding"] != encode(binding)
            ):
                raise ValueError(
                    "Review identity reused for changed Run/candidate/content/policy/use"
                )
            return old[0]
        # Refuse to schedule over another unfinished task, independently of Run labels.
        if s.rows(
            "SELECT id FROM tasks WHERE run_id=? AND status IN ('ready','running','waiting_remote')",
            (run_id,),
        ):
            raise ValueError("Another unfinished task must be resolved first")
        if (
            request["policy"]
            and request["policy"]["mode"] == "production"
            and (not self.adapter or self.adapter.execution_mode != "real_model")
        ):
            raise ValueError("Development adapter cannot produce production decisions")
        with s.db:
            plan = json.loads(s.run(run_id)["plan"])
            step = len(plan)
            plan.append("candidate_review." + request["operation"])
            s.db.execute("UPDATE runs SET plan=?,status='ready' WHERE id=?", (encode(plan), run_id))
            s._create_task(run_id, step, None)
            task_id = s.one("SELECT id FROM tasks WHERE run_id=? AND step=?", (run_id, step))["id"]
            s.db.execute(
                "INSERT INTO candidate_review_actions VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    request_id,
                    run_id,
                    task_id,
                    request["operation"],
                    request["generation_ref"],
                    encode(request),
                    encode(payload),
                    encode(binding),
                    encode(profile(self.config()) if trial else self.config()),
                    VERSION,
                ),
            )
            self.clear_calls(run_id, task_id)
        return s.one("SELECT * FROM candidate_review_actions WHERE request_id=?", (request_id,))

    def base_result(self, a, status):
        request = json.loads(a["request"])
        return {
            "operation": a["operation"],
            "review_status": status,
            "binding": json.loads(a["binding"]),
            "prompt_version": a["prompt_version"],
            "model_config": json.loads(a["config"]),
            "development": bool(request["policy"] and request["policy"]["mode"] == "development"),
            "policy_mode": request["policy"]["mode"] if request["policy"] else "not_configured",
            "execution_mode": json.loads(a["config"])["execution_mode"],
            "science_validated": False,
        }

    def finish_output(self, a, raw):
        try:
            parsed = parse_review(
                raw, a["operation"], json.loads(a["input"]), json.loads(a["request"])
            )
        except (ValueError, TypeError, KeyError, IndexError):
            return {
                **self.base_result(a, "invalid_output"),
                "parse_error": "Review contract/provenance invalid; inspect saved response. No ethical/scientific disposition applied.",
            }
        result = {**self.base_result(a, "completed"), "artifact": parsed}
        if a["operation"] == "P09":
            result["decision_route"] = json.loads(a["input"])["candidate_ethics_decision_policy"][
                "routes"
            ][parsed["decision_per_approved_policy"]]
        return result

    def perform(self, inputs, calls):
        a = self.store.one(
            "SELECT * FROM candidate_review_actions WHERE task_id=?", (inputs.task_id,)
        )
        payload = json.loads(a["input"])
        if not json.loads(a["request"])["policy"] or (
            a["operation"] == "P09" and not payload["candidate_ethics_decision_policy"]
        ):
            return ModuleResult(self.base_result(a, "policy_not_configured"))
        if not self.adapter or not self.adapter.configured:
            return ModuleResult(self.base_result(a, "model_not_configured"))
        messages = self.messages(payload, a["prompt_version"])
        actual = self.adapter.request(messages)
        request = {
            "operation": a["operation"],
            "messages": messages,
            "actual_request": actual,
            "binding": json.loads(a["binding"]),
            "model_config": json.loads(a["config"]),
            "prompt_version": a["prompt_version"],
        }
        self.adapter.preflight(request)
        if len(encode(actual).encode()) > self.config()["max_request_bytes"]:
            return ModuleResult(self.base_result(a, "capacity_exceeded"))
        response = calls.execute("review.model", self.adapter.target, request, self.adapter)
        try:
            raw = self.adapter.text(response.output)
        except (ValueError, TypeError, KeyError):
            raw = ""
        result = self.finish_output(a, raw)
        result["call_provenance"] = {"task_id": a["task_id"], "request_id": a["request_id"]}
        return ModuleResult(result)

    def execute(self, request_id, *, recover=False):
        s = self.store
        a = s.one("SELECT * FROM candidate_review_actions WHERE request_id=?", (request_id,))
        payload, binding = self.ready_input(a["run_id"], json.loads(a["request"]))
        if payload != json.loads(a["input"]) or binding != json.loads(a["binding"]):
            raise ValueError("Frozen review input/content/Goal/policy/use changed")
        task = s.one("SELECT * FROM tasks WHERE id=?", (a["task_id"],))
        if task["status"] == "succeeded":
            return self.snapshot(a["run_id"])
        if not self.config_matches(a):
            raise ValueError("Frozen review model configuration changed")
        self.clear_calls(a["run_id"], a["task_id"])
        if (
            getattr(self.adapter, "background_responses", False)
            and json.loads(a["request"])["policy"]
            and (a["operation"] != "P09" or payload["candidate_ethics_decision_policy"])
        ):
            return RemoteReview(self).execute(a, recover=recover)
        if recover:
            s.recover(run_id=a["run_id"])
        if s.one("SELECT status FROM tasks WHERE id=?", (a["task_id"],))["status"] == "ready":
            registry = Registry()
            registry.register("candidate_review." + a["operation"], self.perform)
            Scheduler(s, registry).step(a["run_id"])
        return self.snapshot(a["run_id"])

    def query_remote(self, request_id):
        a = self.store.one(
            "SELECT * FROM candidate_review_actions WHERE request_id=?", (request_id,)
        )
        if not getattr(self.adapter, "background_responses", False):
            raise ValueError("Explicit frozen Responses configuration required")
        return RemoteReview(self).execute(a, query=True)

    def actions(self, run_id):
        rows = self.store.rows(
            "SELECT a.*,t.status AS task_status,t.error,r.output FROM candidate_review_actions a JOIN tasks t ON t.id=a.task_id LEFT JOIN results r ON r.task_id=a.task_id WHERE a.run_id=? ORDER BY t.step",
            (run_id,),
        )
        for a in rows:
            for key in ("request", "input", "binding", "config", "error"):
                a[key] = json.loads(a[key]) if a[key] else None
            out = a.pop("output")
            a["result"] = json.loads(out) if out else None
            a["remote"] = remote_snapshot(self.store, a["task_id"])
            a["attempts"] = self.store.rows(
                "SELECT id,status,usage,error,previous_id FROM attempts WHERE task_id=? ORDER BY started_at,ordinal",
                (a["task_id"],),
            )
        return rows

    def action(self, run_id, request_id):
        for action in self.actions(run_id):
            if action["request_id"] == request_id:
                return action
        raise ValueError("Review record not in this Run")

    def snapshot(self, run_id):
        self.store.run(run_id)
        return {
            "actions": self.actions(run_id),
            "model_config": self.config(),
            "prompt_version": VERSION,
            "development": self.development,
            "development_policies_allowed": self.development,
            "prepared_trial": [
                {
                    "preparation_sha256": json.loads(f["detail"])["preparation_sha256"],
                    "candidate_id": json.loads(f["detail"])["frozen"]["candidate_id"],
                    "generation_ref": json.loads(f["detail"])["frozen"]["generation_ref"],
                    "request_ids": json.loads(f["detail"])["frozen"]["request_ids"],
                }
                for f in self.store.rows(
                    "SELECT f.detail FROM execution_facts f JOIN tasks t ON t.id=f.task_id WHERE t.run_id=? AND f.kind='candidate_review_trial_prepared'",
                    (run_id,),
                )
            ],
            "real_calls_authorized": bool(self.adapter and self.adapter.authorized),
            "science_validated": False,
        }


class RemoteReview(RemoteP08):
    """Reuse only the existing durable-ID transport, with stage-specific result application."""

    def finish(self, a, job):
        from .responses_model import OpenAIResponses

        try:
            raw = OpenAIResponses.text(json.loads(job["response"]))
        except (ValueError, TypeError, KeyError):
            raw = ""
        result = self.g.finish_output(a, raw)
        result.update(
            remote_response_id=job["response_id"],
            remote_status=job["status"],
            call_provenance={
                "task_id": a["task_id"],
                "request_id": a["request_id"],
                "submission_attempt_id": job["submission_attempt_id"],
                "attempt_id": job["latest_attempt_id"],
            },
        )
        with self.store.db:
            self.store.db.execute(
                "UPDATE tasks SET status='running',error=NULL WHERE id=?", (a["task_id"],)
            )
        self.store.submit_result(a["task_id"], result, stop_status=review_route(result))
