"""Automatic research engineering fixtures; no real requests or scientific validation."""

import runpy
from pathlib import Path

from co_scientist_next.background import BackgroundService
from co_scientist_next.background_ops import DevelopmentReadingAdapter
from co_scientist_next.candidate_review import CandidateReviewService
from co_scientist_next.candidate_review_ops import (
    DEVELOPMENT_DECISIONS,
    DEVELOPMENT_POLICY,
    DEVELOPMENT_R0_POLICY,
    DevelopmentReviewAdapter,
)
from co_scientist_next.generation import GenerationService
from co_scientist_next.generation_ops import DevelopmentGenerationAdapter
from co_scientist_next.goal import DEVELOPMENT_POLICY as GOAL_POLICY
from co_scientist_next.goal import DevelopmentAdapter, GoalSlice
from co_scientist_next.literature_runtime import LiteratureService
from co_scientist_next.research import ResearchController
from co_scientist_next.store import Store

FixtureTransport = runpy.run_path(str(Path(__file__).with_name("test_literature_acquisition.py")))[
    "FixtureTransport"
]
POLICIES = {
    "goal": GOAL_POLICY,
    "candidate": DEVELOPMENT_POLICY,
    "decision_policy": DEVELOPMENT_DECISIONS,
    "r0": DEVELOPMENT_R0_POLICY,
}


def controller(store, reading=None, transport=None):
    c = ResearchController(
        store,
        GoalSlice(store, DevelopmentAdapter(), development_test=True),
        BackgroundService(store, reading or DevelopmentReadingAdapter()),
        LiteratureService(store, enabled=True, transport=transport or FixtureTransport()),
        GenerationService(store, DevelopmentGenerationAdapter()),
        CandidateReviewService(store, DevelopmentReviewAdapter(), development=True),
    )
    c.initialize()
    return c


def start(c, key="offline-start-one", **config):
    s = c.store
    revision = s.revise_brief(
        s.create_project("OFFLINE arbitrary plant question"),
        {
            "question": "How does light affect flowering?",
            "research_focus": "Timing",
            "objectives": "Explore mechanisms",
            "intended_use": "Nonclinical conceptual reading and methods development only",
        },
    )
    return c.start(revision, key, config, POLICIES)


def drain(c, run):
    for _ in range(500):
        if c.row(run)["status"] != "running":
            break
        c.tick(run)
    return c.row(run)


def test_start_runs_full_chain_and_both_counts(tmp_path):
    with Store(tmp_path / "auto.sqlite") as s:
        c = controller(s)
        run = start(c, directed_count=1, open_count=1, mode="Both", candidates_per_mode=2)
        row = drain(c, run)
        assert row["status"] == "completed", row
        assert len(c.generation.actions(run)) == 8, row
        assert len(c.reviews.actions(run)) == 16
        assert len(c.background.seeds(run)) == 2
        assert all(
            a["result"]["generation_status"] == "generated" for a in c.generation.actions(run)
        )
        before = len(s.rows("SELECT * FROM attempts"))
        c.tick(run)
        assert len(s.rows("SELECT * FROM attempts")) == before


def test_restart_success_replay_library_reuse_and_seed_binding(tmp_path):
    import json

    path = tmp_path / "persist.sqlite"
    transport = FixtureTransport()
    with Store(path) as s:
        c = controller(s, transport=transport)
        run = start(c, directed_count=1, open_count=0)
        for _ in range(18):
            c.tick(run)
        before = s.rows("SELECT id FROM attempts")
    with Store(path) as s:
        c = controller(s, transport=transport)
        assert drain(c, run)["status"] == "completed"
        assert all(s.rows("SELECT id FROM attempts WHERE id=?", (a["id"],)) for a in before)
        fetch_before = sum(
            "/article/" in x["url"] or "/fullTextXML" in x["url"] for x in transport.sends
        )
        other = start(c, key="offline-start-two", directed_count=1, open_count=0)
        assert drain(c, other)["status"] == "completed"
        assert (
            sum("/article/" in x["url"] or "/fullTextXML" in x["url"] for x in transport.sends)
            == fetch_before
        )
        reused = [a for a in c.literature.history(other) if a["request"]["kind"] == "fetch"]
        assert all(a["result"]["reuse"] and not a["attempts"] for a in reused)
        first = c.background.successful(run, "P04")
        second = c.background.successful(other, "P04")
        assert {a["task_id"] for a in first}.isdisjoint(a["task_id"] for a in second)
        assert all(a["input"]["source_view"]["run_id"] == other for a in second)
        assert all(
            json.loads(a["request"])["operation"] == "P04"
            for x in second
            for a in s.rows("SELECT request FROM attempts WHERE task_id=?", (x["task_id"],))
        )


def test_pause_resume_stop_and_uncertain_are_not_retried(tmp_path):
    import pytest

    from co_scientist_next.contracts import TransportUncertain

    class Lost(DevelopmentReadingAdapter):
        def __call__(self, request):
            raise TransportUncertain("connection", "response_headers", "ECONNRESET")

    with Store(tmp_path / "control.sqlite") as s:
        c = controller(s, reading=Lost())
        run = start(c, directed_count=1, open_count=0)
        c.control(s.db, run, "pause")
        for _ in range(4):
            c.tick(run)
        assert not s.rows("SELECT * FROM attempts")
        c.control(s.db, run, "resume")
        assert drain(c, run)["status"] == "blocked"
        attempts = s.rows("SELECT * FROM attempts WHERE status='uncertain'")
        assert len(attempts) == 1
        for _ in range(4):
            c.tick(run)
        assert len(s.rows("SELECT * FROM attempts WHERE status='uncertain'")) == 1
        with pytest.raises(ValueError):
            c.control(s.db, run, "resume")
        another = start(c, key="offline-stop-one")
        c.control(s.db, another, "stop")
        c.tick(another)
        assert not [t for t in s.tasks(another) if t["status"] != "ready"]


def test_one_seed_problem_does_not_block_sibling_and_nonpass_no_r0(tmp_path):
    import json

    from co_scientist_next.contracts import CallResponse
    from co_scientist_next.store import encode

    class Selective(DevelopmentReadingAdapter):
        def __call__(self, req):
            p = json.loads(req["messages"][-1]["content"])
            if req["operation"] == "P07" and p["seed_brief"]["kind"] == "directed":
                req = {**req, "fixture_scenario": "unable_to_prepare"}
            return super().__call__(req)

    class Reject(DevelopmentReviewAdapter):
        def __call__(self, req):
            response = super().__call__(req)
            value = json.loads(response.output["raw_response"])
            if req["operation"] == "P09":
                value["decision_per_approved_policy"] = "reject"
            return CallResponse({"raw_response": encode(value), "fixture": True})

    with Store(tmp_path / "siblings.sqlite") as s:
        c = controller(s, reading=Selective())
        c.reviews.adapter = Reject()
        run = start(c)
        assert drain(c, run)["status"] == "completed"
        seeds = c.background.seeds(run)
        assert len(c.generation.actions(run)) == 1
        assert c.generation.actions(run)[0]["request"]["seed_id"] == next(
            x["id"] for x in seeds if x["kind"] == "open"
        )
        assert all(a["operation"] == "P09" for a in c.reviews.actions(run))


def test_limits_no_automatic_ready_and_atomic_start(tmp_path):
    import sqlite3

    import pytest

    with Store(tmp_path / "limits.sqlite") as s:
        c = controller(s)
        run = start(c, max_model_calls=1)
        row = drain(c, run)
        assert row["status"] == "blocked" and row["reason"] == "resource_limit:model_calls"
        assert len(s.rows("SELECT * FROM attempts")) == 1
        assert not c.generation.actions(run)
        revision = s.revise_brief(s.create_project("Atomic"), {"question": "Atomic question"})
        before = len(s.rows("SELECT * FROM runs"))
        s.db.execute(
            "CREATE TRIGGER crash_start BEFORE INSERT ON research_runs BEGIN SELECT RAISE(ABORT,'offline interrupted transaction'); END"
        )
        with pytest.raises(sqlite3.IntegrityError):
            c.start(revision, "atomic-start-key", {}, POLICIES)
        assert len(s.rows("SELECT * FROM runs")) == before
        s.db.execute("DROP TRIGGER crash_start")
        r = c.start(revision, "atomic-start-key", {}, POLICIES)
        assert c.start(revision, "atomic-start-key", {}, POLICIES) == r
        assert (
            len(s.rows("SELECT * FROM research_runs WHERE start_key=?", ("atomic-start-key",))) == 1
        )


def test_followup_ready_no_progress_and_long_range(tmp_path):
    class Follow(DevelopmentReadingAdapter):
        def __init__(self, always=False):
            super().__init__()
            self.n = 0
            self.always = always

        def __call__(self, req):
            if req["operation"] == "P07":
                self.n += 1
                req = {
                    **req,
                    "fixture_scenario": "retrieve_more" if self.n == 1 or self.always else "ready",
                }
            return super().__call__(req)

    with Store(tmp_path / "follow.sqlite") as s:
        c = controller(s, reading=Follow())
        run = start(
            c, directed_count=1, open_count=0, segment_characters=25, max_segments_per_source=1
        )
        row = drain(c, run)
        assert row["status"] == "completed", row
        records = c.background.successful(run, "P07")
        # No changed content cannot become ready just because a second fixture would say so.
        assert records[0]["result"]["artifact"]["decision"] == "retrieve_more"
        assert not c.generation.actions(run)
        assert any(a["input"].get("focused_followups") for a in c.background.successful(run, "P03"))
        views = c.background.views(run)
        assert any(v["cropped"] and v["not_read_ranges"] for v in views)
        assert all(
            v["text"] and len(v["text"]) == v["character_range"][1] - v["character_range"][0]
            for v in views
        )
        from co_scientist_next.research_view import workspace

        projection = workspace(s, run)
        assert projection["counts"]["reading_records"] == len(c.background.successful(run, "P04"))
        assert (
            projection["counts"]["unique_source_identifiers"]
            < projection["counts"]["material_views"]
        )


def test_substantive_new_reading_allows_followup_ready(tmp_path):
    import json

    from co_scientist_next.contracts import CallResponse
    from co_scientist_next.store import encode

    class NewInformation(DevelopmentReadingAdapter):
        def __init__(self):
            super().__init__()
            self.checks = 0
            self.reads = 0

        def __call__(self, req):
            if req["operation"] == "P07":
                self.checks += 1
                req = {**req, "fixture_scenario": "retrieve_more" if self.checks == 1 else "ready"}
            response = super().__call__(req)
            if req["operation"] == "P04":
                self.reads += 1
                value = json.loads(response.output["raw_response"])
                for card in value["finding_cards"]:
                    card["not_established"].append(
                        "OFFLINE newly extracted scope detail " + str(self.reads)
                    )
                return CallResponse({"raw_response": encode(value), "fixture": True})
            return response

    with Store(tmp_path / "changed.sqlite") as s:
        c = controller(s, reading=NewInformation())
        run = start(c, directed_count=1, open_count=0)
        assert drain(c, run)["status"] == "completed"
        assert [
            a["result"]["artifact"]["decision"] for a in c.background.successful(run, "P07")
        ] == ["retrieve_more", "ready"]
        assert len(c.generation.actions(run)) == 1


def test_missing_abstract_and_unavailable_fulltext_are_explicit(tmp_path):
    for mode in ("no_abstract", "no_fulltext"):
        # Fixture has provider OA metadata altered; no live service.
        import json

        from co_scientist_next.contracts import CallResponse

        H = runpy.run_path(str(Path(__file__).with_name("test_literature_acquisition.py")))

        class Limited(FixtureTransport):
            def __call__(self, req, mode=mode, H=H):
                if "/article/" in req["url"]:
                    row = {**H["FIXTURE"]["article"]}
                    if mode == "no_abstract":
                        row.pop("abstractText", None)
                    else:
                        row["isOpenAccess"] = "N"
                    self.sends.append(req)
                    return CallResponse(H["envelope"](req, json.dumps({"result": row})))
                return super().__call__(req)

        with Store(tmp_path / (mode + ".sqlite")) as s:
            c = controller(s, transport=Limited())
            run = start(c, directed_count=1, open_count=0)
            row = drain(c, run)
            if mode == "no_abstract":
                assert row["status"] == "blocked"
                assert not c.background.successful(run, "ABSTRACT_SELECT")
                assert not c.generation.actions(run)
            else:
                assert row["status"] == "completed", row
                assert all(v["access"] == "abstract" for v in c.background.views(run))
                assert any(
                    a["result"]["acquisition"].get("limitation")
                    for a in c.literature.history(run)
                    if a["request"]["kind"] == "fetch"
                    and a["request"]["desired_access"] == "full_text"
                )


def test_cross_process_controller_resume_and_annotations_export(tmp_path):
    import os
    import subprocess
    import sys

    path = tmp_path / "process.sqlite"
    with Store(path) as s:
        c = controller(s)
        run = start(c, directed_count=1, open_count=0)
        for _ in range(15):
            c.tick(run)
        saved = s.rows("SELECT id FROM attempts")
    code = """
import runpy,sys
from co_scientist_next.store import Store
h=runpy.run_path('tests/next/test_research_controller.py')
with Store(sys.argv[1]) as s:
 c=h['controller'](s)
 assert h['drain'](c,sys.argv[2])['status']=='completed'
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(path), run],
        env={**os.environ, "PYTHONPATH": "src"},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    with Store(path) as s:
        from co_scientist_next.workspace_records import WorkspaceRecords

        x = WorkspaceRecords(s)
        target = x.targets(run)[0]
        x.save(
            run,
            {
                "target_kind": "run",
                "target_ref": run,
                "target_sha256": target["sha256"],
                "category": "note",
                "note": "OFFLINE independent critique",
                "observations": {},
            },
        )
        export = x.export(run)
        assert export["human_annotations"][0]["note"] == "OFFLINE independent critique"
        assert export["research_runs"] and export["research_events"]
        assert all(s.rows("SELECT id FROM attempts WHERE id=?", (a["id"],)) for a in saved)
        assert not s.rows(
            "SELECT task_id,call_key FROM attempts GROUP BY task_id,call_key HAVING COUNT(*)>1"
        )


def test_followup_reference_does_not_cross_seed(tmp_path):
    with Store(tmp_path / "isolation.sqlite") as store:
        c = controller(store)
        run = start(c)
        row = c.row(run)
        row["state"].update(
            seed_index=0, seed_id="first", seeds=[{"id": "first"}, {"id": "second"}],
            followup_ref="first-seed-only", round=1,
        )
        c.next_seed(row)
        assert row["state"]["seed_id"] == "second"
        assert "followup_ref" not in row["state"]
        assert row["state"]["round"] == 0
