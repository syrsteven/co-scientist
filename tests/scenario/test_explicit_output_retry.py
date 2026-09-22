"""Explicit paid-output retries through the real Worker/SQLite, all offline."""

import asyncio
import json
import shutil
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import yaml
from sqlalchemy import select
from typer.testing import CliRunner

from co_scientist.adapters.llm.replay import ReplayLLMProvider
from co_scientist.adapters.persistence.sqlite import (
    BudgetReservationRow,
    CostEntryRow,
    EventRow,
    ExternalCallRow,
    RunRow,
    TaskRow,
)
from co_scientist.application.commands import RetryInvalidOutput
from co_scientist.application.config import resolve_run_config
from co_scientist.application.service import (
    ApplicationInvalidRequestError,
    build_application_service,
)
from co_scientist.cli.app import app
from co_scientist.domain.states import RunState
from co_scientist.domain.task import TaskLeaseFence
from co_scientist.events.models import NewEvent
from co_scientist.export.run_export import SqliteRunReadModel, verify_core_release_invariants
from co_scientist.ports.event_store import ConcurrencyConflict
from co_scientist.ports.external_provider import RawExternalResponse
from co_scientist.runtime.core_runner import CoreRunner
from tests.core_preview_support import write_core_preview_inputs

RUN = "explicit-retry"
BAD_RAW = b'{"schema_version": 1, "hypotheses": ['


async def broken_response(self, request):
    return RawExternalResponse(body=BAD_RAW, mime_type="application/json", usage={
        "input_tokens": 23, "output_tokens": 17, "cost_usd": "0.25", "pricing_version": "offline-v1",
    })


async def create_failed_run(root):
    goal, profile, environment = write_core_preview_inputs(root)
    settings = yaml.safe_load(profile.read_text())
    settings["scientific_context"] = True
    profile.write_text(yaml.safe_dump(settings))
    config = resolve_run_config(goal_file=goal, profile_file=profile,
                                provider="replay", environment=environment)
    runner = CoreRunner(data_dir=root / "data", environment=environment)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(ReplayLLMProvider, "invoke", broken_response)
        result = await runner.execute(config=config, run_id=RUN)
    assert result.state == "needs_attention"
    runner.uow.engine.dispose()
    return environment


@pytest.fixture(scope="module")
def failed_seed(tmp_path_factory):
    root = tmp_path_factory.mktemp("explicit-output-seed")
    environment = asyncio.run(create_failed_run(root))
    return root, environment


@pytest.fixture
def case(tmp_path, failed_seed):
    root, environment = failed_seed
    shutil.copytree(root / "data", tmp_path / "data")
    runner = CoreRunner(data_dir=tmp_path / "data", environment=environment)
    model = SqliteRunReadModel(runner.uow)
    call = next(c for c in model.external_calls(RUN) if c["state"] == "validation_failed")
    yield runner, model, call, environment
    runner.uow.engine.dispose()


def tip(runner):
    return runner.uow.load(RUN)[-1].sequence


def authorize(runner, call):
    return runner.supervisor.retry_invalid_output(run_id=RUN,
        external_call_id=call["external_call_id"], expected_sequence=tip(runner))


def good_generation(environment):
    document = json.loads(Path(environment["CO_SCIENTIST_REPLAY_RESPONSES"]).read_text())
    payload = next(r["response"] for r in document["responses"] if r["skill_id"] == "generation")

    async def response(self, request):
        assert request["skill_id"] == "generation"
        return RawExternalResponse(body=json.dumps(payload).encode(), mime_type="application/json",
            usage={"input_tokens": 29, "output_tokens": 31, "cost_usd": "0.4", "pricing_version": "offline-v1"})
    return response


async def worker_step(runner):
    runner._compose(runner.uow.run_manifest(RUN))
    try:
        return await runner.worker.run_once(RUN)
    finally:
        await runner.aclose()


@pytest.mark.asyncio
async def test_retry_is_raw_first_same_task_new_call_and_exactly_once_cost(case, monkeypatch):
    runner, model, old, environment = case
    old_tasks, old_costs = model.tasks(RUN), model.costs(RUN)
    old_sequence = tip(runner)
    commit = authorize(runner, old)
    assert commit.last_sequence == old_sequence + 3
    assert model.external_calls(RUN) == [old] and model.costs(RUN) == old_costs
    assert model.tasks(RUN)[0]["task_id"] == old_tasks[0]["task_id"]
    assert runner.uow.task_state(old["task_id"]) == "pending"
    monkeypatch.setattr(ReplayLLMProvider, "invoke", good_generation(environment))
    # A separate worker composition, not the control command, invokes the provider.
    worker = CoreRunner(data_dir=runner.data_dir, environment=environment)
    result = await worker_step(worker)
    assert result.status == "completed" and result.attempt == 2
    calls = sorted(model.external_calls(RUN), key=lambda c: c["attempt"])
    assert calls[0] == old
    assert calls[1]["state"] == "domain_result_applied"
    assert calls[1]["parent_call_id"] == old["external_call_id"]
    assert calls[1]["request_fingerprint"] == old["request_fingerprint"]
    assert calls[1]["execution_context"]["reservation_id"] == old["execution_context"]["reservation_id"]
    assert runner.artifacts.read(runner.uow.get_external_call(old["external_call_id"]).raw_artifact_ref) == BAD_RAW
    costs = model.costs(RUN)
    assert len(costs) == 2
    assert sum(c["input_tokens"] for c in costs) == 52
    assert sum(c["output_tokens"] for c in costs) == 48
    assert sum(Decimal(c["cost_usd"]) for c in costs) == Decimal("0.65")
    snapshot = runner.uow.load_budget_snapshot(RUN)
    assert snapshot.settled.model_calls == 2 and snapshot.settled.cost_usd == Decimal("0.65")
    assert verify_core_release_invariants(RUN, model).violation_count == 0
    created = [e["payload"]["hypothesis_id"] for e in model.events(RUN)
               if e["event_type"] == "HypothesisContentCreated"]
    assert created.count("h-1") == created.count("h-2") == 1


@pytest.mark.asyncio
async def test_each_invalid_response_requires_new_explicit_authorization_and_stops_at_max_attempts(case, monkeypatch):
    runner, model, call, environment = case
    monkeypatch.setattr(ReplayLLMProvider, "invoke", broken_response)
    for expected_attempt in (2, 3):
        authorize(runner, call)
        result = await CoreRunner(data_dir=runner.data_dir, environment=environment).resume(run_id=RUN)
        assert result.state == "needs_attention"
        call = max(model.external_calls(RUN), key=lambda c: c["attempt"])
        assert call["attempt"] == expected_attempt and call["state"] == "validation_failed"
        before = tip(runner), len(model.costs(RUN))
        await CoreRunner(data_dir=runner.data_dir, environment=environment).resume(run_id=RUN)
        assert before == (tip(runner), len(model.costs(RUN)))
    before = tip(runner)
    with pytest.raises(ValueError, match="max_attempts"):
        authorize(runner, call)
    assert tip(runner) == before and len(model.costs(RUN)) == 3
    assert verify_core_release_invariants(RUN, model).violation_count == 0


def test_stale_duplicate_wrong_call_and_resume_do_not_authorize(case):
    runner, model, call, _ = case
    sequence = tip(runner)
    with pytest.raises(ConcurrencyConflict):
        runner.supervisor.retry_invalid_output(run_id=RUN, external_call_id=call["external_call_id"], expected_sequence=sequence - 1)
    with pytest.raises(KeyError):
        runner.supervisor.retry_invalid_output(run_id=RUN, external_call_id="missing-call", expected_sequence=sequence)
    with pytest.raises(ValueError, match="explicit resolution"):
        runner.supervisor.resume_run(RUN, expected_sequence=sequence)
    with pytest.raises(ValueError, match="dedicated resolution"):
        runner.uow.commit_lifecycle_batch(run_id=RUN, expected_sequence=sequence,
            events=(NewEvent(event_type="RunResumed", payload={}),),
            target_run_state=RunState.RUNNING, idempotency_key="bypass")
    assert runner.uow.recover_expired_leases(run_id=RUN, now=datetime.now(UTC) + timedelta(days=1)) == ()
    assert tip(runner) == sequence
    authorize(runner, call)
    with pytest.raises(ConcurrencyConflict):
        runner.supervisor.retry_invalid_output(run_id=RUN, external_call_id=call["external_call_id"], expected_sequence=sequence)
    with pytest.raises(ValueError, match="needs_attention"):
        authorize(runner, call)
    assert tip(runner) == sequence + 3 and len(model.costs(RUN)) == 1


@pytest.mark.parametrize("condition", [
    "call_budget", "input_budget", "output_budget", "usd_budget", "unbounded", "exact_input_budget",
    "max_attempts", "no_cost", "wrong_cost", "scientific_attention", "applied",
    "changed_input", "changed_input_body", "changed_reservation", "wrong_run",
])
def test_invalid_or_unfunded_requests_are_atomic_noops(case, condition):
    runner, model, call, _ = case
    with runner.uow.session_factory.begin() as session:
        run = session.get(RunRow, RUN)
        manifest = json.loads(run.manifest_json)
        limits = {"call_budget": ("max_model_calls", 1), "input_budget": ("max_input_tokens", 22),
                  "output_budget": ("max_output_tokens", 16), "usd_budget": ("max_usd", "0.24"),
                  "unbounded": ("max_model_calls", None), "exact_input_budget": ("max_input_tokens", 23)}
        if condition in limits:
            key, value = limits[condition]
            manifest["budget"][key] = value
            run.manifest_json = json.dumps(manifest)
        elif condition == "max_attempts":
            session.get(TaskRow, call["task_id"]).max_attempts = 1
        elif condition in {"no_cost", "wrong_cost"}:
            cost = session.scalar(select(CostEntryRow))
            if condition == "no_cost":
                session.delete(cost)
            else:
                cost.input_tokens += 1
        elif condition == "scientific_attention":
            row = session.scalar(select(EventRow).where(EventRow.event_type == "RunNeedsAttention"))
            payload = json.loads(row.payload_json)
            payload["reason"] = "meta_review_requires_scientist_input"
            row.payload_json = json.dumps(payload)
        elif condition == "applied":
            session.get(ExternalCallRow, call["external_call_id"]).applied_domain_sequence = 1
        elif condition in {"changed_input", "changed_input_body"}:
            task = session.get(TaskRow, call["task_id"])
            payload = json.loads(task.payload_json)
            if condition == "changed_input":
                payload["input_snapshot_hash"] = "different"
            else:
                payload["inputs"]["goal_title"] = "different"
            task.payload_json = json.dumps(payload)
        elif condition == "changed_reservation":
            session.scalar(select(BudgetReservationRow)).external_call_id = None
        else:
            session.get(ExternalCallRow, call["external_call_id"]).run_id = "wrong-run"
    before = tip(runner), model.tasks(RUN), model.costs(RUN)
    with pytest.raises((ValueError, KeyError)):
        authorize(runner, call)
    assert before == (tip(runner), model.tasks(RUN), model.costs(RUN))
    assert runner.uow.run_state(RUN) == "needs_attention"


@pytest.mark.parametrize("limit, value", [("max_model_calls", 1), ("max_input_tokens", 23),
                                         ("max_output_tokens", 17), ("max_usd", "0.25")])
def test_command_revokes_old_lease_and_checks_budget_again_at_claim(case, limit, value):
    runner, model, call, _ = case
    with runner.uow.session_factory() as session:
        task = session.get(TaskRow, call["task_id"])
        fence = TaskLeaseFence(run_id=RUN, task_id=task.task_id,
                              lease_token=task.lease_token, attempt=task.attempt)
    authorize(runner, call)
    with pytest.raises(ValueError, match="stale"):
        runner.uow.heartbeat_task(fence=fence, now=datetime.now(UTC), lease_duration=timedelta(minutes=5))
    # Emulate budget being consumed after authorization, before Worker claim.
    with runner.uow.session_factory.begin() as session:
        run = session.get(RunRow, RUN)
        manifest = json.loads(run.manifest_json)
        manifest["budget"][limit] = value
        run.manifest_json = json.dumps(manifest)
    outcome = runner.uow.claim_next_task(run_id=RUN, worker_id="retry-worker", lease_token="fresh",
                                        now=datetime.now(UTC), lease_duration=timedelta(minutes=5))
    assert outcome.status == "budget_exhausted" and len(model.external_calls(RUN)) == 1


def test_cli_requires_confirmation_and_never_starts_worker(case):
    runner, model, call, environment = case
    args = ["run", "retry-output", RUN, "--call-id", call["external_call_id"],
            "--expected-sequence", str(tip(runner)), "--data-dir", str(runner.data_dir)]
    no = CliRunner().invoke(app, args, env=environment)
    assert no.exit_code == 5 and "confirmation" in no.output
    yes = CliRunner().invoke(app, [*args, "--confirm"], env=environment)
    assert yes.exit_code == 0, yes.output
    receipt = json.loads(yes.stdout)
    assert receipt["worker_started"] is False and receipt["authorized_attempt"] == 2
    assert len(model.external_calls(RUN)) == len(model.costs(RUN)) == 1
    stale = CliRunner().invoke(app, [*args, "--confirm"], env=environment)
    assert stale.exit_code == 4


def test_application_rejects_corrupt_raw_without_writing(case):
    runner, _, call, environment = case
    before = tip(runner)
    (runner.data_dir / "artifacts" / call["raw_artifact_ref"]["path"]).write_bytes(b"corrupted")
    service = build_application_service(runner.data_dir, environment)
    with pytest.raises(ApplicationInvalidRequestError, match="integrity"):
        service.execute(RetryInvalidOutput(run_id=RUN, external_call_id=call["external_call_id"],
                         expected_run_sequence=before, confirmed=True))
    assert tip(runner) == before


@pytest.mark.asyncio
async def test_explicit_retry_can_follow_normal_transport_recovery_without_losing_history(case, monkeypatch):
    runner, model, old, environment = case
    authorize(runner, old)
    runner._compose(runner.uow.run_manifest(RUN))
    now = datetime.now(UTC)
    runner.worker.clock = lambda: now

    async def disconnected(self, request):
        raise httpx.ConnectError("offline response-free failure")

    monkeypatch.setattr(ReplayLLMProvider, "invoke", disconnected)
    with pytest.raises(ExceptionGroup):
        await runner.worker.run_once(RUN)
    now += timedelta(minutes=6)
    monkeypatch.setattr(ReplayLLMProvider, "invoke", good_generation(environment))
    try:
        assert (await runner.worker.run_once(RUN)).attempt == 3
    finally:
        await runner.aclose()
    calls = sorted(model.external_calls(RUN), key=lambda c: c["attempt"])
    assert [c["state"] for c in calls] == ["validation_failed", "failed_before_response", "domain_result_applied"]
    assert len(model.costs(RUN)) == 2
    assert verify_core_release_invariants(RUN, model).violation_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["missing_auth", "wrong_raw", "wrong_parent", "wrong_author", "wrong_next_attempt", "missing_requeue"])
async def test_paid_historical_binding_requires_explicit_raw_bound_proof(case, monkeypatch, mutation):
    runner, model, old, environment = case
    authorize(runner, old)
    monkeypatch.setattr(ReplayLLMProvider, "invoke", good_generation(environment))
    await worker_step(runner)
    assert verify_core_release_invariants(RUN, model).violation_count == 0
    with runner.uow.session_factory.begin() as session:
        if mutation == "wrong_parent":
            session.scalar(select(ExternalCallRow).where(ExternalCallRow.attempt == 2)).parent_call_id = "wrong-parent"
        else:
            kind = "TaskRequeued" if mutation == "missing_requeue" else "TaskOutputRetryRequested"
            row = session.scalar(select(EventRow).where(EventRow.event_type == kind))
            payload = json.loads(row.payload_json)
            if mutation in {"missing_auth", "missing_requeue"}:
                payload["task_id"] = "another-task"
            elif mutation == "wrong_raw":
                payload["raw_artifact_ref"]["sha256"] = "sha256:" + "0" * 64
            elif mutation == "wrong_author":
                payload["authorized_by"] = "agent"
            else:
                payload["authorized_attempt"] = 3
            row.payload_json = json.dumps(payload)
    assert verify_core_release_invariants(RUN, model).external_call_without_reservation_count > 0
