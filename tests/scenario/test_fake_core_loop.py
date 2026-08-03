import asyncio
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from co_scientist.adapters.artifacts.filesystem import FilesystemArtifactStore
from co_scientist.adapters.llm.fake import FakeLLMProvider
from co_scientist.adapters.llm.replay import ReplayLLMProvider, ReplayMiss
from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork
from co_scientist.agents.executor import SkillExecutor
from co_scientist.agents.result import AgentExecutionContext
from co_scientist.domain.review import ReviewPolicy, ReviewStage, required_review_stages
from co_scientist.domain.states import RunState, TaskState
from co_scientist.domain.task import NewTask
from co_scientist.domain.tournament import TournamentEpoch
from co_scientist.events.models import NewEvent
from co_scientist.runtime.external_calls import ExternalCallRunner, request_fingerprint
from co_scientist.supervisor.orchestrator import Supervisor


# Mutation caught: modifying raw bytes, violating FIFO order, or returning unstable fake IDs.
@pytest.mark.asyncio
async def test_fake_provider_returns_queued_raw_responses_in_order() -> None:
    provider = FakeLLMProvider([b'{"step":1}', b'{"step":2}'])

    first = await provider.invoke({"request": 1})
    second = await provider.invoke({"request": 2})

    assert (first.body, first.mime_type, first.provider_response_id) == (
        b'{"step":1}',
        "application/json",
        "fake-1",
    )
    assert (second.body, second.provider_response_id) == (b'{"step":2}', "fake-2")
    assert provider.call_count == 2


# Mutation caught: replaying by dict insertion order or returning a response for an unknown request.
@pytest.mark.asyncio
async def test_replay_provider_uses_canonical_fingerprint_and_fails_closed() -> None:
    recorded_request = {"skill": "generation", "input": {"b": 2, "a": 1}}
    fingerprint = request_fingerprint(recorded_request)
    provider = ReplayLLMProvider({fingerprint: b'{"hypotheses":[]}'})

    replayed = await provider.invoke({"input": {"a": 1, "b": 2}, "skill": "generation"})

    assert replayed.body == b'{"hypotheses":[]}'
    assert replayed.provider_response_id == f"replay-{fingerprint[:12]}"
    missing_request = {"skill": "reflection"}
    missing_fingerprint = request_fingerprint(missing_request)
    with pytest.raises(ReplayMiss, match=missing_fingerprint[:12]):
        await provider.invoke(missing_request)


# Mutation caught: bypassing ExternalCallRunner or changing the canonical skill request contract.
@pytest.mark.asyncio
async def test_skill_executor_uses_raw_first_runner_and_returns_agent_result(tmp_path) -> None:
    uow = SqliteUnitOfWork(f"sqlite:///{tmp_path / 'executor.db'}")
    uow.create_schema()
    uow.create_run("run-1", manifest={})
    uow.enqueue_tasks(
        [
            NewTask(
                task_id="task-1",
                run_id="run-1",
                idempotency_key="generation:run-1:1",
                intent_type="generate",
                payload={},
            )
        ]
    )
    artifacts = FilesystemArtifactStore(tmp_path / "artifacts")
    runner = ExternalCallRunner(SimpleNamespace(uow=uow, artifacts=artifacts))
    expected_request = {
        "skill_id": "generation",
        "skill_version": "0.1.0",
        "system_prompt": (
            "Return JSON hypotheses containing title, claim, mechanism_chain, assumptions,\n"
            "predictions, falsifiers, and generation_strategy. Do not create tasks.\n"
        ),
        "input_schema": "GenerationInputV1",
        "output_schema": "GenerationResultV1",
        "allowed_tools": [],
        "input": {"research_goal": "test regeneration"},
    }
    raw_body = b'{"hypotheses":[{"hypothesis_id":"h-1"}]}'
    provider = ReplayLLMProvider({request_fingerprint(expected_request): raw_body})
    context = AgentExecutionContext(
        run_id="run-1",
        task_id="task-1",
        idempotency_key="generation:run-1:1",
        skill_id="generation",
        skill_version="0.1.0",
        output_schema_version=1,
        input_snapshot_hash="sha256:input",
    )

    result = await SkillExecutor(runner, provider).execute(
        call_id="call-1",
        skill_directory=Path("skills/generation"),
        inputs={"research_goal": "test regeneration"},
        context=context,
    )

    assert result.payload == {"hypotheses": [{"hypothesis_id": "h-1"}]}
    assert result.raw_artifact_ref.path.startswith("raw/call-1/")
    assert artifacts.read(result.raw_artifact_ref) == raw_body
    assert uow.external_call_state("call-1") == "agent_result_submitted"


@pytest.mark.parametrize(
    ("context_override", "message"),
    [
        ({"skill_id": "reflection"}, "skill does not match"),
        ({"skill_version": "0.2.0"}, "skill version does not match"),
        ({"output_schema_version": 2}, "schema version must be 1"),
    ],
)
# Mutation caught: allowing execution context identity or schema version to drift from a skill.
@pytest.mark.asyncio
async def test_skill_executor_rejects_incompatible_context_before_provider_call(
    tmp_path,
    context_override,
    message: str,
) -> None:
    uow = SqliteUnitOfWork(f"sqlite:///{tmp_path / 'context.db'}")
    uow.create_schema()
    uow.create_run("run-1", manifest={})
    uow.enqueue_tasks(
        [
            NewTask(
                task_id="task-1",
                run_id="run-1",
                idempotency_key="generation:run-1:1",
                intent_type="generate",
                payload={},
            )
        ]
    )
    runner = ExternalCallRunner(
        SimpleNamespace(
            uow=uow,
            artifacts=FilesystemArtifactStore(tmp_path / "artifacts"),
        )
    )
    provider = FakeLLMProvider([b'{"hypotheses":[]}'])
    context_data = {
        "run_id": "run-1",
        "task_id": "task-1",
        "idempotency_key": "generation:run-1:1",
        "skill_id": "generation",
        "skill_version": "0.1.0",
        "output_schema_version": 1,
        "input_snapshot_hash": "sha256:input",
        **context_override,
    }

    with pytest.raises(ValueError, match=message):
        await SkillExecutor(runner, provider).execute(
            call_id="call-1",
            skill_directory=Path("skills/generation"),
            inputs={},
            context=AgentExecutionContext(**context_data),
        )

    assert provider.call_count == 0


@pytest.mark.parametrize(
    ("raw_body", "error_type", "message"),
    [
        (b"[]", TypeError, "JSON object"),
        (b'{"score":NaN}', ValueError, "invalid JSON constant"),
    ],
)
# Mutation caught: accepting a non-object or non-standard constant as strict skill JSON.
@pytest.mark.asyncio
async def test_skill_executor_rejects_non_object_or_nonstandard_json_after_raw_persistence(
    tmp_path,
    raw_body: bytes,
    error_type: type[Exception],
    message: str,
) -> None:
    uow = SqliteUnitOfWork(f"sqlite:///{tmp_path / 'strict-json.db'}")
    uow.create_schema()
    uow.create_run("run-1", manifest={})
    uow.enqueue_tasks(
        [
            NewTask(
                task_id="task-1",
                run_id="run-1",
                idempotency_key="generation:run-1:1",
                intent_type="generate",
                payload={},
            )
        ]
    )
    runner = ExternalCallRunner(
        SimpleNamespace(
            uow=uow,
            artifacts=FilesystemArtifactStore(tmp_path / "artifacts"),
        )
    )

    with pytest.raises(error_type, match=message):
        await SkillExecutor(runner, FakeLLMProvider([raw_body])).execute(
            call_id="call-1",
            skill_directory=Path("skills/generation"),
            inputs={},
            context=AgentExecutionContext(
                run_id="run-1",
                task_id="task-1",
                idempotency_key="generation:run-1:1",
                skill_id="generation",
                skill_version="0.1.0",
                output_schema_version=1,
                input_snapshot_hash="sha256:input",
            ),
        )

    assert uow.external_call_state("call-1") == "validation_failed"


def _content_hash(payload: dict) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class _CoreHarness:
    def __init__(self, root: Path) -> None:
        self.root = root

    @staticmethod
    def _enrich_payloads(responses: list[dict]) -> list[dict]:
        payloads: list[dict] = []
        for index, response in enumerate(responses):
            payload = copy.deepcopy(response["payload"])
            if response["skill"] == "generation":
                for hypothesis_index, hypothesis in enumerate(payload["hypotheses"], start=1):
                    hypothesis_id = f"h-{hypothesis_index}"
                    hypothesis["hypothesis_id"] = hypothesis_id
                    hypothesis["content_hash"] = _content_hash(hypothesis)
            elif response["skill"] == "reflection":
                payload.update(
                    {
                        "hypothesis_id": response["hypothesis_id"],
                        "stage": response["stage"],
                        "review_id": f"review-{index}",
                    }
                )
            elif response["skill"] == "evolution":
                payload.update(
                    {
                        "hypothesis_id": "h-3",
                        "content_id": payload["child_content_id"],
                    }
                )
                payload["content_hash"] = _content_hash(payload)
            payloads.append(payload)
        return payloads

    @staticmethod
    def _task_id(index: int, response: dict) -> str:
        if response["skill"] == "reflection":
            return f"review:{response['stage']}:{response['hypothesis_id']}"
        return f"scenario:{response['skill']}:{index}"

    @staticmethod
    def _persisted_task_ids(uow: SqliteUnitOfWork) -> set[str]:
        with uow.engine.connect() as connection:
            rows = connection.execute(text("SELECT task_id FROM tasks")).all()
        return {row.task_id for row in rows}

    def run_trace(self, trace_path: str) -> SimpleNamespace:
        return asyncio.run(self._run_trace(Path(trace_path)))

    async def _run_trace(self, trace_path: Path) -> SimpleNamespace:
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
        if trace["trace_version"] != 1:
            raise ValueError("unsupported core trace version")
        responses = trace["responses"]
        payloads = self._enrich_payloads(responses)

        uow = SqliteUnitOfWork(f"sqlite:///{self.root / 'core-loop.db'}")
        uow.create_schema()
        uow.create_run("run-1", manifest={"trace_version": 1})
        state_history = [uow.run_state("run-1")]
        epoch = TournamentEpoch(
            epoch_id="epoch-1",
            research_plan_version=1,
            evaluation_rules_hash="sha256:rules",
            ranking_prompt_hash="sha256:ranking-prompt",
            judge_profile_hash="sha256:judge",
            rating_policy_version="1",
            admission_policy_version="1",
            anchor_set_id="anchors-1",
        )
        started = uow.commit_domain_batch(
            run_id="run-1",
            expected_sequence=0,
            events=(
                NewEvent(event_type="RunStarted", payload={}),
                NewEvent(
                    event_type="TournamentEpochOpened",
                    payload=epoch.model_dump(mode="json"),
                ),
            ),
            target_run_state=RunState.RUNNING,
            idempotency_key="start:run-1",
        )
        state_history.append(uow.run_state("run-1"))
        expected_sequence = started.last_sequence
        supervisor = Supervisor(
            uow=uow,
            review_policy=ReviewPolicy(
                profile_id="core-trace",
                required_before_admission=(ReviewStage.FULL,),
            ),
        )
        provider = FakeLLMProvider(
            [
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                for payload in payloads
            ]
        )
        runner = ExternalCallRunner(
            SimpleNamespace(
                uow=uow,
                artifacts=FilesystemArtifactStore(self.root / "artifacts"),
            )
        )

        for index, (response, payload) in enumerate(zip(responses, payloads, strict=True)):
            task_id = self._task_id(index, response)
            try:
                uow.task_state(task_id)
            except KeyError:
                scheduled = supervisor.enqueue_task(
                    task=NewTask(
                        task_id=task_id,
                        run_id="run-1",
                        idempotency_key=task_id,
                        intent_type=f"run_{response['skill']}",
                        payload={
                            key: value for key, value in response.items() if key != "payload"
                        },
                    ),
                    expected_sequence=expected_sequence,
                )
                expected_sequence = scheduled.last_sequence
            uow.transition_task(task_id, TaskState.LEASED)
            uow.transition_task(task_id, TaskState.RUNNING)
            inputs = {
                "trace_index": index,
                **{key: value for key, value in response.items() if key != "payload"},
            }
            input_hash = _content_hash(inputs)
            result = await SkillExecutor(runner, provider).execute(
                call_id=f"call-{index}",
                skill_directory=Path("skills") / response["skill"],
                inputs=inputs,
                context=AgentExecutionContext(
                    run_id="run-1",
                    task_id=task_id,
                    idempotency_key=task_id,
                    skill_id=response["skill"],
                    skill_version="0.1.0",
                    output_schema_version=1,
                    input_snapshot_hash=input_hash,
                ),
            )
            assert result.payload == payload
            uow.transition_task(task_id, TaskState.RESULT_RECEIVED)
            committed = supervisor.handle_result(
                run_id="run-1",
                task_id=task_id,
                result=result,
                expected_sequence=expected_sequence,
            )
            expected_sequence = committed.last_sequence

        events = uow.load("run-1")
        child_events = [
            event
            for event in events
            if event.event_type == "HypothesisContentCreated"
            and event.payload.get("parent_content_ids")
        ]
        if len(child_events) != 1:
            raise ValueError("expected exactly one committed Evolution child")
        child_payload = child_events[0].payload
        child_id = child_payload.get("hypothesis_id")
        child_content_hash = child_payload.get("content_hash")
        if child_id is None or child_content_hash is None:
            raise ValueError("committed Evolution child identity is incomplete")
        if not isinstance(child_id, str) or not isinstance(child_content_hash, str):
            raise TypeError("committed Evolution child identity must be strings")
        child_reviews = [
            event
            for event in events
            if event.event_type == "ReviewCompleted"
            and event.payload.get("hypothesis_id") == child_id
        ]
        completed_stages = {
            event.payload["stage"]
            for event in child_reviews
        }
        safety_verdicts = [
            event.payload["safety_passed"]
            for event in child_reviews
            if "safety_passed" in event.payload
        ]
        if len(safety_verdicts) != 1 or not isinstance(safety_verdicts[0], bool):
            raise ValueError("committed Reflection safety_passed verdict is required")
        child_proximity = [
            event
            for event in events
            if event.event_type == "ProximityAssessed"
            and child_id
            in {event.payload.get("left_id"), event.payload.get("right_id")}
        ]
        if len(child_proximity) != 1:
            raise ValueError("exactly one committed child Proximity result is required")
        duplicate_likelihood = child_proximity[0].payload.get("duplicate_likelihood")
        threshold = trace["policy"].get("duplicate_likelihood_threshold")
        if duplicate_likelihood is None:
            raise ValueError("committed Proximity duplicate_likelihood is required")
        if (
            isinstance(duplicate_likelihood, bool)
            or not isinstance(duplicate_likelihood, int | float)
        ):
            raise TypeError("committed Proximity duplicate_likelihood must be numeric")
        if threshold is None:
            raise ValueError("duplicate_likelihood_threshold policy is required")
        if isinstance(threshold, bool) or not isinstance(threshold, int | float):
            raise TypeError("duplicate_likelihood_threshold policy must be numeric")
        duplicate = duplicate_likelihood >= threshold
        admission = supervisor.admit_hypothesis(
            run_id="run-1",
            expected_sequence=expected_sequence,
            hypothesis_id=child_id,
            content_hash=child_content_hash,
            safety_passed=safety_verdicts[0],
            required_stages=required_review_stages(supervisor.review_policy),
            completed_stages=completed_stages,
            novelty_required=trace["policy"]["novelty_required"],
            novelty_assessment=None,
            proximity_complete=True,
            duplicate=duplicate,
        )
        if admission.entry is None or admission.commit is None:
            raise AssertionError(f"child admission failed: {admission.decision}")
        expected_sequence = admission.commit.last_sequence

        stopping = supervisor.request_normal_completion(
            "run-1",
            expected_sequence=expected_sequence,
            reason="trace_exhausted",
        )
        state_history.append(uow.run_state("run-1"))
        for state in (TaskState.LEASED, TaskState.RUNNING, TaskState.RESULT_RECEIVED):
            uow.transition_task("finalize:run-1", state)
        supervisor.apply_finalization(
            "run-1",
            expected_sequence=stopping.last_sequence,
            completeness="complete",
        )
        state_history.append(uow.run_state("run-1"))
        committed_events = uow.load("run-1")
        return SimpleNamespace(
            final_state=uow.run_state("run-1"),
            state_history=state_history,
            persisted_task_ids=self._persisted_task_ids(uow),
            task_enqueued_events=tuple(
                event for event in committed_events if event.event_type == "TaskEnqueued"
            ),
            child=SimpleNamespace(initial_rating=admission.entry.rating),
        )


@pytest.fixture
def core_harness(tmp_path) -> _CoreHarness:
    return _CoreHarness(tmp_path)


# Mutation caught: bypassing the real core loop, leaking task authority, skipping stopping,
# or carrying a parent rating into the evolved child.
def test_fake_trace_reaches_finalization_without_agent_created_tasks(core_harness) -> None:
    result = core_harness.run_trace("tests/scenario/fixtures/core_loop_trace.json")
    assert result.final_state == "completed"
    assert result.state_history[-2:] == ["stopping", "completed"]
    assert result.persisted_task_ids == {
        event.payload["task_id"] for event in result.task_enqueued_events
    }
    assert all(
        event.payload["created_by"] == "supervisor"
        for event in result.task_enqueued_events
    )
    assert result.child.initial_rating == 1200.0


def _write_trace_variant(tmp_path: Path, mutate) -> Path:
    trace = json.loads(
        Path("tests/scenario/fixtures/core_loop_trace.json").read_text(encoding="utf-8")
    )
    mutate(trace)
    destination = tmp_path / "trace.json"
    destination.write_text(json.dumps(trace), encoding="utf-8")
    return destination


@pytest.mark.parametrize("missing_field", ["safety_passed", "duplicate_likelihood"])
# Mutation caught: admitting when a required scientific verdict is absent from committed results.
def test_fake_trace_fails_closed_when_admission_evidence_is_missing(
    core_harness,
    tmp_path: Path,
    missing_field: str,
) -> None:
    def remove_field(trace: dict) -> None:
        if missing_field == "safety_passed":
            response = next(
                item
                for item in trace["responses"]
                if item.get("hypothesis_id") == "h-3" and item.get("stage") == "initial_review"
            )
        else:
            response = next(
                item
                for item in trace["responses"]
                if item["skill"] == "proximity" and item["payload"].get("left_id") == "h-3"
            )
        response["payload"].pop(missing_field)

    trace_path = _write_trace_variant(tmp_path, remove_field)

    with pytest.raises(ValueError, match=missing_field):
        core_harness.run_trace(str(trace_path))


# Mutation caught: ignoring the committed duplicate likelihood or its explicit policy threshold.
def test_fake_trace_rejects_child_at_or_above_duplicate_threshold(
    core_harness,
    tmp_path: Path,
) -> None:
    def mark_duplicate(trace: dict) -> None:
        response = next(
            item
            for item in trace["responses"]
            if item["skill"] == "proximity" and item["payload"].get("left_id") == "h-3"
        )
        response["payload"]["duplicate_likelihood"] = 0.5

    trace_path = _write_trace_variant(tmp_path, mark_duplicate)

    with pytest.raises(AssertionError, match="child admission failed"):
        core_harness.run_trace(str(trace_path))
