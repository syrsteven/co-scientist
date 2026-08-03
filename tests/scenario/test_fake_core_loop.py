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
from co_scientist.domain.review import ReviewPolicy, ReviewStage
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
    def _enrich_payloads(responses: list[dict]) -> tuple[list[dict], dict[str, str]]:
        payloads: list[dict] = []
        content_hashes: dict[str, str] = {}
        for index, response in enumerate(responses):
            payload = copy.deepcopy(response["payload"])
            if response["skill"] == "generation":
                for hypothesis_index, hypothesis in enumerate(payload["hypotheses"], start=1):
                    hypothesis_id = f"h-{hypothesis_index}"
                    hypothesis["hypothesis_id"] = hypothesis_id
                    hypothesis["content_hash"] = _content_hash(hypothesis)
                    content_hashes[hypothesis_id] = hypothesis["content_hash"]
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
                content_hashes["h-3"] = payload["content_hash"]
            payloads.append(payload)
        return payloads, content_hashes

    @staticmethod
    def _task_id(index: int, response: dict) -> str:
        if response["skill"] == "reflection":
            return f"review:{response['stage']}:{response['hypothesis_id']}"
        return f"scenario:{response['skill']}:{index}"

    @staticmethod
    def _persisted_tasks(uow: SqliteUnitOfWork) -> tuple[NewTask, ...]:
        with uow.engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT task_id, run_id, idempotency_key, intent_type, payload_json "
                    "FROM tasks ORDER BY rowid"
                )
            ).all()
        return tuple(
            NewTask(
                task_id=row.task_id,
                run_id=row.run_id,
                idempotency_key=row.idempotency_key,
                intent_type=row.intent_type,
                payload=json.loads(row.payload_json),
            )
            for row in rows
        )

    def run_trace(self, trace_path: str) -> SimpleNamespace:
        return asyncio.run(self._run_trace(Path(trace_path)))

    async def _run_trace(self, trace_path: Path) -> SimpleNamespace:
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
        if trace["trace_version"] != 1:
            raise ValueError("unsupported core trace version")
        responses = trace["responses"]
        payloads, content_hashes = self._enrich_payloads(responses)

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
                uow.enqueue_tasks(
                    [
                        NewTask(
                            task_id=task_id,
                            run_id="run-1",
                            idempotency_key=task_id,
                            intent_type=f"run_{response['skill']}",
                            payload={key: value for key, value in response.items() if key != "payload"},
                        )
                    ]
                )
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

        child_admission = trace["child_admission"]
        events = uow.load("run-1")
        completed_stages = {
            event.payload["stage"]
            for event in events
            if event.event_type == "ReviewCompleted"
            and event.payload.get("hypothesis_id") == child_admission["hypothesis_id"]
        }
        proximity_complete = any(
            event.event_type == "ProximityAssessed"
            and child_admission["hypothesis_id"]
            in {event.payload.get("left_id"), event.payload.get("right_id")}
            for event in events
        )
        admission = supervisor.admit_hypothesis(
            run_id="run-1",
            expected_sequence=expected_sequence,
            hypothesis_id=child_admission["hypothesis_id"],
            content_hash=content_hashes[child_admission["hypothesis_id"]],
            safety_passed=child_admission["safety_passed"],
            required_stages=set(child_admission["required_stages"]),
            completed_stages=completed_stages,
            novelty_required=child_admission["novelty_required"],
            novelty_assessment=None,
            proximity_complete=proximity_complete,
            duplicate=child_admission["duplicate"],
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
        return SimpleNamespace(
            final_state=uow.run_state("run-1"),
            state_history=state_history,
            tasks=self._persisted_tasks(uow),
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
    assert all(task.created_by == "supervisor" for task in result.tasks)
    assert result.child.initial_rating == 1200.0
