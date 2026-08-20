import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import yaml

from co_scientist.application.config import resolve_run_config
from co_scientist.domain.states import RunState
from co_scientist.export.run_export import SqliteRunReadModel
from co_scientist.ports.artifact_store import ArtifactRef
from co_scientist.runtime.core_runner import CoreRunner
from tests.core_preview_support import write_core_preview_inputs


@pytest.mark.asyncio
async def test_supervisor_bootstrap_and_core_runner_execute_use_one_durable_path(
    tmp_path: Path,
) -> None:
    goal_file, profile_file, environment = write_core_preview_inputs(tmp_path)
    config = resolve_run_config(
        goal_file=goal_file,
        profile_file=profile_file,
        provider="replay",
        environment=environment,
    )
    runner = CoreRunner(data_dir=tmp_path / "data", environment=environment)

    result = await runner.execute(config=config)

    assert result.state is RunState.COMPLETED
    assert result.stop_reason == "quality_converged"
    events = runner.uow.load(result.run_id)
    assert [event.event_type for event in events[:3]] == [
        "RunStarted",
        "TournamentEpochOpened",
        "TaskEnqueued",
    ]
    assert events[2].payload["task_id"].startswith("generation:")
    assert events[-2].event_type == "FinalizationCompleted"
    assert events[-1].event_type == "RunCompleted"
    assert all(event.payload.get("created_by", "supervisor") == "supervisor" for event in events if event.event_type == "TaskEnqueued")


@pytest.mark.asyncio
async def test_resume_continues_a_supervisor_bootstrapped_non_terminal_run(
    tmp_path: Path,
) -> None:
    goal_file, profile_file, environment = write_core_preview_inputs(tmp_path)
    config = resolve_run_config(
        goal_file=goal_file,
        profile_file=profile_file,
        provider="replay",
        environment=environment,
    )
    runner = CoreRunner(data_dir=tmp_path / "data", environment=environment)
    run_id = "run-interrupted"

    runner.supervisor.bootstrap_run(
        run_id=run_id,
        manifest=config.model_dump(mode="json")["manifest"],
    )
    assert runner.uow.run_state(run_id) == "running"

    result = await runner.resume(run_id=run_id)

    assert result.run_id == run_id
    assert result.state is RunState.COMPLETED
    assert result.last_sequence == runner.uow.load(run_id)[-1].sequence


@pytest.mark.asyncio
async def test_runner_schedules_configured_opportunistic_then_fixed_anchor_matches(
    tmp_path: Path,
) -> None:
    goal_file, profile_file, environment = write_core_preview_inputs(
        tmp_path,
        minimum_matches=6,
        top_k_stability_window=3,
    )
    config = resolve_run_config(
        goal_file=goal_file,
        profile_file=profile_file,
        provider="replay",
        environment=environment,
    )
    runner = CoreRunner(data_dir=tmp_path / "data", environment=environment)

    result = await runner.execute(config=config)

    assert result.state is RunState.COMPLETED
    matches = [
        event.payload
        for event in runner.uow.load(result.run_id)
        if event.event_type == "MatchEvaluated"
    ]
    assert [match["comparison_kind"] for match in matches] == [
        "opportunistic",
        "opportunistic",
        "opportunistic",
        "opportunistic",
        "fixed_anchor",
        "fixed_anchor",
    ]


@pytest.mark.asyncio
async def test_runner_verifies_literature_resources_before_bootstrap(tmp_path: Path) -> None:
    goal_file, profile_file, environment = write_core_preview_inputs(tmp_path)
    config = resolve_run_config(
        goal_file=goal_file,
        profile_file=profile_file,
        provider="replay",
        environment=environment,
    )
    Path(environment["CO_SCIENTIST_REPLAY_PUBMED_SEARCH"]).write_text(
        '{"tampered":true}\n', encoding="utf-8"
    )
    runner = CoreRunner(data_dir=tmp_path / "data", environment=environment)

    with pytest.raises(ValueError, match="pubmed_search"):
        await runner.execute(config=config)

    assert runner.literature_bridges == {}


@pytest.mark.asyncio
async def test_replay_literature_runs_raw_first_and_grounds_novelty(
    tmp_path: Path,
) -> None:
    goal_file, profile_file, environment = write_core_preview_inputs(tmp_path)
    config = resolve_run_config(
        goal_file=goal_file,
        profile_file=profile_file,
        provider="replay",
        environment=environment,
    )
    runner = CoreRunner(data_dir=tmp_path / "data", environment=environment)

    result = await runner.execute(config=config)

    calls = SqliteRunReadModel(runner.uow).external_calls(result.run_id)
    literature_calls = [
        call for call in calls if str(call["provider"]).startswith("replay_pubmed")
    ]
    assert [call["model_or_tool"] for call in literature_calls] == ["esearch", "esummary"]
    assert all(call["state"] == "domain_result_applied" for call in literature_calls)
    assert all(call["raw_artifact_ref"] is not None for call in literature_calls)
    assert all(call["applied_domain_sequence"] is not None for call in literature_calls)
    assert all(call["attempt"] == 1 for call in literature_calls)
    assert all(
        call["execution_context"]["reservation_id"] != "legacy-unbound"
        and call["execution_context"]["lease_fence_fingerprint"]
        for call in literature_calls
    )
    assert all(
        runner.artifacts.read(ArtifactRef.model_validate(call["raw_artifact_ref"]))
        for call in literature_calls
    )
    events = runner.uow.load(result.run_id)
    evidence_event = next(
        event
        for event in events
        if event.event_type == "MetaReviewCompleted"
        and event.payload.get("source_documents")
    )
    assert evidence_event.payload["source_call_id"] == literature_calls[-1]["external_call_id"]
    assert {item["source_id"] for item in evidence_event.payload["source_documents"]} == {
        "pubmed:1001",
        "pubmed:1002",
    }
    novelty = [
        event for event in events if event.event_type == "NoveltyAssessmentRecorded"
    ]
    assert novelty
    assert all(
        set(event.payload["evidence_ids"]) == {"pubmed:1001", "pubmed:1002"}
        for event in novelty
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("forgery", ["missing", "unknown-source"])
async def test_literature_novelty_fails_closed_without_grounded_evidence(
    tmp_path: Path,
    forgery: str,
) -> None:
    goal_file, profile_file, environment = write_core_preview_inputs(tmp_path)
    replay_path = Path(environment["CO_SCIENTIST_REPLAY_RESPONSES"])
    replay = json.loads(replay_path.read_text(encoding="utf-8"))
    full_review = next(
        record
        for record in replay["responses"]
        if record["skill_id"] == "reflection"
        and record["inputs"]["review_stage"] == "full_review"
    )
    if forgery == "missing":
        full_review["response"]["novelty_assessment"] = None
        full_review["response"]["evidence_ids"] = []
    else:
        full_review["response"]["novelty_assessment"]["evidence_ids"] = ["pubmed:forged"]
    replay_path.write_text(json.dumps(replay), encoding="utf-8")
    config = resolve_run_config(
        goal_file=goal_file,
        profile_file=profile_file,
        provider="replay",
        environment=environment,
    )
    runner = CoreRunner(data_dir=tmp_path / "data", environment=environment)

    with pytest.raises(ValueError, match="grounded literature evidence"):
        await runner.execute(config=config)


@pytest.mark.asyncio
async def test_two_runs_share_one_database_without_deterministic_task_collisions(
    tmp_path: Path,
) -> None:
    goal_file, profile_file, environment = write_core_preview_inputs(tmp_path)
    config = resolve_run_config(
        goal_file=goal_file,
        profile_file=profile_file,
        provider="replay",
        environment=environment,
    )
    data_dir = tmp_path / "data"
    runner = CoreRunner(data_dir=data_dir, environment=environment)

    first = await runner.execute(config=config)
    second = await runner.execute(config=config)
    restarted = CoreRunner(data_dir=data_dir, environment={})
    replayed = await restarted.resume(run_id=first.run_id)

    assert first.state is second.state is replayed.state is RunState.COMPLETED
    assert first.run_id != second.run_id
    tasks = SqliteRunReadModel(runner.uow).tasks(first.run_id)
    assert tasks
    assert all(first.run_id in task["task_id"] for task in tasks)


@pytest.mark.asyncio
async def test_non_converged_checkpoint_returns_resumable_and_resume_is_safe(
    tmp_path: Path,
) -> None:
    goal_file, profile_file, environment = write_core_preview_inputs(
        tmp_path,
        novelty_verdict="novel",
    )
    config = resolve_run_config(
        goal_file=goal_file,
        profile_file=profile_file,
        provider="replay",
        environment=environment,
    )
    runner = CoreRunner(data_dir=tmp_path / "data", environment=environment)

    first = await runner.execute(config=config)
    second = await runner.resume(run_id=first.run_id)

    assert first.state is second.state is RunState.RUNNING
    assert first.last_sequence == second.last_sequence
    assert sum(
        event.event_type == "ConvergenceCheckpointRecorded"
        for event in runner.uow.load(first.run_id)
    ) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("hypothesis_count", "expected_state"),
    [(1, RunState.FAILED), (3, RunState.COMPLETED), (5, RunState.FAILED)],
)
async def test_schema_valid_generation_cardinalities_finish_under_control(
    tmp_path: Path,
    hypothesis_count: int,
    expected_state: RunState,
) -> None:
    goal_file, profile_file, environment = write_core_preview_inputs(
        tmp_path,
        hypothesis_count=hypothesis_count,
        max_hypotheses=4,
    )
    config = resolve_run_config(
        goal_file=goal_file,
        profile_file=profile_file,
        provider="replay",
        environment=environment,
    )
    runner = CoreRunner(data_dir=tmp_path / "data", environment=environment)

    result = await runner.execute(config=config)

    assert result.state is expected_state
    assert not runner.uow.unresolved_task_ids(result.run_id)
    if expected_state is RunState.FAILED:
        assert result.stop_reason in {
            "insufficient_hypotheses_for_core_workflow",
            "hypothesis_count_exceeds_profile_budget",
        }


@pytest.mark.asyncio
async def test_terminal_and_paused_resume_do_not_recompose_providers(
    tmp_path: Path,
) -> None:
    goal_file, profile_file, environment = write_core_preview_inputs(tmp_path)
    config = resolve_run_config(
        goal_file=goal_file,
        profile_file=profile_file,
        provider="replay",
        environment=environment,
    )
    data_dir = tmp_path / "data"
    runner = CoreRunner(data_dir=data_dir, environment=environment)
    terminal = await runner.execute(config=config)
    paused_id = "run-paused-without-resources"
    paused = runner.supervisor.bootstrap_run(
        run_id=paused_id,
        manifest=config.model_dump(mode="json")["manifest"],
    )
    runner.supervisor.pause_run(paused_id, expected_sequence=paused.last_sequence)
    for key in (
        "CO_SCIENTIST_REPLAY_RESPONSES",
        "CO_SCIENTIST_REPLAY_PUBMED_SEARCH",
        "CO_SCIENTIST_REPLAY_PUBMED_SUMMARY",
    ):
        Path(environment[key]).rename(Path(environment[key] + ".moved"))
    restarted = CoreRunner(data_dir=data_dir, environment={})

    terminal_result = await restarted.resume(run_id=terminal.run_id)
    paused_result = await restarted.resume(run_id=paused_id)

    assert terminal_result.state is RunState.COMPLETED
    assert paused_result.state is RunState.PAUSED


class _OfflineOpenAIResponse:
    def __init__(self, payload: dict[str, Any], response_id: str) -> None:
        self.id = response_id
        self.usage = SimpleNamespace(input_tokens=3, output_tokens=5)
        self._payload = payload

    def model_dump_json(self) -> str:
        return json.dumps(
            {
                "id": self.id,
                "output": [
                    {
                        "content": [
                            {"type": "output_text", "text": json.dumps(self._payload)}
                        ]
                    }
                ],
            },
            separators=(",", ":"),
        )


@pytest.mark.asyncio
async def test_openai_shape_uses_the_same_worker_literature_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    respx_mock: Any,
) -> None:
    goal_file, profile_file, replay_environment = write_core_preview_inputs(tmp_path)
    profile = yaml.safe_load(profile_file.read_text(encoding="utf-8"))
    profile["providers"] = {"llm": "openai", "literature": "pubmed"}
    profile_file.write_text(yaml.safe_dump(profile), encoding="utf-8")
    replay = json.loads(
        Path(replay_environment["CO_SCIENTIST_REPLAY_RESPONSES"]).read_text(
            encoding="utf-8"
        )
    )
    responses = {
        (
            record["skill_id"],
            json.dumps(record["inputs"], separators=(",", ":"), sort_keys=True),
        ): record["response"]
        for record in replay["responses"]
    }

    class FakeResponses:
        def __init__(self) -> None:
            self.count = 0

        async def create(self, **request: Any) -> _OfflineOpenAIResponse:
            self.count += 1
            user = json.loads(request["input"])
            key = (
                request["text"]["format"]["name"].removesuffix("ResultV1").lower(),
                json.dumps(user["input"], separators=(",", ":"), sort_keys=True),
            )
            return _OfflineOpenAIResponse(responses[key], f"resp-{self.count}")

    fake_responses = FakeResponses()
    monkeypatch.setattr(
        "openai.AsyncOpenAI",
        lambda **_kwargs: SimpleNamespace(responses=fake_responses),
    )
    respx_mock.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi").mock(
        return_value=httpx.Response(
            200,
            content=Path("tests/scenario/fixtures/pubmed_search_lens.json").read_bytes(),
            headers={"content-type": "application/json", "ncbi-phid": "search-1"},
        )
    )
    respx_mock.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi").mock(
        return_value=httpx.Response(
            200,
            content=Path("tests/scenario/fixtures/pubmed_summary_lens.json").read_bytes(),
            headers={"content-type": "application/json", "ncbi-phid": "summary-1"},
        )
    )
    environment = {
        "OPENAI_API_KEY": "offline-shape-only",
        "CO_SCIENTIST_OPENAI_MODEL": "gpt-offline-shape",
    }
    config = resolve_run_config(
        goal_file=goal_file,
        profile_file=profile_file,
        provider="openai",
        environment=environment,
    )
    runner = CoreRunner(data_dir=tmp_path / "data", environment=environment)

    result = await runner.execute(config=config)

    assert result.state is RunState.COMPLETED
    calls = SqliteRunReadModel(runner.uow).external_calls(result.run_id)
    assert {call["provider"] for call in calls} >= {
        "openai",
        "pubmed:search",
        "pubmed:summary",
    }
    assert all(call["state"] == "domain_result_applied" for call in calls)
