"""Explicit P03–P07 slice using existing Run/Task/Attempt/Result facts."""

import hashlib
import json
import re

from .background_ops import (
    PROMPTS,
    SYSTEM,
    operation_prompt,
    operation_prompt_version,
    parse_output,
    text,
)
from .contracts import ModuleResult
from .literature_runtime import LiteratureService
from .scheduler import Registry, Scheduler
from .store import encode, identity, now

CAPABILITIES = {
    "provider": "Europe PMC",
    "search": "explicit query, cursor, metadata",
    "fetch": "abstract/OA XML where available",
    "images": False,
    "supplements": False,
}
IDLE = {
    "awaiting_background",
    "literature_acquired_unread",
    "literature_incomplete",
    "literature_failed",
    "background_saved",
    "background_problem",
    "awaiting_generation",
    "background_no_progress",
}
OPERATIONS = tuple(PROMPTS)


def digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def background_route(output):
    if output["background_status"] == "saved":
        return (
            "awaiting_generation"
            if output.get("artifact", {}).get("decision") == "ready"
            else "background_saved"
        )
    return (
        "background_no_progress"
        if output["background_status"] == "no_progress"
        else "background_problem"
    )


class BackgroundService:
    def __init__(self, store, adapter=None):
        self.store, self.adapter = store, adapter
        self.literature = LiteratureService(store)

    def config(self):
        return (
            self.adapter.public_config() if self.adapter else {"execution_mode": "not_configured"}
        )

    def actions(self, run_id):
        rows = self.store.rows(
            """SELECT a.*,t.status AS task_status,t.error,r.output FROM background_actions a
            JOIN tasks t ON t.id=a.task_id LEFT JOIN results r ON r.task_id=a.task_id WHERE a.run_id=? ORDER BY t.step""",
            (run_id,),
        )
        for row in rows:
            for k in ("request", "input", "config"):
                row[k] = json.loads(row[k])
            output = row.pop("output")
            row["result"] = json.loads(output) if output else None
            row["error"] = json.loads(row["error"]) if row["error"] else None
            row["attempts"] = self.store.rows(
                "SELECT id,status,usage,started_at,finished_at FROM attempts WHERE task_id=? ORDER BY ordinal",
                (row["task_id"],),
            )
        return rows

    def successful(self, run_id, operation=None):
        return [
            a
            for a in self.actions(run_id)
            if (operation is None or a["operation"] == operation)
            and (a.get("result") or {}).get("background_status") == "saved"
        ]

    def action(self, run_id, ref, operation=None):
        matches = [a for a in self.successful(run_id, operation) if a["request_id"] == ref]
        if len(matches) != 1:
            raise ValueError("Artifact does not belong to this Run/operation or is not completed")
        return matches[0]

    def seeds(self, run_id):
        return [
            seed
            for a in self.successful(run_id)
            if a["operation"].startswith("P06")
            for seed in a["result"]["artifact"]["seeds"]
        ]

    def seed(self, run_id, seed_id):
        matches = [s for s in self.seeds(run_id) if s["id"] == seed_id]
        if len(matches) != 1:
            raise ValueError("Seed is not bound to this Run and fixed Goal")
        return matches[0]

    def goal(self, run_id):
        run = self.literature.passed_goal(run_id)
        return json.loads(
            self.store.one(
                "SELECT content FROM goal_contexts WHERE id=?", (run["goal_context_ref"],)
            )["content"]
        )

    def views(self, run_id):
        return [
            json.loads(r["content"])
            for r in self.store.rows(
                "SELECT content FROM material_views WHERE run_id=? ORDER BY created_at", (run_id,)
            )
        ]

    def create_view(
        self, run_id, acquisition_task_id, *, start=0, end=None, reason="", seed_id=None
    ):
        run = self.literature.passed_goal(run_id)
        if seed_id:
            self.seed(run_id, seed_id)
        entry = next(
            (a for a in self.literature.history(run_id) if a["task_id"] == acquisition_task_id),
            None,
        )
        result = (entry or {}).get("result") or {}
        acquired = result.get("acquisition", {})
        original = acquired.get("text")
        if (
            entry is None
            or entry["request"]["kind"] != "fetch"
            or not original
            or acquired.get("access") not in ("abstract", "full_text")
        ):
            raise ValueError(
                "Select actually obtained text from this Run, not metadata or reviewer data"
            )
        context = entry["request"].get("background_context") or {}
        if context.get("seed_id") and context["seed_id"] != seed_id:
            raise ValueError("Another seed's retrieved material cannot enter this view")
        end = len(original) if end is None else end
        if any(
            isinstance(v, bool) or not isinstance(v, int) for v in (start, end)
        ) or not 0 <= start < end <= len(original):
            raise ValueError("Explicit nonempty character range required")
        cropped = start != 0 or end != len(original)
        if cropped:
            text(reason)
        details = result["details"]
        meta = details.get("metadata", {})
        view_id = identity()
        view = {
            "id": view_id,
            "run_id": run_id,
            "goal_ref": run["goal_context_ref"],
            "seed_id": seed_id,
            "acquisition_task_id": acquisition_task_id,
            "source_ref": acquired["source"]["source_ref"],
            "source_version": str(meta.get("versionNumber") or "provider version unreported"),
            "locator": details.get("text_locator"),
            "access": acquired["access"],
            "representation": ("excerpt of " if cropped else "complete obtained ")
            + details.get("representation", "text"),
            "character_range": [start, end],
            "original_characters": len(original),
            "original_text_sha256": hashlib.sha256(original.encode()).hexdigest(),
            "selection_reason": reason or "Explicit complete obtained text selection",
            "cropped": cropped,
            "not_read_ranges": ([[0, start]] if start else [])
            + ([[end, len(original)]] if end < len(original) else []),
            "text": original[start:end],
            "images_seen": False,
            "supplements_seen": False,
            "access_limitations": acquired.get("limitation")
            or details.get("limitations")
            or "Only the obtained representation; no unseen text/figures/supplements",
            "source_citation": acquired["source"]["citation"],
        }
        with self.store.db:
            self.store.db.execute(
                "INSERT INTO material_views VALUES(?,?,?,?,?)",
                (view_id, run_id, acquisition_task_id, encode(view), now()),
            )
        return view

    def scoped_searches(self, run_id, seed_id=None):
        rows = []
        for a in self.literature.history(run_id):
            if a["request"]["kind"] != "search":
                continue
            context = a["request"].get("background_context") or {}
            if context.get("seed_id") not in (None, seed_id):
                continue
            # Do not send transport attempts/headers, raw unrelated metadata or sibling narratives.
            result = (a.get("result") or {}).get("acquisition")
            rows.append(
                {
                    "record_ref": a["request_id"],
                    "query": a["request"]["query"],
                    "intent": "seed" if context.get("seed_id") else "broad_orientation",
                    "seed_id": context.get("seed_id"),
                    "scope": a["request"]["scope"],
                    "result": result,
                    "execution_status": a["task_status"],
                }
            )
        return rows

    def neutral(self, run_id, ref):
        a = self.action(run_id, ref, "P05")
        if a["seed_id"] is not None:
            raise ValueError("A seed packet cannot replace neutral orientation")
        return a["result"]["artifact"]

    def build_input(self, run_id, operation, request):
        goal = self.goal(run_id)
        seed_id = request.get("seed_id")
        seed = self.seed(run_id, seed_id) if seed_id else None
        seed_brief = (
            {
                k: seed[k]
                for k in ("id", "kind", "question", "unresolved_relationship", "known_anchor_refs")
            }
            if seed
            else None
        )
        if operation == "P06_OPEN":
            orientation = self.neutral(run_id, request["orientation_ref"])
            return {
                "goal_context": goal,
                "neutral_overview": {
                    k: orientation[k] for k in ("overview", "competing_explanations", "limitations")
                },
                "source_discovery_capabilities": CAPABILITIES,
                "generic_search_constraints": {
                    "requested_count": self.count(request, "count", 1, 3),
                    "no_sibling_inputs": True,
                },
            }
        payload = {"goal_context": goal}
        if operation == "P03":
            payload.update(
                {
                    "seed_brief": seed_brief,
                    "source_discovery_capabilities": CAPABILITIES,
                    "generic_search_constraints": {
                        "query_count": self.count(request, "query_count", 1, 10),
                        "no_auto_execution": True,
                    },
                    "executed_search_history": self.scoped_searches(run_id, seed_id),
                }
            )
            if seed:
                neutral = self.neutral(run_id, seed["orientation_ref"])
                payload["neutral_overview"] = {
                    k: neutral[k] for k in ("overview", "competing_explanations", "limitations")
                }
            if request.get("followup_ref"):
                prior = self.action(run_id, request["followup_ref"], "P07")
                if prior["seed_id"] != seed_id or prior["result"]["artifact"]["decision"] != "retrieve_more":
                    raise ValueError("Focused followup requires same-seed retrieve_more")
                payload["focused_followups"] = [f for f in prior["result"]["artifact"]["focused_followups"] if f.get("resolution_kind") != "experiment"]
                payload["followup_stop_condition"] = "Bounded attempt to address these gaps; experiments are not literature tasks; no new material is not ready"
        elif operation == "ABSTRACT_SELECT":
            ids = request.get("view_ids")
            views = [v for v in self.views(run_id) if v["id"] in (ids or []) and v["seed_id"] in (None, seed_id) and v["access"] == "abstract"]
            if not ids or len(views) != len(set(ids)):
                raise ValueError("Actual same-scope abstract views required")
            payload.update({"seed_brief": seed_brief, "abstract_views": views})
        elif operation == "P04":
            view = next((v for v in self.views(run_id) if v["id"] == request["view_id"]), None)
            if not view or view["seed_id"] not in (None, seed_id):
                raise ValueError("Selected material view belongs to another Run/seed")
            if seed and seed["kind"] == "open" and view["seed_id"] not in (None, seed_id):
                raise ValueError("Open branch cannot read sibling views")
            payload.update({"source_view": view, "seed_brief": seed_brief})
        elif operation == "P05":
            eligible = [
                a for a in self.successful(run_id, "P04") if a["seed_id"] in (None, seed_id)
            ]
            selected = request.get("reading_refs", [a["request_id"] for a in eligible])
            if (
                not isinstance(selected, list)
                or not selected
                or len(set(selected)) != len(selected)
                or not set(selected) <= {a["request_id"] for a in eligible}
            ):
                raise ValueError("Explicit actual reading records from this scope required")
            omitted = request.get("omitted_readings", {})
            excluded = [a for a in eligible if a["request_id"] not in selected]
            if not isinstance(omitted, dict) or set(omitted) != {a["request_id"] for a in excluded}:
                raise ValueError("Every omitted reading needs an explicit recorded reason")
            for a in excluded:
                text(omitted[a["request_id"]])
                if any(c["negative_findings"] for c in a["result"]["artifact"]["finding_cards"]):
                    raise ValueError(
                        "This minimal slice cannot omit a reading with recorded negative findings"
                    )
            readings = [
                {"record_ref": a["request_id"], **a["result"]["artifact"]}
                for a in eligible
                if a["request_id"] in selected
            ]
            view_ids = {r["source_view_id"] for r in readings}
            payload.update(
                {
                    "mode": "SEED_PACKET" if seed else "NEUTRAL_ORIENTATION",
                    "seed_brief": seed_brief,
                    "reading_records": readings,
                    "source_views": [v for v in self.views(run_id) if v["id"] in view_ids],
                    "executed_search_history": self.scoped_searches(run_id, seed_id),
                    "selection_manifest": {
                        "selected_readings": selected,
                        "omitted_readings": omitted,
                        "cropping": "Explicit per-view character ranges; no implicit prompt truncation",
                    },
                }
            )
        elif operation == "P06_DIRECTED":
            payload.update(
                {
                    "neutral_orientation": self.neutral(run_id, request["orientation_ref"]),
                    "requested_count": self.count(request, "count", 1, 5),
                    "source_discovery_capabilities": CAPABILITIES,
                }
            )
        elif operation == "P07":
            if not seed:
                raise ValueError("Readiness requires exactly one seed")
            packet = self.action(run_id, request["packet_ref"], "P05")
            if packet["seed_id"] != seed_id:
                raise ValueError("Readiness packet belongs to another seed")
            searches = self.scoped_searches(run_id, seed_id)
            artifact = packet["result"]["artifact"]
            refs = (
                [packet["request_id"], goal["brief_revision_id"], seed_id]
                + artifact["finding_refs"]
                + [r["record_ref"] for r in artifact["retained_contexts"]]
                + [s["record_ref"] for s in searches]
            )
            payload.update(
                {
                    "seed_brief": seed_brief,
                    "packet": artifact,
                    "executed_search_records": searches,
                    "requested_specificity": text(request["requested_specificity"]),
                    "available_record_refs": refs,
                }
            )
        else:
            raise ValueError("Only P03 through P07 are implemented")
        return payload

    @staticmethod
    def count(request, key, default, maximum):
        value = request.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
            raise ValueError(
                "Explicit positive bounded operation count required; not a global scientific rule"
            )
        return value

    def messages(self, operation, payload, *, version=None):
        return [
            {"role": "system", "content": SYSTEM},
            {"role": "developer", "content": operation_prompt(operation, version)},
            {"role": "user", "content": encode(payload)},
        ]

    def submit(self, run_id, request_id, operation, request):
        run = self.literature.passed_goal(run_id)
        if (
            operation not in OPERATIONS
            or not isinstance(request, dict)
            or not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", request_id)
        ):
            raise ValueError("Explicit supported operation/request identity required")
        allowed = {
            "P03": {"seed_id", "query_count", "followup_ref"},
            "ABSTRACT_SELECT": {"seed_id", "view_ids"},
            "P04": {"seed_id", "view_id"},
            "P05": {"seed_id", "reading_refs", "omitted_readings"},
            "P06_DIRECTED": {"orientation_ref", "count"},
            "P06_OPEN": {"orientation_ref", "count"},
            "P07": {"seed_id", "packet_ref", "requested_specificity"},
        }[operation] | {"fixture_scenario"}
        if set(request) - allowed:
            raise ValueError("Unexpected input fields; review/expected fields are never accepted")
        old = self.store.rows("SELECT * FROM background_actions WHERE request_id=?", (request_id,))
        if old:
            if (
                old[0]["run_id"] != run_id
                or old[0]["operation"] != operation
                or old[0]["request"] != encode(request)
            ):
                raise ValueError("Background request_id reused with different input/Run")
            return old[0]
        if run["status"] not in IDLE:
            last = self.store.tasks(run_id)[-1]
            if not (
                run["status"] == "failed"
                and last["module"].startswith("background.")
                and last["status"] == "failed"
            ):
                raise ValueError("An unfinished/uncertain action must be resolved explicitly first")
        unresolved = self.store.rows(
            """SELECT p.id FROM attempts p JOIN tasks t ON t.id=p.task_id
            WHERE t.run_id=? AND p.status IN ('in_flight','uncertain') AND NOT EXISTS (
                SELECT 1 FROM attempts newer WHERE newer.task_id=p.task_id AND newer.call_key=p.call_key AND newer.ordinal>p.ordinal)
            """,
            (run_id,),
        )
        if unresolved:
            raise ValueError(
                "Unresolved external send must be recovered explicitly before a new model task"
            )
        payload = self.build_input(run_id, operation, request)
        version = operation_prompt_version(operation)
        if operation == "P07" and self.store.rows("SELECT name FROM sqlite_master WHERE name='research_runs'") and self.store.rows("SELECT run_id FROM research_runs WHERE run_id=?", (run_id,)):
            version = "v6-p07-bounded-followups-v1"
            payload["followup_requirements"] = "Separate literature-resolvable gaps and future experimental unknowns; include expected information and finite stopping conditions"
        config = self.config()
        if request.get("fixture_scenario") not in (
            None,
            "ready",
            "retrieve_more",
            "unable_to_prepare",
            "invalid_output",
            "technical_failure",
        ):
            raise ValueError("Unknown fixture scenario")
        if request.get("fixture_scenario") and config["execution_mode"] != "development_fixture":
            raise ValueError("Fixture scenario cannot be used with real/unconfigured model")
        if self.adapter:
            self.adapter.preflight({"input": payload, "request": request, "config": config})
        with self.store.db:
            plan = json.loads(run["plan"])
            step = len(plan)
            plan.append("background." + operation)
            self.store.db.execute(
                "UPDATE runs SET plan=?,status='ready' WHERE id=?", (encode(plan), run_id)
            )
            self.store._create_task(run_id, step, None)
            task = self.store.one("SELECT id FROM tasks WHERE run_id=? AND step=?", (run_id, step))
            self.store.db.execute(
                "INSERT INTO background_actions (request_id,run_id,task_id,operation,seed_id,request,input,config,created_at,prompt_version) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    request_id,
                    run_id,
                    task["id"],
                    operation,
                    request.get("seed_id"),
                    encode(request),
                    encode(payload),
                    encode(config),
                    now(),
                    version,
                ),
            )
        return self.store.one("SELECT * FROM background_actions WHERE request_id=?", (request_id,))

    def registry(self):
        r = Registry()
        for operation in OPERATIONS:
            r.register("background." + operation, self.perform)
        return r

    def execute(self, request_id, *, recover=False):
        action = self.store.one(
            "SELECT * FROM background_actions WHERE request_id=?", (request_id,)
        )
        self.literature.passed_goal(action["run_id"])
        if json.loads(action["config"]) != self.config():
            raise ValueError("Resume requires the frozen original model configuration/mode")
        if recover:
            self.store.recover(run_id=action["run_id"])
        task = self.store.one("SELECT status FROM tasks WHERE id=?", (action["task_id"],))
        if task["status"] == "ready":
            Scheduler(self.store, self.registry()).step(action["run_id"])
        return self.snapshot(action["run_id"])

    def progress(self, payload):
        """Content of P07 preparation, not storage identity or scientific validity.

        Resolve caller-assigned references before de-duplicating. Source identities,
        access/context limits, interpretations and their associations remain facts;
        new Task/view/finding IDs and clocks are not new information.
        """

        def content_set(values):
            return sorted({encode(value) for value in values})

        def search_content(record):
            result = record["result"]
            return {
                "query": record["query"],
                "scope": record["scope"],
                "result": {
                    **{k: result[k] for k in ("reported_total", "scope_complete", "status")},
                    "items": content_set(result["items"]),
                }
                if result and result["status"] == "succeeded"
                else {"status": result["status"] if result else None},
            }

        def searches(records):
            return content_set(
                search_content(record)
                for record in records
                if record["result"] and record["result"]["status"] == "succeeded"
            )

        packet = payload["packet"]
        views = {
            view["id"]: {
                k: view.get(k)
                for k in (
                    "source_ref",
                    "source_version",
                    "locator",
                    "text",
                    "access",
                    "representation",
                    "character_range",
                    "original_characters",
                    "original_text_sha256",
                    "cropped",
                    "not_read_ranges",
                    "selection_reason",
                    "access_limitations",
                    "images_seen",
                    "supplements_seen",
                )
            }
            for view in packet["source_views"]
        }
        refs = {ref: "view:" + digest(value) for ref, value in views.items()}
        refs.update(
            {
                record["record_ref"]: "search:" + digest(search_content(record))
                for record in packet["executed_search_history"] + payload["executed_search_records"]
            }
        )

        def referenced_text(value):
            # Also normalize explicit references embedded in model prose. Do not
            # rewrite the obtained source text or stable bibliographic identifiers.
            for ref in sorted(refs, key=len, reverse=True):
                value = value.replace(ref, refs[ref])
            return value

        cards = {}
        for reading in packet["retained_contexts"]:
            for card in reading["finding_cards"]:
                canonical = {
                    k: card[k]
                    for k in (
                        "source_ref",
                        "source_version",
                        "source_locator",
                        "access",
                        "representation",
                        "biological_context",
                        "intervention_comparator",
                        "endpoint",
                        "reported_observation",
                        "author_interpretation",
                        "supporting_quote",
                        "negative_state",
                        "images_seen",
                        "supplements_seen",
                    )
                }
                for field in (
                    "biological_context",
                    "intervention_comparator",
                    "endpoint",
                    "reported_observation",
                    "author_interpretation",
                ):
                    canonical[field] = referenced_text(card[field])
                canonical.update(
                    {
                        k: content_set(
                            v if k == "negative_quotes" else referenced_text(v) for v in card[k]
                        )
                        for k in (
                            "negative_findings",
                            "negative_quotes",
                            "not_established",
                            "transfer_assumptions",
                        )
                    }
                )
                canonical["source_view"] = "view:" + digest(views[card["source_view_ref"]])
                cards[card["id"]] = canonical
        refs.update({ref: "finding:" + digest(value) for ref, value in cards.items()})
        readings = {}
        for reading in packet["retained_contexts"]:
            readings[reading["record_ref"]] = {
                "source_view": "view:" + digest(views[reading["source_view_id"]]),
                "finding_cards": content_set(
                    cards[card["id"]] for card in reading["finding_cards"]
                ),
                "targeted_reading_requests": content_set(
                    referenced_text(v) for v in reading["targeted_reading_requests"]
                ),
            }
        refs.update({ref: "reading:" + digest(value) for ref, value in readings.items()})
        selection = packet["selection_manifest"]
        background = {
            "mode": packet["mode"],
            **{
                k: content_set(referenced_text(v) for v in packet[k])
                for k in ("overview", "competing_explanations", "unranked_questions", "limitations")
            },
            "finding_refs": content_set(refs[ref] for ref in packet["finding_refs"]),
            "knowledge_edges": content_set(
                {
                    "kind": edge["kind"],
                    "description": referenced_text(edge["description"]),
                    "finding_refs": content_set(refs[ref] for ref in edge["finding_refs"]),
                }
                for edge in packet["knowledge_edges"]
            ),
            "readings": content_set(readings.values()),
            "selection": {
                "selected_readings": content_set(
                    refs[ref] for ref in selection["selected_readings"]
                ),
                # Excluded records expose only reasons to P07, not their contents.
                "omission_reasons": content_set(
                    referenced_text(reason) for reason in selection["omitted_readings"].values()
                ),
                "cropping": selection["cropping"],
            },
            "executed_search_history": searches(packet["executed_search_history"]),
        }
        return digest(
            {
                "views": content_set(views.values()),
                "packet": background,
                "searches": searches(payload["executed_search_records"]),
                "specificity": payload["requested_specificity"],
            }
        )

    def perform(self, inputs, calls):
        action = self.store.one(
            "SELECT * FROM background_actions WHERE task_id=?", (inputs.task_id,)
        )
        self.literature.passed_goal(inputs.run_id)
        operation = action["operation"]
        payload = json.loads(action["input"])
        request = json.loads(action["request"])
        config = json.loads(action["config"])
        base = {
            "operation": operation,
            "prompt_version": action["prompt_version"],
            "binding": {
                "run_id": inputs.run_id,
                "goal_ref": inputs.goal_context_ref,
                "seed_id": action["seed_id"],
            },
            "model_config": config,
            "execution_mode": config["execution_mode"],
            "science_validated": False,
        }
        if not self.adapter or not self.adapter.configured:
            return ModuleResult({**base, "background_status": "model_not_configured"})
        if config["execution_mode"] == "real_model" and not self.adapter.authorized:
            return ModuleResult({**base, "background_status": "model_call_not_authorized"})
        fingerprint = self.progress(payload) if operation == "P07" else None
        if operation == "P07":
            base["progress_fingerprint_version"] = "p07-preparation-content-v2"
        if fingerprint:
            previous = [
                a
                for a in self.successful(inputs.run_id, "P07")
                if a["seed_id"] == action["seed_id"] and self.progress(a["input"]) == fingerprint
            ]
            if previous:
                return ModuleResult(
                    {
                        **base,
                        "background_status": "no_progress",
                        "previous_readiness_ref": previous[-1]["request_id"],
                        "reason": "No changed source/reading/packet content, query coverage or specificity; do not repeat model check or infer scientific rejection",
                    }
                )
        messages = self.messages(operation, payload, version=action["prompt_version"])
        actual = self.adapter.request(messages)
        model_request = {
            "operation": operation,
            "prompt_version": action["prompt_version"],
            "messages": messages,
            "actual_request": actual,
            "model_config": config,
            "binding": base["binding"],
        }
        if config["execution_mode"] == "development_fixture":
            model_request["fixture_scenario"] = request.get("fixture_scenario", "ready")
        self.adapter.preflight(model_request)
        size = len(encode(actual).encode())
        if size > config["max_request_bytes"]:
            return ModuleResult(
                {
                    **base,
                    "background_status": "capacity_exceeded",
                    "actual_request_bytes": size,
                    "limit": config["max_request_bytes"],
                    "reason": "No model send and no silent truncation; select explicit smaller material views or configure capacity",
                }
            )
        response = calls.execute("model", self.adapter.target, model_request, self.adapter)
        try:
            artifact = parse_output(operation, self.adapter.text(response.output), payload)
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            with self.store.db:
                self.store.fact(
                    inputs.task_id,
                    "background_parse_error",
                    {"prompt_version": action["prompt_version"], "error": str(exc)},
                )
            return ModuleResult(
                {**base, "background_status": "invalid_output", "parse_error": str(exc)}
            )
        if operation == "P04":
            artifact["source_view_id"] = payload["source_view"]["id"]
            for i, card in enumerate(artifact["finding_cards"]):
                card["id"] = f"finding-{inputs.task_id}-{i}"
        if operation.startswith("P06"):
            artifact["seeds"] = [
                {
                    **q,
                    "id": f"seed-{inputs.task_id}-{i}",
                    "kind": "open" if operation == "P06_OPEN" else "directed",
                    "run_id": inputs.run_id,
                    "goal_ref": inputs.goal_context_ref,
                    "orientation_ref": request["orientation_ref"],
                    "execution_mode": config["execution_mode"],
                }
                for i, q in enumerate(artifact.pop("questions"))
            ]
        return ModuleResult(
            {
                **base,
                "background_status": "saved",
                "artifact": artifact,
                "progress_fingerprint": fingerprint,
            }
        )

    def execute_query(self, run_id, plan_ref, index, request_id, literature):
        plan = self.action(run_id, plan_ref, "P03")
        if (
            isinstance(index, bool)
            or not isinstance(index, int)
            or not 0 <= index < len(plan["result"]["artifact"]["queries"])
        ):
            raise ValueError("Choose an explicit saved planned query")
        q = plan["result"]["artifact"]["queries"][index]
        context = {
            "seed_id": plan["seed_id"],
            "purpose": "seed" if plan["seed_id"] else "orientation",
            "plan_ref": plan_ref,
            "query_index": index,
        }
        action = literature.submit(
            run_id,
            request_id,
            {"kind": "search", "query": q["query"], "page_size": 5},
            background_context=context,
        )
        return literature.execute(action["request_id"])

    def snapshot(self, run_id):
        self.store.run(run_id)
        actions = self.actions(run_id)
        readings = [a for a in actions if a["operation"] == "P04"]
        materials = [
            {
                "acquisition_task_id": a["task_id"],
                "source": a["result"]["acquisition"]["source"],
                "access": a["result"]["acquisition"]["access"],
                "characters": len(a["result"]["acquisition"]["text"]),
                "context": a["request"].get("background_context"),
            }
            for a in self.literature.history(run_id)
            if a["result"] and a["result"]["acquisition"].get("text")
        ]
        return {
            "run_id": run_id,
            "views": self.views(run_id),
            "actions": actions,
            "seeds": self.seeds(run_id),
            "materials": materials,
            "current_model_config": self.config(),
            "current_prompt_versions": {op: operation_prompt_version(op) for op in OPERATIONS},
            "science_validated": False,
            "real_adapter_attempts_recorded": sum(
                len(a["attempts"]) for a in actions if a["config"]["execution_mode"] == "real_model"
            ),
            "model_reading_performance_reviewed": False,
            "real_calls_authorized": bool(
                self.adapter and getattr(self.adapter, "authorized", False)
            ),
            "reading_count_saved": sum(
                (a.get("result") or {}).get("background_status") == "saved" for a in readings
            ),
            "generation_implemented": False,
        }
