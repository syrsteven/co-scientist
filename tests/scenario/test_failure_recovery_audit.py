"""Production failure paths, without online providers or real research artifacts."""

import asyncio
import copy
import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import yaml
from sqlalchemy import select

from co_scientist.adapters.llm.replay import ReplayLLMProvider
from co_scientist.adapters.persistence.sqlite import EventRow, ExternalCallRow, SqliteUnitOfWork
from co_scientist.application.commands import RetryInvalidOutput
from co_scientist.application.config import resolve_run_config
from co_scientist.application.service import build_application_service
from co_scientist.export.run_export import SqliteRunReadModel, verify_core_release_invariants
from co_scientist.runtime.core_runner import CoreRunner
from tests.core_preview_support import write_core_preview_inputs


async def retry_run(root: Path, failures: int) -> CoreRunner:
    goal, profile, environment = write_core_preview_inputs(root)
    config = resolve_run_config(goal_file=goal, profile_file=profile,
                                provider="replay", environment=environment)
    runner = CoreRunner(data_dir=root / "data", environment=environment)
    manifest = config.model_dump(mode="json")["manifest"]
    runner._compose(manifest)
    runner.supervisor.bootstrap_run(run_id="retry-audit", manifest=manifest)
    now = datetime.now(UTC)
    runner.worker.clock = lambda: now
    original = ReplayLLMProvider.invoke
    attempts = 0

    async def flaky(self, request):
        nonlocal attempts
        if request["skill_id"] == "generation":
            attempts += 1
            if attempts <= failures:
                raise httpx.ConnectError("offline connection failure before response")
        return await original(self, request)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(ReplayLLMProvider, "invoke", flaky)
        for _ in range(failures):
            with pytest.raises(ExceptionGroup):
                await runner.worker.run_once("retry-audit")
            now += timedelta(minutes=6)
        result = await runner.drive(run_id="retry-audit")
    assert result.state == "completed"
    assert attempts == failures + 1
    await runner.aclose()
    return runner


@pytest.mark.asyncio
@pytest.mark.parametrize("failures", [1, 2])
async def test_real_lease_retries_retain_auditable_historical_reservations(tmp_path, failures):
    runner = await retry_run(tmp_path, failures)
    model = SqliteRunReadModel(runner.uow)
    calls = [c for c in model.external_calls("retry-audit")
             if c["task_id"].startswith("generation:")]
    assert [c["attempt"] for c in sorted(calls, key=lambda c: c["attempt"])] == list(range(1, failures + 2))
    assert sum(c["state"] == "failed_before_response" for c in calls) == failures
    assert len({c["execution_context"]["reservation_id"] for c in calls}) == 1
    assert verify_core_release_invariants("retry-audit", model).violation_count == 0


@pytest.fixture(scope="module")
def retry_seed(tmp_path_factory):
    root = tmp_path_factory.mktemp("retry-audit-seed")
    runner = asyncio.run(retry_run(root, 1))
    runner.uow.engine.dispose()
    return root / "data"


@pytest.mark.parametrize("mutation", [
    "missing_reservation", "foreign_task", "wrong_request", "changed_context",
    "missing_expiry", "wrong_fence", "missing_requeue", "reordered_requeue",
    "not_failed_before", "invented_raw", "wrong_attempt",
])
def test_historical_retry_binding_requires_complete_durable_evidence(tmp_path, retry_seed, mutation):
    shutil.copytree(retry_seed, tmp_path / "data")
    uow = SqliteUnitOfWork(f"sqlite:///{tmp_path / 'data/co-scientist.db'}")
    with uow.session_factory.begin() as session:
        call = session.scalar(select(ExternalCallRow).where(ExternalCallRow.state == "failed_before_response"))
        context = json.loads(call.execution_context_json)
        if mutation == "missing_reservation":
            context.pop("reservation_id")
        elif mutation == "foreign_task":
            context["task_id"] = "other-task"
        elif mutation == "wrong_request":
            call.request_fingerprint = "wrong-request"
        elif mutation == "changed_context":
            context["input_snapshot_hash"] = "wrong-input"
        elif mutation == "wrong_fence":
            context["lease_fence_fingerprint"] = "sha256:" + "0" * 64
        elif mutation == "not_failed_before":
            call.state = "validation_failed"
        elif mutation == "invented_raw":
            call.raw_artifact_ref_json = json.dumps({"path": "invented"})
        elif mutation == "wrong_attempt":
            call.attempt = 0
        else:
            event_type = "TaskLeaseExpired" if mutation == "missing_expiry" else "TaskRequeued"
            event = session.scalar(select(EventRow).where(EventRow.event_type == event_type))
            payload = json.loads(event.payload_json)
            if mutation == "reordered_requeue":
                event.sequence = 10000
            else:
                payload["task_id"] = "other-task"
                event.payload_json = json.dumps(payload)
        call.execution_context_json = json.dumps(context)
    report = verify_core_release_invariants("retry-audit", SqliteRunReadModel(uow))
    assert report.external_call_without_reservation_count > 0


@pytest.mark.asyncio
@pytest.mark.parametrize("strict,fault", [
    (False, "json"), (True, "json"), (True, "missing"), (True, "multiple"), (True, "binding"),
    (True, "colon"), ("v2", "colon"), ("v2", "binding"), ("v2", "multiple"),
])
async def test_deepseek_ranking_output_is_raw_first_and_pauses(tmp_path, respx_mock, strict, fault):
    goal, profile_file, replay_environment = write_core_preview_inputs(tmp_path)
    profile = yaml.safe_load(profile_file.read_text())
    profile.update(scientific_context=True, research_protocol_version="research-v1",
                   providers={"llm": "deepseek", "literature": "pubmed"})
    if strict:
        profile["ranking_output_protocol"] = (
            "deepseek-strict-tool-v2" if strict == "v2" else "deepseek-strict-tool-v1"
        )
    profile_file.write_text(yaml.safe_dump(profile))
    records = json.loads(Path(replay_environment["CO_SCIENTIST_REPLAY_RESPONSES"]).read_text())["responses"]
    observed = []
    bad_bodies = []
    invalid_ranking = True

    def response(request):
        user = json.loads(json.loads(request.content)["messages"][1]["content"])
        role, inputs = user["input_schema"].removesuffix("InputV1").lower(), user["input"]
        observed.append(role)
        candidates = [r for r in records if r["skill_id"] == role]
        if role == "reflection":
            candidates = [r for r in candidates if r["inputs"]["review_stage"] == inputs["review_stage"]]
        payload = copy.deepcopy(candidates[0]["response"])
        payload.update({k: inputs[k] for k in set(payload) & set(inputs)})
        if role == "reflection":
            payload["review_id"] = f"{inputs['hypothesis_id']}:{inputs['review_stage']}"
            if payload.get("novelty_assessment"):
                payload["novelty_assessment"].update(hypothesis_id=inputs["hypothesis_id"],
                    content_hash=inputs["content_hash"], assessment_id=f"novelty:{inputs['hypothesis_id']}")
        if role == "ranking":
            payload["dimension_reasons"] = {key: "Offline synthetic comparison only"
                                            for key in inputs["evaluation_rubric"]["dimensions"]}
            if strict == "v2":
                reasons = payload.pop("dimension_reasons")
                payload.update({f"reason_{key}": value for key, value in reasons.items()})
        content = json.dumps(payload)
        if role == "ranking" and invalid_ranking and fault == "json":
            payload.pop("unresolved_disagreements", None)
            payload["unresolved_disagreements"] = ["Synthetic counterexample, no real research content"]
            content = json.dumps(payload)[:-2] + "}"
            with pytest.raises(json.JSONDecodeError):
                json.loads(content)
        elif role == "ranking" and invalid_ranking and fault == "colon":
            content = content.replace('"Offline synthetic comparison only"',
                                      '"Offline synthetic comparison only": ""', 1)
            with pytest.raises(json.JSONDecodeError):
                json.loads(content)
        envelope = {"id": f"offline-{len(observed)}", "choices": [{"finish_reason": "stop",
                    "message": {"content": content}}],
                    "usage": {"prompt_tokens": 23, "completion_tokens": 17}}
        if role == "ranking" and strict:
            sent = json.loads(request.content)
            assert request.url.path == "/beta/chat/completions"
            assert sent["tools"][0]["function"]["strict"] is True
            choice = envelope["choices"][0]
            choice.update(finish_reason="tool_calls", message={"content": None, "tool_calls": [
                {"id": "result-1", "type": "function", "function": {
                    "name": inputs["ranking_output_contract"]["tool_name"], "arguments": content,
                }},
            ]})
            if invalid_ranking:
                if fault == "missing":
                    choice.update(finish_reason="stop", message={"content": content})
                elif fault == "multiple":
                    choice["message"]["tool_calls"] *= 2
                elif fault == "binding":
                    wrong = json.loads(content)
                    wrong["left_content_hash"] = "wrong-binding"
                    choice["message"]["tool_calls"][0]["function"]["arguments"] = json.dumps(wrong)
        body = json.dumps(envelope).encode()
        if role == "ranking":
            bad_bodies.append(body)
        return httpx.Response(200, content=body, headers={"content-type": "application/json"})

    respx_mock.post("https://api.deepseek.com/chat/completions").mock(side_effect=response)
    respx_mock.post("https://api.deepseek.com/beta/chat/completions").mock(side_effect=response)
    for tool, fixture in (("esearch", "pubmed_search_lens.json"), ("esummary", "pubmed_summary_lens.json")):
        respx_mock.get(f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/{tool}.fcgi").mock(
            return_value=httpx.Response(200, content=(Path("tests/scenario/fixtures") / fixture).read_bytes()))
    environment = {"DEEPSEEK_API_KEY": "offline-only", "CO_SCIENTIST_DEEPSEEK_MODEL": "offline-test"}
    config = resolve_run_config(goal_file=goal, profile_file=profile_file,
                                provider="deepseek", environment=environment)
    runner = CoreRunner(data_dir=tmp_path / "data", environment=environment)
    result = await runner.execute(config=config, run_id="broken-ranking")
    assert result.state == "needs_attention" and result.stop_reason == "provider_output_invalid"
    assert observed.count("ranking") == 1 and "meta_review" not in observed
    model = SqliteRunReadModel(runner.uow)
    call = next(c for c in model.external_calls(result.run_id) if c["state"] == "validation_failed")
    assert call["validated_payload"] is None and call["agent_result"] is None
    assert (tmp_path / "data/artifacts" / call["raw_artifact_ref"]["path"]).read_bytes() == bad_bodies[0]
    cost = next(c for c in model.costs(result.run_id) if c["external_call_id"] == call["external_call_id"])
    assert (cost["input_tokens"], cost["output_tokens"]) == (23, 17)
    assert not model.matches(result.run_id)
    assert not any(e["event_type"] in {"RatingUpdated", "FinalizationCompleted"} for e in model.events(result.run_id))
    assert model.run_manifest(result.run_id)["state_history"][-1] == "needs_attention"
    assert verify_core_release_invariants(result.run_id, model).violation_count == 0
    before = len(observed), len(model.external_calls(result.run_id)), len(model.events(result.run_id))
    resumed = await CoreRunner(data_dir=tmp_path / "data", environment=environment).resume(run_id=result.run_id)
    assert resumed.state == "needs_attention"
    assert before == (len(observed), len(model.external_calls(result.run_id)), len(model.events(result.run_id)))
    old_cost = dict(cost)
    invalid_ranking = False
    service = build_application_service(tmp_path / "data", environment)
    receipt = service.execute(RetryInvalidOutput(run_id=result.run_id,
        external_call_id=call["external_call_id"], expected_run_sequence=model.events(result.run_id)[-1]["sequence"],
        confirmed=True))
    assert receipt["worker_started"] is False and len(observed) == before[0]
    recovered = await CoreRunner(data_dir=tmp_path / "data", environment=environment).resume(run_id=result.run_id)
    assert recovered.state == "completed"
    retry = next(c for c in model.external_calls(result.run_id) if c["parent_call_id"] == call["external_call_id"])
    assert retry["state"] == "domain_result_applied" and retry["request_fingerprint"] == call["request_fingerprint"]
    assert next(c for c in model.costs(result.run_id) if c["external_call_id"] == call["external_call_id"]) == old_cost
    assert (tmp_path / "data/artifacts" / call["raw_artifact_ref"]["path"]).read_bytes() == bad_bodies[0]
    assert len({m["match_id"] for m in model.matches(result.run_id)}) == len(model.matches(result.run_id))
    assert verify_core_release_invariants(result.run_id, model).violation_count == 0
