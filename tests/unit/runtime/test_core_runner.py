from pathlib import Path

import pytest

from co_scientist.application.config import resolve_run_config
from co_scientist.domain.states import RunState
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
