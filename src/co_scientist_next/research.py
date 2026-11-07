"""Single-process persistent research controller. Only explicit Start grants scheduling."""

import json
import time
from contextlib import nullcontext
from threading import Event, Thread

from .background import digest
from .research_config import expected_candidates, validate_config
from .research_library import ResearchLibrary
from .scheduler import Scheduler
from .store import encode, now


class ResearchYield(BaseException):
    """Stop before a send without manufacturing a technical/scientific result."""


class LocalProblem(Exception):
    pass


class ResearchController:
    def __init__(self, store, goal, background, literature, generation, reviews):
        self.store = store
        self.goal, self.background, self.literature = goal, background, literature
        self.generation, self.reviews = generation, reviews
        self.stop_event = Event()
        self.restart_only = False

    def initialize(self):
        self.store.db.executescript("""
        CREATE TABLE IF NOT EXISTS research_runs (
            run_id TEXT PRIMARY KEY REFERENCES runs(id), start_key TEXT UNIQUE NOT NULL,
            config TEXT NOT NULL, policies TEXT NOT NULL, profiles TEXT NOT NULL,
            status TEXT NOT NULL, state TEXT NOT NULL, reason TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS research_seed_holds (
            run_id TEXT NOT NULL REFERENCES runs(id), seed_id TEXT NOT NULL,
            task_id TEXT NOT NULL REFERENCES tasks(id), reason TEXT NOT NULL,
            created_at TEXT NOT NULL, PRIMARY KEY(run_id,task_id));
        CREATE TABLE IF NOT EXISTS research_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL REFERENCES runs(id),
            seed_id TEXT, kind TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL);
        """)
        from .goal_restart import initialize as initialize_restarts
        initialize_restarts(self.store)
        ResearchLibrary(self.store).initialize()
        from .research_projects import initialize
        initialize(self.store)
        self.store.call_guard = self.guard

    def profiles(self):
        return {
            "goal": self.goal.adapter.public_config()
            if hasattr(self.goal.adapter, "public_config")
            else {
                "execution_mode": "development_fixture"
                if self.goal.development_test
                else "not_configured"
            },
            "reading": self.background.config(),
            "generation": self.generation.config(),
            "review": self.reviews.config(),
        }

    def start(self, revision_id, start_key, config, policies, *, policy_selection=None, defaults_version=None, commit=True):
        config = validate_config(config)
        if not isinstance(start_key, str) or not 8 <= len(start_key) <= 100:
            raise ValueError("Stable Start identity required")
        if set(policies) != {"goal", "candidate", "decision_policy", "r0"}:
            raise ValueError("Explicit versioned Goal, Candidate and R0 policies required")
        old = self.store.rows("SELECT * FROM research_runs WHERE start_key=?", (start_key,))
        if old:
            row = old[0]
            if (
                self.store.run(row["run_id"])["revision_id"] != revision_id
                or row["config"] != encode(config)
                or row["policies"] != encode(policies)
            ):
                raise ValueError("Start identity reused with different frozen input")
            return row["run_id"]
        revision = self.store.one('SELECT project_id FROM brief_revisions WHERE id=?', (revision_id,))
        lifecycle = self.store.rows('SELECT state FROM project_lifecycle WHERE project_id=?', (revision['project_id'],))
        if lifecycle and lifecycle[0]['state'] != 'active':
            raise ValueError('Restore this project before starting a new Run')
        profiles = self.profiles()
        if any(p.get("execution_mode") == "not_configured" for p in profiles.values()):
            raise ValueError("All module profiles must be configured; no fixture fallback")
        if not self.literature.enabled:
            raise ValueError("Literature service is not enabled")
        if any(p.get("execution_mode") == "real_model" and not p.get("credential_configured") for p in profiles.values()):
            raise ValueError("A real module credential is not configured; no fixture fallback")
        # Run, first Task, frozen configuration and unique Start reservation commit together.
        with self.store.db if commit else nullcontext():
            run = self.goal.create_run(revision_id, policies["goal"], commit=False)
            self.store.db.execute(
                "INSERT INTO research_runs VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    run,
                    start_key,
                    encode(config),
                    encode(policies),
                    encode(profiles),
                    "running",
                    encode({"phase": "goal", "seed_index": -1, "seeds": [], "round": 0, "policy_selection": policy_selection, "defaults_version": defaults_version, "explicit_current_start": self.restart_only}),
                    None,
                    now(),
                    now(),
                ),
            )
            self.event(
                run,
                None,
                "research_started",
                {
                    "configuration": config,
                    "expected_candidates": expected_candidates(config),
                    "science_validated": False,
                },
            )
        return run

    def event(self, run, seed, kind, detail):
        self.store.db.execute(
            "INSERT INTO research_events(run_id,seed_id,kind,detail,created_at) VALUES(?,?,?,?,?)",
            (run, seed, kind, encode(detail), now()),
        )

    def row(self, run):
        row = self.store.one("SELECT * FROM research_runs WHERE run_id=?", (run,))
        for k in ("config", "policies", "profiles", "state"):
            row[k] = json.loads(row[k])
        return row

    def save(self, row, *, status=None, reason=None):
        with self.store.db:
            # Never overwrite concurrent Pause/Stop with the worker's stale status.
            self.store.db.execute(
                "UPDATE research_runs SET state=?,updated_at=? WHERE run_id=?",
                (encode(row["state"]), now(), row["run_id"]),
            )
            if status:
                self.store.db.execute(
                    "UPDATE research_runs SET status=?,reason=? WHERE run_id=? AND status='running'",
                    (status, reason, row["run_id"]),
                )

    @staticmethod
    def control(db, run, action):
        row = db.execute("SELECT status FROM research_runs WHERE run_id=?", (run,)).fetchone()
        if row is None:
            raise ValueError("Unknown automatic Run")
        status = row[0]
        allowed = {
            "pause": ("running", "paused"),
            "resume": ("paused", "running"),
            "stop": ("running", "stopped"),
        }
        if action not in allowed:
            raise ValueError("Only pause/resume/stop supported")
        old, new = allowed[action]
        if action == "stop" and status == "paused":
            old = "paused"
        if status not in (old, new):
            raise ValueError("Terminal/blocked research cannot be restarted by ordinary resume")
        with db:
            changed = db.execute(
                "UPDATE research_runs SET status=?,updated_at=? WHERE run_id=? AND status IN (?,?)", (new, now(), run, old, new)
            )
            if changed.rowcount != 1:
                raise ValueError("Research state changed; read the saved terminal status")
            db.execute(
                "INSERT INTO research_events(run_id,kind,detail,created_at) VALUES(?,?,?,?)",
                (
                    run,
                    action,
                    encode({"remote_cancelled": False, "new_calls_scheduled": False}),
                    now(),
                ),
            )
        return {"status": new, "remote_cancelled": False}

    def authorized_run(self, run):
        return not self.restart_only or bool(self.store.rows("SELECT successor_run_id FROM goal_restarts WHERE successor_run_id=?", (run,))) or bool(self.store.rows("SELECT run_id FROM research_runs WHERE run_id=? AND json_extract(state, '$.explicit_current_start')=1", (run,)))

    def guard(self, task_id, request):
        task = self.store.one("SELECT run_id FROM tasks WHERE id=?", (task_id,))
        if not self.authorized_run(task["run_id"]):
            raise ResearchYield()
        rows = self.store.rows(
            "SELECT status,config FROM research_runs WHERE run_id=?", (task["run_id"],)
        )
        if not rows:
            return
        if rows[0]["status"] != "running":
            raise ResearchYield()
        config = json.loads(rows[0]["config"])
        attempts = self.store.rows(
            "SELECT a.request FROM attempts a JOIN tasks t ON t.id=a.task_id WHERE t.run_id=?",
            (task["run_id"],),
        )
        requests = [json.loads(a["request"]) for a in attempts]
        if request.get("operation") and not request["operation"].endswith(".remote_query"):
            count = sum(
                bool(q.get("operation")) and not q["operation"].endswith(".remote_query")
                for q in requests
            )
            if count >= config["max_model_calls"]:
                self.limit(task["run_id"], "model_calls")
        elif request.get("method") == "GET" and "europepmc" in request.get("url", ""):
            is_search = "/search?" in request["url"]
            key = "max_search_pages" if is_search else "max_material_fetches"
            count = sum(
                q.get("method") == "GET"
                and "europepmc" in q.get("url", "")
                and ("/search?" in q["url"]) == is_search
                for q in requests
            )
            if count >= config[key]:
                self.limit(task["run_id"], key)

    def limit(self, run, kind):
        with self.store.db:
            self.store.db.execute(
                "UPDATE research_runs SET status='blocked',reason=? WHERE run_id=?",
                ("resource_limit:" + kind, run),
            )
            self.event(run, None, "resource_limit", {"kind": kind, "ready_inferred": False})
        raise ResearchYield()

    def identifier(self, row, label):
        s = row["state"]
        return "auto-" + digest([row["run_id"], s["seed_index"], s["round"], label])[:48]

    def idle(self, run):
        # This is only controller-owned routing; never clears unresolved calls.
        from .research_scope import blocking_attempts, isolated_task
        active_tasks = self.store.rows("SELECT id FROM tasks WHERE run_id=? AND status IN ('ready','running','waiting_remote')", (run,))
        if any(not isolated_task(self.store, run, t['id']) for t in active_tasks):
            return
        unresolved = self.store.rows(
            "SELECT a.id FROM attempts a JOIN tasks t ON t.id=a.task_id WHERE t.run_id=? AND a.status IN ('uncertain','in_flight')",
            (run,),
        )
        if blocking_attempts(self.store, run, unresolved):
            raise LocalProblem("unresolved_send_requires_explicit_recovery")
        with self.store.db:
            self.store.db.execute("UPDATE runs SET status='awaiting_background' WHERE id=?", (run,))

    def perform(self, row, service, request_id, request, operation=None):
        run = row["run_id"]
        table = (
            "background_actions"
            if service is self.background
            else "literature_actions"
            if service is self.literature
            else "generation_actions"
            if service is self.generation
            else "candidate_review_actions"
        )
        existing = self.store.rows(f"SELECT * FROM {table} WHERE request_id=?", (request_id,))
        if existing:
            action = existing[0]
        else:
            self.idle(run)
            action = (
                service.submit(run, request_id, operation, request)
                if service is self.background
                else service.submit(run, request_id, request)
            )
            with self.store.db:
                self.event(
                    run,
                    row["state"].get("seed_id"),
                    "operation_created",
                    {
                        "operation": operation
                        or request.get("operation")
                        or request.get("kind")
                        or "P08",
                        "request_id": request_id,
                        "task_id": action["task_id"],
                    },
                )
        task = self.store.one("SELECT * FROM tasks WHERE id=?", (action["task_id"],))
        if task["status"] == "succeeded":
            return json.loads(
                self.store.one("SELECT output FROM results WHERE task_id=?", (task["id"],))[
                    "output"
                ]
            )
        jobs = self.store.rows("SELECT * FROM remote_generations WHERE task_id=?", (task["id"],))
        if jobs:
            job = jobs[0]
            if (
                job.get("latest_query")
                and json.loads(job["latest_query"]).get("outcome") == "query_failed"
            ):
                raise LocalProblem("remote_query_failed; ID preserved")
            poll_key = "poll-" + request_id
            poll = row["state"].get(poll_key, {"count": 0, "next": 0})
            if poll["count"] >= row["config"]["max_remote_queries"]:
                raise LocalProblem("remote_observation_limit; ID preserved")
            if time.time() < poll["next"]:
                return None
            # Persist reservation before GET; a crash cannot create a new POST.
            poll["count"] += 1
            poll["next"] = time.time() + row["config"]["poll_interval_seconds"]
            row["state"][poll_key] = poll
            self.save(row)
            service.query_remote(request_id)
            poll["next"] = time.time() + row["config"]["poll_interval_seconds"]
            self.save(row)
            latest = self.store.one(
                "SELECT * FROM remote_generations WHERE task_id=?", (task["id"],)
            )
            if latest.get("latest_query"):
                q = json.loads(latest["latest_query"])
                if q.get("outcome") == "query_failed" or q.get("status") in ("failed", "uncertain"):
                    raise LocalProblem("remote_query_failed; ID preserved")
        else:
            if task["status"] in ("failed", "blocked"):
                self.raise_task_problem(task)
            if task["status"] == "running":
                self.store.recover(task_id=task["id"])
            service.execute(request_id)
        task = self.store.one("SELECT * FROM tasks WHERE id=?", (action["task_id"],))
        if task["status"] == "succeeded":
            return json.loads(
                self.store.one("SELECT output FROM results WHERE task_id=?", (task["id"],))[
                    "output"
                ]
            )
        if task["status"] in ("failed", "blocked"):
            self.raise_task_problem(task)
        return None

    def raise_task_problem(self, task):
        for attempt in self.store.rows(
            "SELECT response FROM attempts WHERE task_id=?", (task["id"],)
        ):
            response = json.loads(attempt["response"]) if attempt["response"] else {}
            if response.get("http_status") in (401, 403):
                raise LocalProblem("credentials_invalid; Run-level stop")
        raise LocalProblem("operation_" + task["status"])

    def background_call(self, row, label, operation, request):
        ref = self.identifier(row, label)
        output = self.perform(row, self.background, ref, request, operation)
        if output and output.get("background_status") != "saved":
            raise LocalProblem("background_" + output.get("background_status", "invalid"))
        return ref, output

    def next_seed(self, row, reason=None):
        s = row["state"]
        if s.get("seed_id"):
            with self.store.db:
                self.event(
                    row["run_id"],
                    s["seed_id"],
                    "direction_finished",
                    {"reason": reason or "candidate_review_boundary", "science_validated": False},
                )
            s.setdefault("direction_results", {})[s["seed_id"]] = (
                reason or "candidate_review_boundary"
            )
        # Followup plans belong to the previous seed, never its sibling.
        s.pop("followup_ref", None)
        s["seed_index"] += 1
        if s["seed_index"] >= len(s["seeds"]):
            s["phase"] = "finished"
            self.save(
                row, status="completed", reason="bounded_work_finished; not scientific approval"
            )
            return
        s.update(seed_id=s["seeds"][s["seed_index"]]["id"], round=0, phase="plan")
        self.clear_round(s)

    @staticmethod
    def clear_round(s):
        for key in (
            "plan_ref",
            "queries",
            "query_index",
            "page",
            "parent_search",
            "cursor",
            "sources",
            "source_index",
            "abstracts",
            "selected",
            "views",
            "view_index",
            "reading_refs",
            "packet_ref",
            "readiness_ref",
            "candidate_index",
            "modes",
            "mode_index",
        ):
            s.pop(key, None)

    def tick(self, run):
        if not self.authorized_run(run):
            return
        row = self.row(run)
        if row["status"] != "running":
            return
        try:
            if row["profiles"] != self.profiles():
                raise LocalProblem("frozen_profiles_changed; no model fallback")
            self.advance(row)
            self.save(row)
        except ResearchYield:
            self.save(row)
        except (LocalProblem, ValueError, KeyError, TypeError) as exc:
            reason = (
                str(exc)
                if isinstance(exc, LocalProblem)
                else type(exc).__name__ + ": contract_or_configuration_error"
            )
            with self.store.db:
                self.event(run, row["state"].get("seed_id"), "stopped_scope", {"reason": reason})
            unresolved = self.store.rows(
                "SELECT a.id FROM attempts a JOIN tasks t ON t.id=a.task_id WHERE t.run_id=? AND a.status IN ('uncertain','in_flight')",
                (run,),
            )
            seed = row["state"].get("seed_id")
            from .research_scope import blocking_attempts, task_seed
            unresolved = blocking_attempts(self.store, run, unresolved)
            global_reason = reason.startswith(("resource_limit", "frozen_profiles", "credentials_invalid")) or "configuration" in reason
            # Only current-seed tasks can be held. Broad/common dependencies remain Run-level.
            own = [a for a in unresolved if task_seed(self.store, self.store.one("SELECT task_id FROM attempts WHERE id=?", (a['id'],))['task_id']) == seed] if seed else []
            if seed and not global_reason and len(own) == len(unresolved):
                with self.store.db:
                    for attempt in own:
                        task_id = self.store.one("SELECT task_id FROM attempts WHERE id=?", (attempt['id'],))['task_id']
                        self.store.db.execute("INSERT OR IGNORE INTO research_seed_holds VALUES(?,?,?,?,?)", (run,seed,task_id,reason,now()))
                self.next_seed(row, reason + ("; unresolved call retained; no automatic resend" if own else ""))
                self.save(row)
            else:
                self.save(row, status="blocked", reason=reason)

    def advance(self, row):
        s, c, run = row["state"], row["config"], row["run_id"]
        phase = s["phase"]
        seed = s.get("seed_id")
        scoped = {"seed_id": seed} if seed else {}
        if phase == "goal":
            tasks = self.store.tasks(run)
            current = next((t for t in tasks if t["status"] in ("ready", "running")), None)
            if current:
                if current["status"] == "running":
                    self.store.recover(task_id=current["id"])
                Scheduler(self.store, self.goal.modules()).step(run)
                return
            if self.store.run(run)["status"] != "awaiting_background":
                raise LocalProblem("goal_" + self.store.run(run)["status"])
            s["phase"] = "plan"
        elif phase == "plan":
            req = {**scoped, "query_count": c["queries_per_round"]}
            if s.get("followup_ref"):
                req["followup_ref"] = s["followup_ref"]
            ref, output = self.background_call(row, "plan", "P03", req)
            if output:
                s.update(
                    plan_ref=ref,
                    queries=output["artifact"]["queries"],
                    query_index=0,
                    page=0,
                    sources=[],
                    phase="search",
                )
        elif phase == "search":
            if s["query_index"] >= len(s["queries"]):
                s.update(phase="abstract", source_index=0, abstracts=[])
                return
            req = {
                "kind": "search",
                "query": s["queries"][s["query_index"]]["query"],
                "page_size": c["page_size"],
            }
            if s.get("cursor"):
                req.update(cursor=s["cursor"], parent_search_id=s["parent_search"])
            ref = self.identifier(row, f"search-{s['query_index']}-{s['page']}")
            existing = self.store.rows(
                "SELECT * FROM literature_actions WHERE request_id=?", (ref,)
            )
            if not existing:
                self.idle(run)
                self.literature.submit(
                    run,
                    ref,
                    req,
                    background_context={
                        "seed_id": seed,
                        "purpose": "seed" if seed else "orientation",
                        "plan_ref": s["plan_ref"],
                        "query_index": s["query_index"],
                    },
                )
            output = self.perform(row, self.literature, ref, req)
            if output:
                a = output["acquisition"]
                if a["status"] == "failed":
                    raise LocalProblem("retrieval_failed; not absence_of_evidence")
                known = {x["source_ref"] for x in s["sources"]}
                for item in a.get("items", []):
                    if item["source_ref"] not in known:
                        s["sources"].append({**item, "search_ref": ref})
                        known.add(item["source_ref"])
                if a.get("next_cursor") and s["page"] + 1 < c["pages_per_query"]:
                    s.update(cursor=a["next_cursor"], parent_search=ref, page=s["page"] + 1)
                else:
                    with self.store.db:
                        self.event(
                            run,
                            seed,
                            "query_finished",
                            {
                                "request_id": ref,
                                "pagination_complete": a.get("pagination_complete"),
                                "unvisited_cursor": a.get("next_cursor"),
                                "stop": "page_limit"
                                if a.get("next_cursor")
                                else "provider_page_end",
                            },
                        )
                    s.update(
                        query_index=s["query_index"] + 1, page=0, cursor=None, parent_search=None
                    )
        elif phase in ("abstract", "fulltext"):
            sources = s["sources"] if phase == "abstract" else s["selected"]
            if s["source_index"] >= len(sources):
                s.update(phase="select" if phase == "abstract" else "read", view_index=0)
                return
            source = sources[s["source_index"]]
            ref = self.identifier(row, phase + "-" + source["source_ref"])
            req = {
                "kind": "fetch",
                "source_ref": source["source_ref"],
                "desired_access": "abstract" if phase == "abstract" else "full_text",
                "search_request_id": source["search_ref"],
            }
            output = self.perform(row, self.literature, ref, req)
            if output:
                a = output["acquisition"]
                task = self.store.one(
                    "SELECT task_id FROM literature_actions WHERE request_id=?", (ref,)
                )["task_id"]
                if a.get("text") and a.get("access") in ("abstract", "full_text"):
                    if phase == "abstract":
                        view = self.ensure_view(run, task, 0, len(a["text"]), seed)
                        s["abstracts"].append({"view_id": view["id"], **source})
                    else:
                        s.setdefault("views", [])
                        total = len(a["text"])
                        covered = min(total, c["segment_characters"] * c["max_segments_per_source"])
                        for start in range(0, covered, c["segment_characters"]):
                            view = self.ensure_view(
                                run,
                                task,
                                start,
                                min(start + c["segment_characters"], covered),
                                seed,
                            )
                            if view["id"] not in s["views"]:
                                s["views"].append(view["id"])
                        with self.store.db:
                            self.event(
                                run,
                                seed,
                                "material_coverage",
                                {
                                    "source_ref": source["source_ref"],
                                    "access": a["access"],
                                    "covered_range": [0, covered],
                                    "obtained_characters": total,
                                    "unread_range": [covered, total] if covered < total else [],
                                    "images_seen": False,
                                    "limitation": a.get("limitation"),
                                    "reuse": output.get("reuse"),
                                },
                            )
                else:
                    with self.store.db:
                        self.event(
                            run,
                            seed,
                            "material_unavailable",
                            {
                                "source_ref": source["source_ref"],
                                "reason": a.get("limitation") or a.get("error"),
                                "abstract_screened": False,
                            },
                        )
                s["source_index"] += 1
        elif phase == "select":
            if not s["abstracts"]:
                s.update(phase="synthesize", reading_refs=[])
                return
            _, output = self.background_call(
                row,
                "relevance",
                "ABSTRACT_SELECT",
                {**scoped, "view_ids": [v["view_id"] for v in s["abstracts"]]},
            )
            if output:
                included = {
                    x["view_id"]
                    for x in output["artifact"]["decisions"]
                    if x["decision"] == "include"
                }
                selected = [v for v in s["abstracts"] if v["view_id"] in included]
                # Relevance is model-owned; a deterministic resource cap is an explicit omission, not exclusion.
                with self.store.db:
                    self.event(
                        run,
                        seed,
                        "relevance_selection",
                        {
                            "decisions": output["artifact"]["decisions"],
                            "resource_omissions": [
                                v["source_ref"] for v in selected[c["sources_per_round"] :]
                            ],
                            "ordering": "provider order among relevance-included only; no quality rank",
                        },
                    )
                s.update(
                    selected=selected[: c["sources_per_round"]],
                    source_index=0,
                    views=[],
                    phase="fulltext",
                )
        elif phase == "read":
            views = s.get("views", [])
            if s["view_index"] >= len(views):
                s["phase"] = "synthesize"
                return
            ref, output = self.background_call(
                row,
                "read-" + views[s["view_index"]],
                "P04",
                {**scoped, "view_id": views[s["view_index"]]},
            )
            if output:
                s.setdefault("reading_refs", []).append(ref)
                s["view_index"] += 1
        elif phase == "synthesize":
            eligible = [
                a["request_id"]
                for a in self.background.successful(run, "P04")
                if a["seed_id"] in (None, seed)
            ]
            if not eligible:
                raise LocalProblem("no_readable_relevant_material; not scientific rejection")
            ref, output = self.background_call(
                row, "packet", "P05", {**scoped, "reading_refs": eligible, "omitted_readings": {}}
            )
            if output:
                s["packet_ref"] = ref
                if seed:
                    s["phase"] = "readiness"
                else:
                    s.update(orientation_ref=ref, phase="seeds_directed")
        elif phase.startswith("seeds_"):
            directed = phase == "seeds_directed"
            count = c["directed_count" if directed else "open_count"]
            if count:
                _, output = self.background_call(
                    row,
                    phase,
                    "P06_DIRECTED" if directed else "P06_OPEN",
                    {"orientation_ref": s["orientation_ref"], "count": count},
                )
                if not output:
                    return
                s["seeds"].extend(output["artifact"]["seeds"])
            if directed:
                s["phase"] = "seeds_open"
            else:
                self.next_seed(row)
        elif phase == "readiness":
            ref, output = self.background_call(
                row,
                "readiness",
                "P07",
                {
                    **scoped,
                    "packet_ref": s["packet_ref"],
                    "requested_specificity": "Conditional mechanistic conjecture within traceable contexts; unknown bridges need not be proven",
                },
            )
            if output:
                a = output["artifact"]
                s["readiness_ref"] = ref
                with self.store.db:
                    self.event(
                        run,
                        seed,
                        "readiness_saved",
                        {
                            "ref": ref,
                            "decision": a["decision"],
                            "premise_gaps": a["premise_gaps"],
                            "hypothetical_unknowns": a["hypothetical_unknowns"],
                            "focused_followups": a["focused_followups"],
                            "allowed_specificity": a["allowed_specificity"],
                        },
                    )
                if a["decision"] == "ready":
                    s.update(
                        phase="generate",
                        candidate_index=0,
                        mode_index=0,
                        modes=["DIRECT", "ASSUMPTION_STRUCTURED"]
                        if c["mode"] == "Both"
                        else [c["mode"]],
                    )
                elif a["decision"] == "retrieve_more" and all(f.get("resolution_kind") == "experiment" for f in a["focused_followups"]):
                    self.next_seed(row, "gap_requires_future_experiment; not scientific rejection")
                elif a["decision"] == "retrieve_more" and s["round"] < c["max_followup_rounds"]:
                    s.update(followup_ref=ref, round=s["round"] + 1, phase="plan")
                    self.clear_round(s)
                else:
                    self.next_seed(
                        row,
                        "followup_limit"
                        if a["decision"] == "retrieve_more"
                        else "unable_to_prepare",
                    )
        elif phase == "generate":
            ref = self.identifier(row, f"candidate-{s['candidate_index']}-{s['mode_index']}")
            req = {
                "seed_id": seed,
                "readiness_ref": s["readiness_ref"],
                "packet_ref": s["packet_ref"],
                "mode": s["modes"][s["mode_index"]],
                "candidate_id": ref,
            }
            output = self.perform(row, self.generation, ref, req)
            if output:
                if output.get("generation_status") != "generated":
                    raise LocalProblem("generation_invalid_or_failed")
                s.update(generation_ref=ref, phase="ethics")
        elif phase in ("ethics", "r0"):
            op = "P09" if phase == "ethics" else "P10"
            req = {
                "operation": op,
                "generation_ref": s["generation_ref"],
                "policy": row["policies"]["candidate" if phase == "ethics" else "r0"],
            }
            if phase == "ethics":
                req.update(
                    intended_use=self.background.goal(run).get("intended_use"),
                    decision_policy=row["policies"]["decision_policy"],
                )
            else:
                req["ethics_ref"] = s["ethics_ref"]
            ref = self.identifier(row, op + "-" + s["generation_ref"])
            output = self.perform(row, self.reviews, ref, req)
            if output:
                if output.get("review_status") != "completed":
                    raise LocalProblem("review_incomplete_or_invalid")
                if (
                    phase == "ethics"
                    and output["artifact"]["decision_per_approved_policy"] == "pass"
                ):
                    s.update(ethics_ref=ref, phase="r0")
                else:
                    with self.store.db:
                        self.event(
                            run,
                            seed,
                            "candidate_boundary",
                            {
                                "generation_ref": s["generation_ref"],
                                "operation": op,
                                "artifact": output["artifact"],
                                "science_validated": False,
                            },
                        )
                    s["mode_index"] += 1
                    if s["mode_index"] >= len(s["modes"]):
                        s["mode_index"] = 0
                        s["candidate_index"] += 1
                    if s["candidate_index"] >= c["candidates_per_mode"]:
                        self.next_seed(row)
                    else:
                        s["phase"] = "generate"

    def ensure_view(self, run, task, start, end, seed):
        for view in self.background.views(run):
            if (
                view["acquisition_task_id"] == task
                and view["seed_id"] == seed
                and view["character_range"] == [start, end]
            ):
                return view
        return self.background.create_view(
            run,
            task,
            start=start,
            end=end,
            seed_id=seed,
            reason="Automatic contiguous character segmentation; explicit range, images/supplements not read",
        )

    def start_worker(self, write_lock):
        def work():
            while not self.stop_event.wait(0.25):
                if not write_lock.acquire(blocking=False):
                    continue
                try:
                    runs = self.store.rows(
                        "SELECT run_id FROM research_runs WHERE status='running' ORDER BY created_at"
                    )
                    for row in runs:
                        try:
                            self.tick(row["run_id"])
                        except Exception as exc:  # noqa: BLE001 -- safe persisted category, never raw provider text
                            with self.store.db:
                                self.store.db.execute("UPDATE research_runs SET status='blocked',reason=? WHERE run_id=?", ("controller_error:" + type(exc).__name__, row["run_id"]))
                                self.event(row["run_id"], None, "controller_error", {"category": type(exc).__name__, "automatic_retry": False})
                finally:
                    write_lock.release()

        self.thread = Thread(target=work, daemon=True, name="research-controller")
        self.thread.start()
