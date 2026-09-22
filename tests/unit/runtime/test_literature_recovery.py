import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from co_scientist.adapters.literature.replay import ReplayLiteratureProvider
from co_scientist.application.config import CoreProfile, resolve_run_config
from co_scientist.domain.states import RunState
from co_scientist.export.run_export import SqliteRunReadModel
from co_scientist.ports.external_provider import RawExternalResponse
from co_scientist.runtime.core_runner import CoreRunner
from tests.core_preview_support import write_core_preview_inputs


@pytest.mark.asyncio
@pytest.mark.parametrize("exhausted", [False, True])
async def test_zero_results_are_applied_and_fallback_is_bounded_and_resumable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exhausted: bool,
) -> None:
    goal_file, profile_file, environment = write_core_preview_inputs(tmp_path)
    profile = yaml.safe_load(profile_file.read_text())
    # Finish on the original query so existing scientific replay responses remain exact.
    title = yaml.safe_load(goal_file.read_text())["title"]
    queries = ["overly specific query", f"{title} lens epithelial regeneration fibrosis"]
    profile["literature_search_queries"] = queries
    profile_file.write_text(yaml.safe_dump(profile))
    config = resolve_run_config(goal_file=goal_file, profile_file=profile_file,
                                provider="replay", environment=environment)
    requested: list[str] = []
    original = ReplayLiteratureProvider.search

    async def search(self: ReplayLiteratureProvider, query: str, limit: int = 10) -> RawExternalResponse:
        requested.append(query)
        if query == queries[0] or exhausted:
            return RawExternalResponse(body=b'{"esearchresult":{"idlist":[]}}',
                                       mime_type="application/json")
        return await original(self, query, limit)

    monkeypatch.setattr(ReplayLiteratureProvider, "search", search)
    runner = CoreRunner(data_dir=tmp_path / "data", environment=environment)
    manifest = config.model_dump(mode="json")["manifest"]
    run_id = "search-recovery"
    runner.supervisor.bootstrap_run(run_id=run_id, manifest=manifest)
    runner._compose(manifest)
    assert runner.worker is not None
    # Simulate a crash after the empty result has been submitted, before domain apply.
    handle_result = runner.supervisor.handle_result

    def crash_on_search(*args: Any, **kwargs: Any) -> Any:
        if args[2].provider.endswith(":search"):
            raise RuntimeError("crash after search submission")
        return handle_result(*args, **kwargs)

    monkeypatch.setattr(runner.supervisor, "handle_result", crash_on_search)
    with pytest.raises(RuntimeError, match="crash after search submission"):
        await runner.drive(run_id=run_id)
    assert requested == queries[:1]
    calls_before = SqliteRunReadModel(runner.uow).external_calls(run_id)
    assert any(call["state"] == "agent_result_submitted" for call in calls_before)
    # A new process resumes the submitted call without making it again.
    restarted = CoreRunner(data_dir=tmp_path / "data", environment=environment)
    result = await restarted.resume(run_id=run_id)
    assert requested == queries
    calls = SqliteRunReadModel(restarted.uow).external_calls(run_id)
    searches = [call for call in calls if str(call["provider"]).endswith(":search")]
    assert len(searches) == 2
    assert all(call["raw_artifact_ref"] and call["state"] == "domain_result_applied" for call in searches)
    events = restarted.uow.load(run_id)
    assert [event.payload["pubmed_query"] for event in events
            if event.event_type == "MetaReviewCompleted"
            and event.payload.get("literature_operation") == "search"] == queries
    if exhausted:
        assert result.state is RunState.FAILED
        assert result.stop_reason == "literature_search_exhausted"
        assert not any(call["model_or_tool"] == "esummary" for call in calls)
    else:
        assert result.state is RunState.COMPLETED
        assert sum(call["model_or_tool"] == "esummary" for call in calls) == 1


@pytest.mark.parametrize("queries", [[" "], ["lens", "lens"], [str(i) for i in range(6)]])
def test_invalid_query_strategy_rejected(queries: list[str]) -> None:
    document = yaml.safe_load(Path("configs/profiles/core_preview_deepseek.yaml").read_text())
    document["literature_search_queries"] = queries
    with pytest.raises(ValueError):
        CoreProfile.model_validate(document)


@pytest.mark.asyncio
@pytest.mark.parametrize("recommendation", ["needs_more_evidence", "reject"])
async def test_honest_negative_review_without_citations_is_not_a_protocol_failure(
    tmp_path: Path, recommendation: str,
) -> None:
    goal_file, profile_file, environment = write_core_preview_inputs(tmp_path)
    replay_path = Path(environment["CO_SCIENTIST_REPLAY_RESPONSES"])
    replay = json.loads(replay_path.read_text())
    for record in replay["responses"]:
        if record["skill_id"] == "reflection" and record["inputs"]["review_stage"] == "full_review":
            record["response"].update(recommendation=recommendation,
                                       evidence_ids=[], novelty_assessment=None)
    replay_path.write_text(json.dumps(replay))
    config = resolve_run_config(goal_file=goal_file, profile_file=profile_file,
                                provider="replay", environment=environment)
    runner = CoreRunner(data_dir=tmp_path / "data", environment=environment)
    result = await runner.execute(config=config)
    assert result.state is RunState.NEEDS_ATTENTION
    assert result.stop_reason == "review_requires_scientist_input"
    calls = SqliteRunReadModel(runner.uow).external_calls(result.run_id)
    assert all(call["state"] == "domain_result_applied" for call in calls)
    events = runner.uow.load(result.run_id)
    assert events[-1].event_type == "RunNeedsAttention"
    assert not any(event.event_type in {"MatchEvaluated", "RunCompleted"} for event in events)
