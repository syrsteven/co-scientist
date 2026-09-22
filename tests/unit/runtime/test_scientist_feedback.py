import json

import pytest
from typer.testing import CliRunner

from co_scientist.adapters.llm.replay import ReplayLLMProvider
from co_scientist.application.cockpit_retry import scientist_feedback
from co_scientist.cli.app import app
from co_scientist.domain.states import RunState
from co_scientist.events.models import NewEvent
from co_scientist.export.run_export import SqliteRunReadModel, verify_core_release_invariants
from co_scientist.ports.event_store import ConcurrencyConflict
from co_scientist.ports.external_provider import RawExternalResponse
from co_scientist.runtime.core_runner import CoreRunner
from co_scientist.supervisor.scientist_feedback import submit_scientist_feedback
from tests.unit.runtime.test_feedback_loop import setup_loop


@pytest.mark.asyncio
@pytest.mark.parametrize("verdict", ["clear", "concern"])
async def test_scientist_note_reassesses_without_overwriting_feedback(tmp_path, monkeypatch, verdict):
    config, env, observed = setup_loop(tmp_path, monkeypatch, safety="insufficient_evidence")
    runner = CoreRunner(data_dir=tmp_path / "data", environment=env)
    assert str((await runner.execute(config=config, run_id="human")).state) == "needs_attention"
    events = runner.uow.load("human")
    original = next(e for e in events if e.event_type == "ResearchFeedbackRecorded")
    args = {"run_id": "human", "feedback_id": original.payload["feedback_id"],
            "expected_sequence": events[-1].sequence, "actor": "Researcher",
            "note": "Please inspect initial safety coverage.", "confirmed": True}
    for override, error in [({"confirmed": False}, ValueError), ({"feedback_id": "wrong"}, ValueError),
                            ({"expected_sequence": 0}, ConcurrencyConflict), ({"note": " "}, ValueError)]:
        with pytest.raises(error):
            submit_scientist_feedback(runner.supervisor, **{**args, **override})
        assert runner.uow.load("human") == events
    calls_before = len(observed)
    with pytest.raises(ValueError, match="dedicated resolution"):
        runner.uow.commit_lifecycle_batch(run_id="human", expected_sequence=events[-1].sequence,
            events=(NewEvent(event_type="RunResumed", payload={}),), target_run_state=RunState.RUNNING,
            idempotency_key="unauthorized-resume")
    snapshot = runner.uow.load_budget_snapshot("human")
    with monkeypatch.context() as scoped:
        scoped.setattr(runner.uow, "load_budget_snapshot", lambda run: snapshot.model_copy(update={"hard_limit_reached": True}))
        with pytest.raises(ValueError, match="budget"):
            submit_scientist_feedback(runner.supervisor, **args)
    if verdict == "concern":
        payload = {k: v for k, v in args.items() if k not in {"run_id", "expected_sequence"}}
        payload["expected_run_sequence"] = args["expected_sequence"]
        db = tmp_path / "data/co-scientist.db"
        assert scientist_feedback(db, "human", {**payload, "run_id": "injected"})["status"] == 422
        assert scientist_feedback(db, "human", {**payload, "confirmed": "true"})["status"] == 422
        result = scientist_feedback(db, "human", payload)
        assert result["ok"]
    else:
        note = tmp_path / "note.txt"
        note.write_text(args["note"])
        invoked = CliRunner().invoke(app, ["run", "scientist-feedback", "human", "--feedback-id", args["feedback_id"],
            "--expected-sequence", str(args["expected_sequence"]), "--actor", args["actor"],
            "--note-file", str(note), "--confirm", "--data-dir", str(tmp_path / "data")])
        assert invoked.exit_code == 0, invoked.output
        result = json.loads(invoked.output)
    assert not result["worker_started"] and len(observed) == calls_before
    with pytest.raises(ConcurrencyConflict):
        submit_scientist_feedback(runner.supervisor, **args)
    old_invoke = ReplayLLMProvider.invoke

    async def reassess(self, request):
        if request["skill_id"] == "meta_review" and request["input"].get("scientist_feedback"):
            inputs = request["input"]
            assert inputs["scientist_feedback"]["source_feedback_hash"] == original.payload["feedback_hash"]
            assert inputs["research_feedback"]["safety_direction_check"] == "insufficient_evidence"
            return RawExternalResponse(body=json.dumps({"schema_version": 1, "research_plan_version": 1,
                "source_content_hashes": inputs["source_content_hashes"], "system_feedback": [],
                "overview": "Independent reassessment", "coverage_gaps": [],
                "safety_direction_check": verdict}).encode(), mime_type="application/json")
        return await old_invoke(self, request)

    monkeypatch.setattr(ReplayLLMProvider, "invoke", reassess)
    await runner.aclose()
    runner = CoreRunner(data_dir=tmp_path / "data", environment=env)
    outcome = await runner.resume(run_id="human")
    assert str(outcome.state) == ("completed" if verdict == "clear" else "needs_attention")
    final = runner.uow.load("human")
    assert next(e for e in final if e.sequence == original.sequence) == original
    assert len([e for e in final if e.event_type == "ScientistFeedbackRecorded"]) == 1
    assert len([e for e in final if e.event_type == "ResearchFeedbackRecorded"]) == 2
    assert verify_core_release_invariants("human", SqliteRunReadModel(runner.uow)).violation_count == 0


@pytest.mark.asyncio
async def test_scientist_reassessment_cannot_expand_round_allowance(tmp_path, monkeypatch):
    config, env, _ = setup_loop(tmp_path, monkeypatch, safety="concern", rounds=1)
    runner = CoreRunner(data_dir=tmp_path / "data", environment=env)
    await runner.execute(config=config, run_id="bounded")
    events = runner.uow.load("bounded")
    feedback = next(e for e in events if e.event_type == "ResearchFeedbackRecorded")
    with pytest.raises(ValueError, match="allowance exhausted"):
        submit_scientist_feedback(runner.supervisor, run_id="bounded",
            feedback_id=feedback.payload["feedback_id"], expected_sequence=events[-1].sequence,
            actor="Researcher", note="Please reconsider.", confirmed=True)
    assert runner.uow.load("bounded") == events
