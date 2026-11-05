"""OFFLINE P09/P10 engineering fixtures, never safety or scientific validation."""

import copy
import json
import os
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

from co_scientist_next.candidate_review import CandidateReviewService
from co_scientist_next.candidate_review_ops import (
    DEVELOPMENT_DECISIONS,
    DEVELOPMENT_POLICY,
    DEVELOPMENT_R0_POLICY,
    DevelopmentReviewAdapter,
    parse_review,
)
from co_scientist_next.generation import GenerationService
from co_scientist_next.generation_ops import DevelopmentGenerationAdapter
from co_scientist_next.store import Store, encode

H = runpy.run_path(str(Path(__file__).with_name("test_generation.py")))
R = runpy.run_path(str(Path(__file__).with_name("test_responses_background.py")))


def generated(store):
    run, _, request = H["prepared"](store)
    g = GenerationService(store, DevelopmentGenerationAdapter())
    g.submit(run, "offline-review-candidate", request)
    g.execute("offline-review-candidate")
    return run


def p09(**changes):
    return {
        "operation": "P09",
        "generation_ref": "offline-review-candidate",
        "intended_use": "OFFLINE conceptual nonclinical test",
        "policy": copy.deepcopy(DEVELOPMENT_POLICY),
        "decision_policy": copy.deepcopy(DEVELOPMENT_DECISIONS),
        **changes,
    }


def p10(ethics="offline-review-p09", **changes):
    return {
        "operation": "P10",
        "generation_ref": "offline-review-candidate",
        "ethics_ref": ethics,
        "policy": copy.deepcopy(DEVELOPMENT_R0_POLICY),
        **changes,
    }


def finish(g, run, ref, request):
    g.submit(run, ref, request)
    g.execute(ref)
    return g.action(run, ref)


@pytest.mark.parametrize(
    "scenario,decision",
    [
        ("pass", "pass"),
        ("reject", "reject"),
        ("incomplete", "incomplete"),
        ("invalid", None),
        ("failed", None),
        ("uncertain", None),
    ],
)
def test_ethics_branches_pass_only_and_distinct_execution_errors(tmp_path, scenario, decision):
    with Store(tmp_path / "fixture.sqlite") as s:
        run = generated(s)
        g = CandidateReviewService(s, DevelopmentReviewAdapter(scenario), development=True)
        a = finish(g, run, "offline-review-p09", p09())
        if decision:
            assert a["result"]["artifact"]["decision_per_approved_policy"] == decision
        else:
            assert not a["result"] or a["result"]["review_status"] != "completed"
        if decision == "pass":
            b = finish(g, run, "offline-review-p10", p10())
            assert b["result"]["artifact"]["disposition"] == "proceed_to_R1"
            assert s.run(run)["status"] == "awaiting_r1"
        else:
            with pytest.raises((ValueError, KeyError)):
                g.submit(run, "offline-forbidden-p10", p10())
            assert not s.rows("SELECT id FROM tasks WHERE module='candidate_review.P10'")
        assert not s.rows("SELECT id FROM tasks WHERE module LIKE '%R1%'")


def test_missing_policy_not_configured_and_no_production_default(tmp_path):
    with Store(tmp_path / "fixture.sqlite") as s:
        run = generated(s)
        g = CandidateReviewService(s, DevelopmentReviewAdapter(), development=True)
        a = finish(g, run, "offline-missing-policy", p09(policy=None))
        assert a["result"]["review_status"] == "policy_not_configured" and not a["attempts"]
        with pytest.raises(ValueError, match="production"):
            g.submit(
                run,
                "offline-no-prod-fake",
                p09(policy={**DEVELOPMENT_POLICY, "mode": "production"}),
            )
        with pytest.raises(ValueError, match="Development policy"):
            CandidateReviewService(s).submit(run, "offline-explicit-dev", p09())


def test_frozen_scope_identity_input_isolation_and_replay(tmp_path):
    with Store(tmp_path / "fixture.sqlite") as s:
        run = generated(s)
        g = CandidateReviewService(s, DevelopmentReviewAdapter(), development=True)
        a = finish(g, run, "offline-review-p09", p09())
        before = len(s.rows("SELECT id FROM attempts"))
        tasks = len(s.tasks(run))
        assert g.submit(run, a["request_id"], p09())["task_id"] == a["task_id"]
        g.execute(a["request_id"])
        assert len(s.rows("SELECT id FROM attempts")) == before and len(s.tasks(run)) == tasks
        assert set(a["input"]) == {
            "goal_context",
            "fixed_candidate",
            "goal_ethics_record",
            "intended_use",
            "approved_policy_id",
            "approved_policy_text",
            "candidate_ethics_decision_policy",
        }
        for change in [
            p09(intended_use="different"),
            p09(policy={**DEVELOPMENT_POLICY, "version": "2"}),
            p09(expected="answer"),
        ]:
            with pytest.raises(ValueError):
                g.submit(run, a["request_id"], change)
        with pytest.raises(KeyError):
            g.submit("wrong-run", "offline-other-run", p10())
        b = g.submit(run, "offline-review-p10", p10())
        payload = json.loads(b["input"])
        assert set(payload) == {
            "goal_context",
            "fixed_candidate",
            "passed_candidate_ethics_record",
            "actual_visible_source_views",
            "r0_policy_version",
        }
        assert all(v["text"] and v["access"] for v in payload["actual_visible_source_views"])
        assert "expected" not in payload and "REVIEW" not in payload
        with s.db:
            original = s.one(
                "SELECT output FROM results WHERE task_id=?",
                (
                    s.one(
                        "SELECT task_id FROM generation_actions WHERE request_id=?",
                        (p09()["generation_ref"],),
                    )["task_id"],
                ),
            )
            result = json.loads(original["output"])
            result["candidate"]["title"] = "OFFLINE illicit content mutation"
            s.db.execute(
                "UPDATE results SET output=? WHERE output=?", (encode(result), original["output"])
            )
        with pytest.raises(ValueError, match="same-candidate"):
            g.execute(b["request_id"])


def r0_output(payload):
    return {
        "candidate_id": payload["fixed_candidate"]["candidate_id"],
        "disposition": "proceed_to_R1",
        "goal_alignment": "OFFLINE goal check",
        "blocking_defects": [],
        "scientific_unknowns": ["Unknown bridge"],
        "required_R1_checks": ["Check local wording, dispute and intervention validity"],
        "limitations": ["Engineering fixture only"],
    }


@pytest.mark.parametrize("category", ["source_direct_contradiction", "core_factual_error"])
def test_core_factual_block_requires_actual_visible_original_locator(tmp_path, category):
    with Store(tmp_path / "fixture.sqlite") as s:
        run = generated(s)
        g = CandidateReviewService(s, DevelopmentReviewAdapter(), development=True)
        finish(g, run, "offline-review-p09", p09())
        a = g.submit(run, "offline-review-p10", p10())
        payload = json.loads(a["input"])
        view = payload["actual_visible_source_views"][0]
        candidate_span = payload["fixed_candidate"]["scoped_claim"]
        out = r0_output(payload)
        out.update(
            disposition="blocked",
            blocking_defects=[
                {
                    "category": category,
                    "candidate_path": "/scoped_claim",
                    "candidate_span": candidate_span,
                    "defect": "OFFLINE manufactured core error used only to test locator contract",
                    "actual_visible_basis": {
                        "source_view_ref": view["id"],
                        "start": 0,
                        "end": 8,
                        "quote": view["text"][:8],
                        "access": view["access"],
                        "reliability_reason": "OFFLINE actual original view; truth assessment is not tested here",
                    },
                    "why_indispensable": "OFFLINE counterexample asserted core necessity, not scientific validation",
                }
            ],
        )
        assert parse_review(encode(out), "P10", payload, p10())["disposition"] == "blocked"
        for bad in ["wrong quote", "model memory"]:
            changed = copy.deepcopy(out)
            changed["blocking_defects"][0]["actual_visible_basis"]["quote"] = bad
            with pytest.raises(ValueError, match="paraphrase"):
                parse_review(encode(changed), "P10", payload, p10())
        assistant = copy.deepcopy(payload)
        assistant["actual_visible_source_views"][0]["source_origin"] = "assistant_paraphrase"
        with pytest.raises(ValueError, match="paraphrase"):
            parse_review(encode(out), "P10", assistant, p10())
        assert (
            parse_review(encode(r0_output(payload)), "P10", payload, p10())["disposition"]
            == "proceed_to_R1"
        )
        for forbidden_category in [
            "scientific_unknown",
            "local_wording_error",
            "weak_evidence",
            "unknown_novelty",
            "unimplemented_tool",
            "disputed_transfer",
        ]:
            invalid = copy.deepcopy(out)
            invalid["blocking_defects"][0]["category"] = forbidden_category
            with pytest.raises(ValueError, match="not an R0 blocking"):
                parse_review(encode(invalid), "P10", payload, p10())


def test_cross_process_saved_success_replay_no_adapter_sends(tmp_path):
    db = tmp_path / "fixture.sqlite"
    with Store(db) as s:
        run = generated(s)
        g = CandidateReviewService(s, DevelopmentReviewAdapter(), development=True)
        finish(g, run, "offline-review-p09", p09())
        finish(g, run, "offline-review-p10", p10())
        count = len(s.rows("SELECT id FROM attempts"))
    code = """
import sys
from co_scientist_next.store import Store
from co_scientist_next.candidate_review import CandidateReviewService
with Store(sys.argv[1]) as s:
 g=CandidateReviewService(s,development=True)
 g.execute('offline-review-p09');g.execute('offline-review-p10')
 assert len(s.rows('SELECT id FROM attempts'))==int(sys.argv[2])
 print('Saved P09/P10 replayed in new process with NO adapter')
"""
    p = subprocess.run(
        [sys.executable, "-c", code, str(db), str(count)],
        env={**os.environ, "PYTHONPATH": "src"},
        capture_output=True,
        text=True,
        check=True,
    )
    assert "NO adapter" in p.stdout


def test_responses_queued_same_id_completion_and_no_refresh_send(tmp_path, monkeypatch):
    import urllib.request

    from co_scientist_next.responses_model import OpenAIResponses

    wire = R["Wire"]([R["envelope"]("queued")])
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_: wire)
    with Store(tmp_path / "fixture.sqlite") as s:
        run = generated(s)
        adapter = OpenAIResponses(R["CONFIG"], R["SECRET"], authorized=True)
        g = CandidateReviewService(s, adapter, development=True)
        a = g.submit(run, "offline-remote-review", p09())
        output = DevelopmentReviewAdapter()(
            {
                "operation": "P09",
                "messages": g.messages(json.loads(a["input"]), a["prompt_version"]),
            }
        )
        g.execute(a["request_id"])
        assert g.snapshot(run)["actions"][-1]["remote"]["response_id"] == "resp_OFFLINE1"
        g.execute(a["request_id"])
        assert len(wire.sent) == 1
        wire.responses.append(R["envelope"]("completed", output.output["raw_response"]))
        g.query_remote(a["request_id"])
        assert (
            g.action(run, a["request_id"])["result"]["artifact"]["decision_per_approved_policy"]
            == "pass"
        )
        assert [r[0] for r in wire.sent] == ["POST", "GET"]
        assert len(s.rows("SELECT * FROM remote_generations")) == 1


@pytest.mark.parametrize(
    "terminal,body",
    [
        ("incomplete", None),
        ("failed", None),
        ("completed", ""),
        ("completed", "{"),
        ("completed", '{"candidate_id":"foreign"}'),
    ],
)
def test_remote_invalid_or_truncated_review_never_forms_ethics_decision(
    tmp_path, monkeypatch, terminal, body
):
    import urllib.request

    from co_scientist_next.responses_model import OpenAIResponses

    wire = R["Wire"]([R["envelope"](terminal, body)])
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_: wire)
    with Store(tmp_path / "fixture.sqlite") as s:
        run = generated(s)
        g = CandidateReviewService(
            s, OpenAIResponses(R["CONFIG"], R["SECRET"], authorized=True), development=True
        )
        a = finish(g, run, "offline-terminal-review", p09())
        assert a["result"]["review_status"] == "invalid_output" and "artifact" not in a["result"]
        assert a["remote"]["status"] == terminal and len(wire.sent) == 1
        with pytest.raises(ValueError):
            g.submit(run, "offline-no-r0-after-bad", p10(ethics=a["request_id"]))


def test_remote_submit_uncertainty_and_query_failure_do_not_post_again(tmp_path, monkeypatch):
    import urllib.request

    from co_scientist_next.responses_model import OpenAIResponses

    wire = R["Wire"]([ConnectionResetError()])
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_: wire)
    with Store(tmp_path / "fixture.sqlite") as s:
        run = generated(s)
        g = CandidateReviewService(
            s, OpenAIResponses(R["CONFIG"], R["SECRET"], authorized=True), development=True
        )
        a = finish(g, run, "offline-uncertain-review", p09())
        assert a["task_status"] == "blocked" and not a["remote"]
        g.execute(a["request_id"], recover=True)
        assert len(wire.sent) == 1 and a["attempts"][0]["status"] == "uncertain"
    wire = R["Wire"]([R["envelope"]("queued"), ConnectionResetError()])
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_: wire)
    with Store(tmp_path / "query.sqlite") as s:
        run = generated(s)
        g = CandidateReviewService(
            s, OpenAIResponses(R["CONFIG"], R["SECRET"], authorized=True), development=True
        )
        a = finish(g, run, "offline-query-failure", p09())
        g.query_remote(a["request_id"])
        a = g.action(run, a["request_id"])
        assert (
            a["remote"]["response_id"] == "resp_OFFLINE1"
            and a["remote"]["latest_query"]["outcome"] == "query_failed"
        )
        g.execute(a["request_id"])
        assert [x[0] for x in wire.sent] == ["POST", "GET"]


def test_missing_decision_policy_never_sends_and_custom_policy_routes_are_explicit(tmp_path):
    class NeverSend(DevelopmentReviewAdapter):
        def __call__(self, request):
            raise AssertionError("Policy missing; send forbidden")

    with Store(tmp_path / "fixture.sqlite") as s:
        run = generated(s)
        g = CandidateReviewService(s, NeverSend(), development=True)
        a = finish(g, run, "offline-no-decision-policy", p09(decision_policy=None))
        assert a["result"]["review_status"] == "policy_not_configured" and not a["attempts"]
        for routes in [
            {"pass": "continue", "reject": "continue"},
            {"pass": "hold", "unknown": "hold"},
        ]:
            with pytest.raises(ValueError):
                g.submit(
                    run,
                    "offline-bad-decision-policy",
                    p09(decision_policy={**DEVELOPMENT_DECISIONS, "routes": routes}),
                )


def test_real_candidate_import_is_explicit_isolated_and_never_overwrites(tmp_path):
    from co_scientist_next.review_fixture import create_fixture

    trial = Path(__file__).resolve().parents[2] / "docs/trials/p08-direct-responses-real"
    db = tmp_path / "isolated.sqlite"
    metadata = create_fixture(db, trial)
    with pytest.raises(ValueError, match="NEW isolated"):
        create_fixture(db, trial)
    with Store(db) as s:
        g = CandidateReviewService(s, DevelopmentReviewAdapter(), development=True)
        request = p09(generation_ref=metadata["generation_ref"])
        a = finish(g, metadata["run_id"], "offline-import-p09", request)
        assert a["binding"]["candidate_sha256"] == metadata["candidate_sha256"]
        b = finish(
            g,
            metadata["run_id"],
            "offline-import-p10",
            p10(ethics="offline-import-p09", generation_ref=metadata["generation_ref"]),
        )
        assert b["result"]["development"] is True
        assert b["result"]["artifact"]["disposition"] == "proceed_to_R1"
        assert len(b["input"]["actual_visible_source_views"]) == 5
        with pytest.raises(ValueError, match="development review only"):
            g.submit(
                metadata["run_id"],
                "offline-production-import",
                {**request, "policy": {**DEVELOPMENT_POLICY, "mode": "production"}},
            )


def test_remote_query_in_new_process_never_recreates_post(tmp_path, monkeypatch):
    import urllib.request

    from co_scientist_next.responses_model import OpenAIResponses

    db = tmp_path / "fixture.sqlite"
    wire = R["Wire"]([R["envelope"]("queued")])
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_: wire)
    with Store(db) as s:
        run = generated(s)
        g = CandidateReviewService(
            s, OpenAIResponses(R["CONFIG"], R["SECRET"], authorized=True), development=True
        )
        a = g.submit(run, "offline-new-process-review", p09())
        output = DevelopmentReviewAdapter()(
            {
                "operation": "P09",
                "messages": g.messages(json.loads(a["input"]), a["prompt_version"]),
            }
        )
        g.execute(a["request_id"])
    code = """
import sys,runpy,urllib.request
from unittest.mock import patch
from co_scientist_next.store import Store
from co_scientist_next.candidate_review import CandidateReviewService
from co_scientist_next.responses_model import OpenAIResponses
r=runpy.run_path(sys.argv[2]);wire=r['Wire']([r['envelope']('completed',sys.argv[3])])
with patch.object(urllib.request,'build_opener',lambda *_:wire),Store(sys.argv[1]) as s:
 g=CandidateReviewService(s,OpenAIResponses(r['CONFIG'],r['SECRET'],authorized=True),development=True)
 g.query_remote('offline-new-process-review')
 assert [a[0] for a in wire.sent]==['GET']
 assert s.one("SELECT count(*) AS n FROM attempts WHERE call_key='responses.submit'")['n']==1
 print('OFFLINE new process uses saved ID and GET only')
"""
    p = subprocess.run(
        [
            sys.executable,
            "-c",
            code,
            str(db),
            str(Path(__file__).with_name("test_responses_background.py")),
            output.output["raw_response"],
        ],
        env={**os.environ, "PYTHONPATH": "src"},
        capture_output=True,
        text=True,
        check=True,
    )
    assert "GET only" in p.stdout


def test_concrete_false_core_counterexample_can_stop_r0_without_repair(tmp_path):
    """Deliberately FALSE new fixture candidate, NOT a verdict on the real DIRECT candidate."""
    from co_scientist_next.contracts import CallResponse
    from co_scientist_next.review_fixture import create_fixture

    root = Path(__file__).resolve().parents[2]
    source = root / "docs/trials/p08-direct-responses-real"
    trial = tmp_path / "false-core-counterexample"
    trial.mkdir()
    data = {
        name: json.loads((source / name).read_text())
        for name in [
            "frozen-input.json",
            "successor-action.json",
            "parsed-result.json",
            "candidate.json",
            "historical-before.json",
        ]
    }
    cid = "OFFLINE-FALSE-CORE-COUNTEREXAMPLE"
    false_claim = "The supplied TDP-43 source establishes that 12D cannot restore SKAR or Bim exon 3 splicing in the HeLa depletion/re-expression experiment. This failure is my indispensable core premise."
    data["candidate.json"].update(candidate_id=cid, scoped_claim=false_claim)
    data["parsed-result.json"]["candidate"] = data["candidate.json"]
    data["parsed-result.json"]["binding"]["candidate_id"] = cid
    data["frozen-input.json"]["candidate_id_from_caller"] = cid
    data["successor-action.json"]["candidate_id"] = cid
    source_request = json.loads(data["successor-action.json"]["request"])
    source_request["candidate_id"] = cid
    data["successor-action.json"]["request"] = encode(source_request)
    for name, value in data.items():
        (trial / name).write_text(encode(value))
    metadata = create_fixture(tmp_path / "fixture.sqlite", trial)

    class FalseCoreReviewer(DevelopmentReviewAdapter):
        def __call__(self, request):
            if request["operation"] == "P09":
                return super().__call__(request)
            payload = json.loads(request["messages"][-1]["content"])
            view = next(
                v
                for v in payload["actual_visible_source_views"]
                if v["source_ref"] == "epmc:MED:35112738"
            )
            quote = "splicing of\nSKAR\nand\nBim\nexon 3 were fully restored by all three TDP‐43 variants"
            start = view["text"].index(quote)
            result = r0_output(payload)
            result.update(
                disposition="blocked",
                blocking_defects=[
                    {
                        "category": "source_direct_contradiction",
                        "candidate_path": "/scoped_claim",
                        "candidate_span": false_claim,
                        "defect": "OFFLINE deliberately false core premise: source reports restoration, candidate asserts inability to restore in the same named experiment.",
                        "actual_visible_basis": {
                            "source_view_ref": view["id"],
                            "start": start,
                            "end": start + len(quote),
                            "quote": quote,
                            "access": view["access"],
                            "reliability_reason": "Obtained original Results text in precisely named HeLa depletion/re-expression experiment, not assistant memory.",
                        },
                        "why_indispensable": "This artificial candidate explicitly makes failure-to-restore its indispensable premise; without it the asserted candidate as written fails.",
                    }
                ],
            )
            return CallResponse({"raw_response": encode(result)})

    with Store(tmp_path / "fixture.sqlite") as s:
        g = CandidateReviewService(s, FalseCoreReviewer(), development=True)
        finish(
            g,
            metadata["run_id"],
            "offline-review-p09",
            p09(generation_ref=metadata["generation_ref"]),
        )
        before = g.candidate(metadata["run_id"], metadata["generation_ref"])[1]
        a = finish(
            g,
            metadata["run_id"],
            "offline-review-p10",
            p10(generation_ref=metadata["generation_ref"]),
        )
        assert a["result"]["artifact"]["disposition"] == "blocked"
        assert s.run(metadata["run_id"])["status"] == "candidate_r0_blocked"
        assert g.candidate(metadata["run_id"], metadata["generation_ref"])[1] == before
        count = len(s.tasks(metadata["run_id"]))
        assert (
            s.submit_result(a["task_id"], a["result"], stop_status="candidate_r0_blocked") is False
        )
        assert len(s.tasks(metadata["run_id"])) == count


def test_other_candidate_goal_and_policy_results_are_not_reusable(tmp_path):
    with Store(tmp_path / "fixture.sqlite") as s:
        run = generated(s)
        a = s.one("SELECT * FROM generation_actions WHERE request_id='offline-review-candidate'")
        request = {**json.loads(a["request"]), "candidate_id": "different-candidate"}
        gen = GenerationService(s, DevelopmentGenerationAdapter())
        gen.submit(run, "offline-second-candidate", request)
        gen.execute("offline-second-candidate")
        g = CandidateReviewService(s, DevelopmentReviewAdapter(), development=True)
        finish(g, run, "offline-review-p09", p09())
        with pytest.raises(ValueError, match="same-candidate"):
            g.submit(
                run, "offline-wrong-candidate-r0", p10(generation_ref="offline-second-candidate")
            )
        goal_id = s.run(run)["goal_context_ref"]
        goal = json.loads(
            s.one("SELECT content FROM goal_contexts WHERE id=?", (goal_id,))["content"]
        )
        with s.db:
            s.db.execute(
                "UPDATE goal_contexts SET content=? WHERE id=?",
                (encode({**goal, "original_question": "OFFLINE changed Goal"}), goal_id),
            )
        with pytest.raises(ValueError, match="binding"):
            g.execute("offline-review-p09")


def test_only_completed_generation_lineage_scopes_old_uncertain_not_global(tmp_path, monkeypatch):
    import urllib.request

    from co_scientist_next.generation_migration import ACKS, MigrationService
    from co_scientist_next.responses_model import OpenAIResponses
    from co_scientist_next.store import now

    migration_helpers = runpy.run_path(
        str(Path(__file__).with_name("test_generation_migration.py"))
    )
    wire = R["Wire"]([])
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_: wire)
    with Store(tmp_path / "fixture.sqlite") as s:
        run, _, old, req = migration_helpers["source_fixture"](s)
        original = migration_helpers["historical"](s, old["task_id"])
        m = MigrationService(s, R["CONFIG"])
        preview = m.preview(run, req)
        m.confirm(run, req, preview["preview_hash"], dict.fromkeys(ACKS, True))
        g = GenerationService(s, OpenAIResponses(R["CONFIG"], R["SECRET"], authorized=True))
        a = s.one("SELECT * FROM generation_actions WHERE request_id=?", (req["request_id"],))
        raw = DevelopmentGenerationAdapter()(
            {"messages": g.messages(json.loads(a["input"]))}
        ).output["raw_response"]
        wire.responses.append(R["envelope"]("completed", raw))
        g.execute(req["request_id"], authorize_migrated_execution=True)
        reviews = CandidateReviewService(s, DevelopmentReviewAdapter(), development=True)
        finish(reviews, run, "offline-review-p09", p09(generation_ref=req["request_id"]))
        assert migration_helpers["historical"](s, old["task_id"]) == original
        other_task = s.one(
            "SELECT id FROM tasks WHERE run_id=? AND module='goal.screen.v1'", (run,)
        )["id"]
        with s.db:
            s.db.execute(
                "INSERT INTO attempts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "offline-unrelated-uncertain",
                    other_task,
                    "unrelated",
                    "OFFLINE",
                    "{}",
                    1,
                    None,
                    "uncertain",
                    None,
                    None,
                    encode(
                        {
                            "cost": None,
                            "input_tokens": None,
                            "output_tokens": None,
                            "tool_units": None,
                        }
                    ),
                    now(),
                    None,
                    None,
                ),
            )
        with pytest.raises(ValueError, match="Other unresolved"):
            reviews.submit(run, "offline-forbidden-other", p10(generation_ref=req["request_id"]))
        assert not s.rows("SELECT request_id FROM candidate_review_actions WHERE operation='P10'")
        assert migration_helpers["historical"](s, old["task_id"]) == original


def test_unsent_export_is_readonly_complete_and_development_only(tmp_path):
    import hashlib

    from co_scientist_next.review_fixture import create_fixture

    root = Path(__file__).resolve().parents[2]
    db = tmp_path / "isolated.sqlite"
    meta = create_fixture(db, root / "docs/trials/p08-direct-responses-real")
    with Store(db) as s:
        g = CandidateReviewService(s, DevelopmentReviewAdapter(), development=True)
        finish(g, meta["run_id"], "offline-export-p09", p09(generation_ref=meta["generation_ref"]))
        finish(
            g,
            meta["run_id"],
            "offline-export-p10",
            p10(ethics="offline-export-p09", generation_ref=meta["generation_ref"]),
        )
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    out = tmp_path / "export"
    command = [
        sys.executable,
        "-m",
        "co_scientist_next.review_export",
        "--fixture-db",
        str(db),
        "--run-id",
        meta["run_id"],
        "--model-config",
        str(root / "docs/preparations/responses-background/model-config.json"),
        "--output",
        str(out),
    ]
    subprocess.run(
        command, env={**os.environ, "PYTHONPATH": "src"}, capture_output=True, text=True, check=True
    )
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before
    for op in ("P09", "P10"):
        exported = json.loads((out / (op + ".unsent-request.json")).read_text())
        payload = json.loads(exported["messages"][-1]["content"])
        assert payload["fixed_candidate"] == json.loads(
            (root / "docs/trials/p08-direct-responses-real/candidate.json").read_text()
        )
        assert not exported["model_config"]["credential_configured"]
        assert exported["actual_request"]["body"]["background"]
        assert "temperature" not in exported["actual_request"]["body"]
        if op == "P10":
            assert len(payload["actual_visible_source_views"]) == 5
            assert payload["passed_candidate_ethics_record"]["development"]
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["model_requests"] == 0 and not manifest["production_P10_executable"]


def test_r0_cannot_substitute_assistant_summary_for_actual_source_input(tmp_path):
    with Store(tmp_path / "fixture.sqlite") as s:
        run = generated(s)
        g = CandidateReviewService(s, DevelopmentReviewAdapter(), development=True)
        finish(g, run, "offline-review-p09", p09())
        action = s.one(
            "SELECT * FROM generation_actions WHERE request_id='offline-review-candidate'"
        )
        payload = json.loads(action["input"])
        for view in payload["actual_frozen_seed_background_packet"]["source_views"]:
            view["source_origin"] = "assistant_paraphrase"
        with s.db:
            s.db.execute(
                "UPDATE generation_actions SET input=? WHERE request_id=?",
                (encode(payload), action["request_id"]),
            )
        with pytest.raises(ValueError, match="Actual source text"):
            g.submit(run, "offline-no-summary-r0", p10())
        assert not s.rows("SELECT task_id FROM candidate_review_actions WHERE operation='P10'")
