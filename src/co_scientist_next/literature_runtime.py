"""Narrow M12 manual acquisition continuation. No query planning or reading."""

import json
import re
from dataclasses import asdict

from .contracts import ModuleResult
from .europe_pmc import SCOPE, EuropePMC, public_http
from .literature import AccessLevel, FetchRequest, SearchRequest
from .scheduler import Registry, Scheduler
from .store import encode, now

SEARCH, FETCH = "literature.search.v1", "literature.fetch.v1"


def literature_route(output):
    status = output["acquisition"]["status"]
    return {
        "succeeded": "literature_acquired_unread",
        "incomplete": "literature_incomplete",
        "failed": "literature_failed",
    }[status]


class LiteratureService:
    def __init__(self, store, *, enabled=False, transport=public_http):
        self.store, self.enabled, self.transport = store, enabled, transport

    def passed_goal(self, run_id):
        run = self.store.run(run_id)
        if not run["goal_context_ref"]:
            raise ValueError("A saved Goal and completed Goal Ethics pass are required")
        saved = self.store.rows(
            """SELECT r.output FROM results r JOIN tasks t ON t.id=r.task_id
               WHERE t.run_id=? AND t.module='goal.screen.v1' AND t.status='succeeded'""",
            (run_id,),
        )
        if len(saved) != 1:
            raise ValueError("No saved completed Goal Ethics pass")
        result = json.loads(saved[0]["output"])
        ethics = result.get("ethics", {})
        if (
            result.get("execution_status") != "screened"
            or ethics.get("completed") is not True
            or ethics.get("decision") != "pass"
            or ethics.get("policy_refs") != [run["policy_ref"]]
        ):
            raise ValueError("Acquisition requires the saved completed Goal Ethics pass")
        self.store.one(
            "SELECT id FROM goal_contexts WHERE id=? AND run_id=?",
            (run["goal_context_ref"], run_id),
        )
        return run

    def submit(self, run_id, request_id, request, *, background_context=None):
        if not self.enabled:
            raise ValueError("Public literature access was not explicitly enabled at startup")
        run = self.passed_goal(run_id)
        if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", request_id):
            raise ValueError("A stable request_id is required for idempotent explicit submission")
        payload = self.validate(request)
        if payload["kind"] == "search" and request.get("parent_search_id"):
            parent = next(
                (a for a in self.history(run_id) if a["request_id"] == request["parent_search_id"]),
                None,
            )
            previous = ((parent or {}).get("result") or {}).get("acquisition", {})
            if (
                not parent
                or parent["request"]["kind"] != "search"
                or parent["request"]["query"] != payload["query"]
                or not payload["cursor"]
                or previous.get("next_cursor") != payload["cursor"]
            ):
                raise ValueError("Continuation must bind the actual parent query/cursor")
            payload["parent_search_id"] = request["parent_search_id"]
            background_context = parent["request"].get("background_context")
        if payload["kind"] == "fetch":
            matches = [
                a
                for a in self.history(run_id)
                if a["request"]["kind"] == "search"
                and any(
                    i["source_ref"] == payload["source_ref"]
                    for i in (a.get("result") or {}).get("acquisition", {}).get("items", [])
                )
            ]
            if request.get("search_request_id"):
                matches = [a for a in matches if a["request_id"] == request["search_request_id"]]
                payload["search_request_id"] = request["search_request_id"]
            else:
                matches = [
                    a
                    for a in matches
                    if not a["request"].get("background_context", {}).get("seed_id")
                ]
            if not matches:
                raise ValueError(
                    "Fetch source must bind this Run's search history; select parent for seed material"
                )
            background_context = matches[0]["request"].get("background_context")
        if background_context:
            plan = self.store.one(
                """SELECT a.*,r.output FROM background_actions a JOIN results r ON r.task_id=a.task_id
                WHERE a.request_id=? AND a.run_id=? AND a.operation='P03'""",
                (background_context["plan_ref"], run_id),
            )
            output = json.loads(plan["output"])
            if (
                plan["seed_id"] != background_context.get("seed_id")
                or output.get("background_status") != "saved"
            ):
                raise ValueError("Query plan context mismatch")
            if (
                payload["kind"] == "search"
                and output["artifact"]["queries"][background_context["query_index"]]["query"]
                != payload["query"]
            ):
                raise ValueError("Executed query must equal selected saved plan")
            payload["background_context"] = background_context
            if payload["kind"] == "search":
                managed = self.store.rows("SELECT name FROM sqlite_master WHERE type='table' AND name='research_runs'")
                automatic = managed and self.store.rows("SELECT run_id FROM research_runs WHERE run_id=?", (run_id,))
                payload["query_origin"] = "model_planned_controller_executed" if automatic else "model_planned_user_executed"
        old = self.store.rows("SELECT * FROM literature_actions WHERE request_id=?", (request_id,))
        if old:
            if old[0]["run_id"] != run_id or old[0]["request"] != encode(payload):
                raise ValueError("request_id reused with different query/source/Run")
            return old[0]  # Never automatically resend an existing action.
        if run["status"] not in (
            "awaiting_background",
            "literature_acquired_unread",
            "literature_incomplete",
            "literature_failed",
            "background_saved",
            "background_problem",
            "awaiting_generation",
            "background_no_progress",
        ):
            raise ValueError(
                "Run has an unfinished/blocked action; resolve explicitly before a new request"
            )
        if payload["kind"] == "fetch" and payload["source_ref"] not in self.source_refs(run_id):
            raise ValueError("Fetch source must come from this Run's saved search history")
        module = SEARCH if payload["kind"] == "search" else FETCH
        with self.store.db:
            plan = json.loads(run["plan"])
            step = len(plan)
            plan.append(module)
            self.store.db.execute(
                "UPDATE runs SET plan=?,status='ready' WHERE id=?", (encode(plan), run_id)
            )
            self.store._create_task(run_id, step, {"manual_literature_request": payload})
            task = self.store.one("SELECT id FROM tasks WHERE run_id=? AND step=?", (run_id, step))
            self.store.db.execute(
                "INSERT INTO literature_actions VALUES(?,?,?,?,?)",
                (request_id, run_id, task["id"], encode(payload), now()),
            )
        return self.store.one("SELECT * FROM literature_actions WHERE request_id=?", (request_id,))

    @staticmethod
    def validate(request):
        if not isinstance(request, dict):
            raise TypeError("Structured manual request required")
        if request.get("kind") == "search":
            query = request.get("query")
            cursor = request.get("cursor")
            size = request.get("page_size", 5)
            if not isinstance(query, str) or not query.strip() or len(query) > 2000:
                raise ValueError("Explicit manual query of 1..2000 characters required")
            if cursor is not None and (
                not isinstance(cursor, str) or not cursor or len(cursor) > 4000
            ):
                raise ValueError("Invalid cursor")
            if isinstance(size, bool) or not isinstance(size, int) or not 1 <= size <= 20:
                raise ValueError("page_size must be 1..20")
            return {
                "kind": "search",
                "query": query,
                "cursor": cursor,
                "page_size": size,
                "query_origin": "human_entered",
                "source": "Europe PMC",
                "scope": SCOPE,
            }
        if request.get("kind") == "fetch":
            source = request.get("source_ref")
            if not isinstance(source, str) or not re.fullmatch(
                r"epmc:[A-Z]+:[A-Za-z0-9._-]+", source
            ):
                raise ValueError("Invalid Europe PMC source_ref")
            access = AccessLevel(request.get("desired_access", "abstract"))
            if access == AccessLevel.NONE:
                raise ValueError("Specify requested access level")
            return {
                "kind": "fetch",
                "source_ref": source,
                "desired_access": access.value,
                "query_origin": "human_selected_source",
            }
        raise ValueError("Only explicit search/fetch is implemented")

    def registry(self):
        registry = Registry()
        registry.register(SEARCH, self.acquire)
        registry.register(FETCH, self.acquire)
        return registry

    def execute(self, request_id, *, recover=False):
        if not self.enabled:
            raise ValueError("Public literature access disabled")
        action = self.store.one(
            "SELECT * FROM literature_actions WHERE request_id=?", (request_id,)
        )
        self.passed_goal(action["run_id"])
        if recover:
            self.store.recover(run_id=action["run_id"])
        task = self.store.one("SELECT status FROM tasks WHERE id=?", (action["task_id"],))
        if task["status"] == "ready":
            Scheduler(self.store, self.registry()).step(action["run_id"])
        # failed/blocked/running are deliberately not retried by a repeat POST.
        return self.history(action["run_id"])

    def acquire(self, inputs, calls):
        self.passed_goal(inputs.run_id)  # M12 gate is checked again at execution.
        request = inputs.previous_result["manual_literature_request"]
        library = None
        if self.store.rows("SELECT name FROM sqlite_master WHERE name='research_runs'") and self.store.rows("SELECT run_id FROM research_runs WHERE run_id=?", (inputs.run_id,)):
            from .research_library import ResearchLibrary
            library = ResearchLibrary(self.store)
            if request["kind"] == "fetch":
                reused = library.lookup(request["source_ref"], request["desired_access"])
                if reused:
                    return ModuleResult(reused)
        port = EuropePMC(calls, page_size=request.get("page_size", 5), transport=self.transport)
        if request["kind"] == "search":
            result = port.search(
                SearchRequest("Europe PMC", request["query"], SCOPE, request["cursor"])
            )
        else:
            result = port.fetch(
                FetchRequest(request["source_ref"], AccessLevel(request["desired_access"]))
            )
        output = {"acquisition": asdict(result), "details": port.details, "model_read": False, "science_validated": False}
        if library and request["kind"] == "fetch":
            library.save(inputs.task_id, request, output)
        return ModuleResult(output)

    def source_refs(self, run_id):
        return {
            source["source_ref"]
            for item in self.history(run_id)
            for source in (item.get("result") or {}).get("acquisition", {}).get("items", [])
        }

    def history(self, run_id):
        rows = self.store.rows(
            """SELECT a.*,t.status AS task_status,t.error,r.output FROM literature_actions a
               JOIN tasks t ON t.id=a.task_id LEFT JOIN results r ON r.task_id=t.id
               WHERE a.run_id=? ORDER BY t.step""",
            (run_id,),
        )
        for row in rows:
            row["request"] = json.loads(row["request"])
            output = row.pop("output")
            row["result"] = json.loads(output) if output else None
            row["error"] = json.loads(row["error"]) if row["error"] else None
            row["attempts"] = self.store.rows(
                """SELECT id,call_key,status,target,request,started_at,finished_at,error,usage
                   FROM attempts WHERE task_id=? ORDER BY started_at,ordinal""",
                (row["task_id"],),
            )
        return rows
