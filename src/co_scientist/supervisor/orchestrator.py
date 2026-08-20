"""Deterministic application-level orchestration owned by the Supervisor."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from co_scientist.adapters.persistence.sqlite import CommitResult, SqliteUnitOfWork
from co_scientist.agents.payloads import (
    EvolutionResultV1,
    GenerationResultV1,
    MetaReviewResultV1,
    ProximityResultV1,
    RankingResultV1,
    ReflectionResultV1,
    validate_output_payload,
)
from co_scientist.agents.result import AgentExecutionContext, AgentResult
from co_scientist.domain.admission import (
    AdmissionEvidenceSnapshot,
    admission_policy_from_manifest,
    reduce_admission_evidence,
)
from co_scientist.domain.budget import BudgetEstimate, CostEntry
from co_scientist.domain.convergence import ConvergenceCheckpoint, StopDecision, evaluate_stop
from co_scientist.domain.hypothesis import (
    compute_hypothesis_content_hash,
    hypothesis_content_from_draft,
)
from co_scientist.domain.research_plan import ResearchPlan
from co_scientist.domain.review import (
    ReviewPolicy,
    ReviewStage,
)
from co_scientist.domain.run_mutations import RunMutationKind, validate_run_mutation
from co_scientist.domain.states import ExternalCallState, RunState, TaskState
from co_scientist.domain.task import NewTask, TaskLeaseFence, TaskMutation
from co_scientist.domain.tournament import (
    MatchDecision,
    MatchResult,
    TournamentEntry,
    TournamentEpoch,
    admit_entry,
    apply_match,
    get_rating_policy,
    validate_match_contract,
)
from co_scientist.events.models import DomainEvent, NewEvent
from co_scientist.events.reducers import replay_tournament
from co_scientist.ports.event_store import ConcurrencyConflict
from co_scientist.runtime.checkpoints import ConvergenceCheckpointBuilder
from co_scientist.runtime.external_calls import prompt_hash, request_fingerprint
from co_scientist.runtime.task_payload import WorkerTaskPayload
from co_scientist.skills.loader import load_skill, resolve_core_skill_contract
from co_scientist.supervisor.followups import FollowupIntent, derive_followup_intents


class AdmissionDecision(BaseModel):
    """Explain whether a candidate satisfies all independent admission gates."""

    model_config = ConfigDict(frozen=True)

    admitted: bool
    missing_requirements: tuple[str, ...] = ()
    conflicting_evidence: tuple[str, ...] = ()


class AdmissionOutcome(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    decision: AdmissionDecision
    entry: TournamentEntry | None = None
    commit: CommitResult | None = None


def plan_revision_action(
    old: ResearchPlan,
    new: ResearchPlan,
) -> Literal["new_epoch", "fork_run"]:
    """Classify an accepted plan revision without carrying ratings across epochs."""

    if old.run_id != new.run_id:
        raise ValueError("ResearchPlan revision must belong to the same run")
    if new.version <= old.version:
        raise ValueError("ResearchPlan version must increase")
    return "fork_run" if old.scientific_scope_hash != new.scientific_scope_hash else "new_epoch"


class PlanRevisionOutcome(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    action: Literal["new_epoch", "fork_run"]
    commit: CommitResult
    next_epoch: TournamentEpoch | None = None


class TickOutcome(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    decision: StopDecision
    commit: CommitResult | None = None


class AdvanceOutcome(BaseModel):
    """One Supervisor-owned scheduling or stopping decision."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    action: Literal["waiting", "scheduled", "admitted", "checkpointed", "terminal"]
    commit: CommitResult | None = None


def _as_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    return 0


def _as_float(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError("persisted rating value must be numeric")
    return float(value)


class Supervisor:
    """Sole authority for applying results, creating tasks, and ending runs."""

    def __init__(self, *, uow: SqliteUnitOfWork, review_policy: ReviewPolicy) -> None:
        self.uow = uow
        self.review_policy = review_policy

    @staticmethod
    def _task_enqueued_event(
        task: NewTask,
        *,
        causation_id: str | None = None,
        correlation_id: str | None = None,
    ) -> NewEvent:
        return NewEvent(
            event_type="TaskEnqueued",
            payload=task.model_dump(mode="json"),
            causation_id=causation_id,
            correlation_id=correlation_id,
        )

    def enqueue_task(self, *, task: NewTask, expected_sequence: int) -> CommitResult:
        """Atomically persist a Supervisor-owned task and its creator provenance."""

        validate_run_mutation(
            RunState(self.uow.run_state(task.run_id)),
            (
                RunMutationKind.ENQUEUE_FINALIZATION_TASK
                if task.intent_type == "finalize_run"
                else RunMutationKind.ENQUEUE_EXPLORATION_TASK
            ),
            task_intent=task.intent_type,
        )
        return self.uow.commit_domain_batch(
            run_id=task.run_id,
            expected_sequence=expected_sequence,
            events=(self._task_enqueued_event(task, correlation_id=task.run_id),),
            followup_tasks=(task,),
            idempotency_key=f"task-enqueue:{task.idempotency_key}",
        )

    def _epoch_state(
        self,
        run_id: str,
    ) -> tuple[TournamentEpoch | None, tuple[TournamentEpoch, ...]]:
        return self._epoch_state_from_events(self.uow.load(run_id))

    @staticmethod
    def _epoch_state_from_events(
        events: Sequence[DomainEvent],
    ) -> tuple[TournamentEpoch | None, tuple[TournamentEpoch, ...]]:
        active: TournamentEpoch | None = None
        history: list[TournamentEpoch] = []
        for event in events:
            if event.event_type == "TournamentEpochOpened":
                active = TournamentEpoch.model_validate(event.payload)
                history.append(active)
            elif (
                event.event_type == "TournamentEpochClosed"
                and active is not None
                and event.payload.get("epoch_id") == active.epoch_id
            ):
                active = None
        return active, tuple(history)

    def _active_epoch(self, run_id: str) -> TournamentEpoch:
        active, _ = self._epoch_state(run_id)
        if active is None:
            raise ValueError(f"run {run_id} has no active TournamentEpoch")
        return active

    @staticmethod
    def _replay_admission(
        commit: CommitResult,
        *,
        run_id: str,
        hypothesis_id: str,
    ) -> AdmissionOutcome:
        events = commit.events
        expected_contract = (
            ("HypothesisTournamentReady", 2),
            ("TournamentEntryCreated", 1),
            ("InitialRatingAssigned", 1),
        )
        if (
            len(events) != len(expected_contract)
            or tuple((event.event_type, event.schema_version) for event in events)
            != expected_contract
            or any(event.run_id != run_id for event in events)
        ):
            raise ValueError("idempotency key belongs to a different admission")
        snapshot = AdmissionEvidenceSnapshot.model_validate(events[0].payload)
        entry = TournamentEntry.model_validate(events[1].payload)
        rating = events[2].payload
        if (
            snapshot.run_id != run_id
            or snapshot.hypothesis_id != hypothesis_id
            or snapshot.missing_requirements
            or snapshot.conflicting_evidence
            or entry.hypothesis_id != hypothesis_id
            or entry.epoch_id != snapshot.epoch_id
            or entry.content_hash != snapshot.content_hash
            or rating.get("hypothesis_id") != hypothesis_id
            or rating.get("epoch_id") != snapshot.epoch_id
            or rating.get("rating") != entry.rating
            or rating.get("rating_policy_version") != snapshot.rating_policy_version
        ):
            raise ValueError("idempotency key belongs to a different admission")
        return AdmissionOutcome(
            decision=AdmissionDecision(admitted=True),
            entry=entry,
            commit=commit,
        )

    @staticmethod
    def _validate_submitted_result(
        *,
        run_id: str,
        task_id: str,
        result: AgentResult,
        call_state: ExternalCallState,
        persisted_result: Mapping[str, Any] | None,
        task_state: TaskState,
    ) -> None:
        if result.run_id != run_id or result.task_id != task_id:
            raise ValueError("AgentResult does not match Supervisor command ownership")
        if call_state not in {
            ExternalCallState.AGENT_RESULT_SUBMITTED,
            ExternalCallState.DOMAIN_RESULT_APPLIED,
        }:
            raise ValueError("AgentResult has not reached agent_result_submitted")
        if persisted_result != result.model_dump(mode="json"):
            raise ValueError("AgentResult does not match the durably submitted result")
        terminal_task_state = {
            "completed": TaskState.SUCCEEDED,
            "partial": TaskState.PENDING,
            "rejected": TaskState.FAILED,
            "failed": TaskState.FAILED,
        }[result.status]
        valid_task_state = (
            task_state in {TaskState.RUNNING, TaskState.RESULT_RECEIVED}
            if call_state is ExternalCallState.AGENT_RESULT_SUBMITTED
            else task_state is terminal_task_state
        )
        if not valid_task_state:
            raise ValueError("task must be result_received before domain application")

    @staticmethod
    def _audit_event_for_result(result: AgentResult) -> NewEvent:
        event_type = {
            "partial": "AgentResultPartial",
            "rejected": "AgentResultRejected",
            "failed": "AgentResultFailed",
        }[result.status]
        return NewEvent(
            event_type=event_type,
            payload={
                "source_result_id": result.result_id,
                "source_task_id": result.task_id,
                "status": result.status,
            },
            causation_id=result.result_id,
            correlation_id=result.run_id,
        )

    @staticmethod
    def _events_for_result(result: AgentResult) -> tuple[NewEvent, ...]:
        common = {
            "source_result_id": result.result_id,
            "source_task_id": result.task_id,
            "status": result.status,
        }
        payload = result.payload
        if result.skill_id == "generation":
            generation = GenerationResultV1.model_validate(payload)
            events: list[NewEvent] = []
            for draft in generation.hypotheses:
                content = hypothesis_content_from_draft(draft)
                events.append(
                    NewEvent(
                        event_type="HypothesisContentCreated",
                        schema_version=2,
                        payload={
                            **content.model_dump(mode="json"),
                            "content_hash": compute_hypothesis_content_hash(content),
                            "hypothesis_id": draft.hypothesis_id,
                            "research_plan_version": generation.research_plan_version,
                            **common,
                        },
                        causation_id=result.result_id,
                        correlation_id=result.run_id,
                    )
                )
            return tuple(events)

        if result.skill_id == "evolution":
            evolution = EvolutionResultV1.model_validate(payload)
            return tuple(
                NewEvent(
                    event_type="HypothesisContentCreated",
                    schema_version=2,
                    payload={
                        **content.model_dump(mode="json"),
                        "content_hash": compute_hypothesis_content_hash(content),
                        "hypothesis_id": draft.hypothesis_id,
                        "research_plan_version": evolution.research_plan_version,
                        "change_rationale": evolution.change_rationales[draft.hypothesis_id],
                        **common,
                    },
                    causation_id=result.result_id,
                    correlation_id=result.run_id,
                )
                for draft in evolution.children
                for content in (hypothesis_content_from_draft(draft),)
            )

        if result.skill_id == "reflection":
            reflection = ReflectionResultV1.model_validate(payload)
            review_payload = reflection.model_dump(
                mode="json",
                exclude={"schema_version", "novelty_assessment"},
            )
            if reflection.stage is ReviewStage.INITIAL:
                review_payload["safety_passed"] = reflection.safety_status == "passed"
            events = [
                NewEvent(
                    event_type="ReviewCompleted",
                    schema_version=2,
                    payload={**review_payload, **common},
                    causation_id=result.result_id,
                    correlation_id=result.run_id,
                )
            ]
            if reflection.novelty_assessment is not None:
                events.append(
                    NewEvent(
                        event_type="NoveltyAssessmentRecorded",
                        schema_version=1,
                        payload={
                            **reflection.novelty_assessment.model_dump(mode="json"),
                            **common,
                        },
                        causation_id=result.result_id,
                        correlation_id=result.run_id,
                    )
                )
            return tuple(events)

        if result.skill_id == "ranking":
            ranking = RankingResultV1.model_validate(payload)
            winner_id = (
                ranking.left_id
                if ranking.winner_slot == 1
                else ranking.right_id
                if ranking.winner_slot == 2
                else None
            )
            ranking_payload = ranking.model_dump(
                mode="json",
                exclude={"schema_version", "decision_status", "winner_slot"},
            )
            return (
                NewEvent(
                    event_type="MatchEvaluated",
                    schema_version=2,
                    payload={
                        **ranking_payload,
                        "decision": ranking.decision_status.value,
                        "winner_id": winner_id,
                        **common,
                    },
                    causation_id=result.result_id,
                    correlation_id=result.run_id,
                ),
            )

        if result.skill_id == "proximity":
            event_type = "ProximityAssessed"
            terminal_payload: ProximityResultV1 | MetaReviewResultV1 = (
                ProximityResultV1.model_validate(payload)
            )
        elif result.skill_id == "meta_review":
            event_type = "MetaReviewCompleted"
            terminal_payload = MetaReviewResultV1.model_validate(payload)
        else:
            raise ValueError(f"unsupported skill result: {result.skill_id}")
        return (
            NewEvent(
                event_type=event_type,
                schema_version=2,
                payload={
                    **terminal_payload.model_dump(mode="json", exclude={"schema_version"}),
                    **common,
                },
                causation_id=result.result_id,
                correlation_id=result.run_id,
            ),
        )

    def _followup_tasks(
        self,
        *,
        run_id: str,
        events: Sequence[NewEvent],
        source_result: AgentResult,
    ) -> tuple[NewTask, ...]:
        approved: dict[str, FollowupIntent] = {}
        for event in events:
            intents = derive_followup_intents(
                event_type=event.event_type,
                payload=event.payload,
                review_policy=self.review_policy,
            )
            for intent in intents:
                key = f"review:{intent.intent_type.removeprefix('run_')}:{intent.target_id}"
                approved[key] = intent
        tasks: list[NewTask] = []
        for task_id, intent in approved.items():
            content_hash = next(
                (
                    str(event.payload["content_hash"])
                    for event in events
                    if event.event_type == "HypothesisContentCreated"
                    and event.payload.get("hypothesis_id") == intent.target_id
                ),
                None,
            )
            if content_hash is None:
                raise ValueError("follow-up task requires immutable hypothesis content")
            directory = Path("skills/reflection")
            manifest = load_skill(directory)
            inputs = {
                "hypothesis_id": intent.target_id,
                "content_hash": content_hash,
                "review_stage": intent.intent_type.removeprefix("run_"),
            }
            payload = WorkerTaskPayload(
                skill_id=manifest.id,
                skill_version=manifest.version,
                output_schema_id=manifest.output_schema,
                output_schema_version=1,
                research_plan_version=source_result.research_plan_version,
                provider_id=source_result.provider,
                model_or_tool=source_result.model_or_tool,
                inputs=inputs,
                input_snapshot_hash=request_fingerprint(inputs),
                prompt_hash=prompt_hash(
                    (directory / manifest.prompt_path).read_text(encoding="utf-8")
                ),
                budget_estimate=BudgetEstimate(model_calls=1),
            )
            tasks.append(
                NewTask(
                    task_id=task_id,
                    run_id=run_id,
                    idempotency_key=task_id,
                    intent_type=intent.intent_type,
                    payload=payload.model_dump(mode="json"),
                )
            )
        return tuple(tasks)

    @staticmethod
    def _cost_entry(
        *,
        run_id: str,
        external_call_id: str,
        usage: Mapping[str, Any],
    ) -> CostEntry:
        nested_tokens = usage.get("tokens")
        tokens = nested_tokens if isinstance(nested_tokens, Mapping) else {}
        return CostEntry(
            cost_entry_id=f"cost:{external_call_id}",
            run_id=run_id,
            external_call_id=external_call_id,
            input_tokens=_as_int(usage.get("input_tokens", tokens.get("input"))),
            output_tokens=_as_int(usage.get("output_tokens", tokens.get("output"))),
            cost_usd=Decimal(str(usage.get("cost_usd", "0"))),
            pricing_version=str(usage.get("pricing_version", "unpriced")),
        )

    def _rating_events_for_result(self, run_id: str, result: AgentResult) -> tuple[NewEvent, ...]:
        """Persist authoritative rating changes for a complete match contract."""

        if result.skill_id != "ranking":
            return ()
        required = {
            "match_id",
            "epoch_id",
            "left_id",
            "left_content_hash",
            "right_id",
            "right_content_hash",
            "decision_status",
            "research_plan_version",
            "evaluation_rules_hash",
            "ranking_prompt_hash",
            "judge_profile_hash",
            "rating_policy_version",
            "admission_policy_version",
        }
        missing = sorted(required.difference(result.payload))
        if missing:
            raise ValueError(f"completed ranking result is missing required fields: {missing}")
        stream = self.uow.load(run_id)
        ranking = RankingResultV1.model_validate(result.payload)
        winner_id = (
            ranking.left_id
            if ranking.winner_slot == 1
            else ranking.right_id
            if ranking.winner_slot == 2
            else None
        )
        match = MatchResult(
            match_id=ranking.match_id,
            epoch_id=ranking.epoch_id,
            left_id=ranking.left_id,
            right_id=ranking.right_id,
            decision=ranking.decision_status,
            winner_id=winner_id,
        )
        if result.prompt_hash != result.payload.get("ranking_prompt_hash"):
            raise ValueError("ranking execution prompt hash does not match match contract")
        epoch = self._active_epoch(run_id)
        if match.epoch_id != epoch.epoch_id:
            raise ValueError(
                f"match {match.match_id} epoch {match.epoch_id} is not active epoch {epoch.epoch_id}"
            )
        validate_match_contract(
            epoch,
            plan_version=int(result.payload["research_plan_version"]),
            rules_hash=str(result.payload["evaluation_rules_hash"]),
            prompt_hash=str(result.payload["ranking_prompt_hash"]),
            judge_hash=str(result.payload["judge_profile_hash"]),
            rating_policy=str(result.payload["rating_policy_version"]),
            admission_policy=str(result.payload["admission_policy_version"]),
        )
        participants = {match.left_id, match.right_id}
        entry_ids = {
            str(event.payload.get("hypothesis_id"))
            for event in stream
            if event.event_type == "TournamentEntryCreated"
            and event.payload.get("epoch_id") == epoch.epoch_id
        }
        initial_rating_ids = {
            str(event.payload.get("hypothesis_id"))
            for event in stream
            if event.event_type == "InitialRatingAssigned"
            and event.payload.get("epoch_id") == epoch.epoch_id
        }
        if not participants.issubset(entry_ids & initial_rating_ids):
            raise ValueError(
                f"match {match.match_id} references a participant not admitted to active epoch"
            )
        persisted_matches = [
            event
            for event in stream
            if event.event_type == "MatchEvaluated"
            and event.payload.get("match_id") == match.match_id
        ]
        persisted_ratings = [
            event
            for event in stream
            if event.event_type == "RatingUpdated"
            and event.payload.get("match_id") == match.match_id
        ]
        if persisted_matches or persisted_ratings:
            persisted_ranking_payload = ranking.model_dump(
                mode="json",
                exclude={"schema_version", "decision_status", "winner_slot"},
            )
            expected_payload = {
                **persisted_ranking_payload,
                "decision": match.decision.value,
                "winner_id": match.winner_id,
                "source_result_id": result.result_id,
                "source_task_id": result.task_id,
                "status": result.status,
            }
            normalized_expected_payload = NewEvent(
                event_type="MatchEvaluated",
                schema_version=2,
                payload=expected_payload,
            ).payload
            if (
                len(persisted_matches) != 1
                or persisted_matches[0].payload != normalized_expected_payload
                or persisted_matches[0].causation_id != result.result_id
                or persisted_matches[0].correlation_id != run_id
            ):
                raise ValueError(f"conflicting duplicate match_id: {match.match_id}")
            if match.decision is not MatchDecision.DECISIVE:
                if persisted_ratings:
                    raise ValueError(f"non-decisive duplicate match has ratings: {match.match_id}")
                return ()
            if len(persisted_ratings) != 2:
                raise ValueError(
                    f"decisive duplicate match has incomplete ratings: {match.match_id}"
                )
            match_index = stream.index(persisted_matches[0])
            prior_ratings = replay_tournament(stream[:match_index]).ratings.get(match.epoch_id, {})
            try:
                before_left = float(prior_ratings[match.left_id])
                before_right = float(prior_ratings[match.right_id])
            except KeyError as error:
                raise ValueError(
                    f"duplicate match {match.match_id} references an unrated TournamentEntry"
                ) from error
            policy = get_rating_policy(str(result.payload["rating_policy_version"]))
            after_left, after_right = apply_match(
                before_left,
                before_right,
                match,
                k_factor=policy.k_factor,
            )
            expected_ratings = {
                match.left_id: (before_left, after_left),
                match.right_id: (before_right, after_right),
            }
            for offset, event in enumerate(persisted_ratings, start=1):
                hypothesis_id = event.payload.get("hypothesis_id")
                expected = expected_ratings.pop(str(hypothesis_id), None)
                if (
                    expected is None
                    or event.sequence != persisted_matches[0].sequence + offset
                    or event.payload.get("epoch_id") != match.epoch_id
                    or event.payload.get("rating_policy_version") != policy.version
                    or _as_float(event.payload.get("before_rating")) != expected[0]
                    or _as_float(event.payload.get("rating")) != expected[1]
                    or event.causation_id != result.result_id
                    or event.correlation_id != run_id
                ):
                    raise ValueError(
                        f"duplicate match rating provenance mismatch: {match.match_id}"
                    )
            if expected_ratings:
                raise ValueError(f"duplicate match rating participants mismatch: {match.match_id}")
            return tuple(
                NewEvent(
                    event_type=event.event_type,
                    schema_version=event.schema_version,
                    payload=event.payload,
                    causation_id=event.causation_id,
                    correlation_id=event.correlation_id,
                )
                for event in persisted_ratings
            )
        if match.decision is not MatchDecision.DECISIVE:
            return ()
        policy = get_rating_policy(epoch.rating_policy_version)
        epoch_ratings = replay_tournament(stream).ratings.get(match.epoch_id, {})
        try:
            before_left = float(epoch_ratings[match.left_id])
            before_right = float(epoch_ratings[match.right_id])
        except KeyError as error:
            raise ValueError(
                f"match {match.match_id} references an unrated TournamentEntry"
            ) from error
        after_left, after_right = apply_match(
            before_left,
            before_right,
            match,
            k_factor=policy.k_factor,
        )
        return tuple(
            NewEvent(
                event_type="RatingUpdated",
                payload={
                    "match_id": match.match_id,
                    "epoch_id": match.epoch_id,
                    "hypothesis_id": hypothesis_id,
                    "before_rating": before,
                    "rating": after,
                    "rating_policy_version": policy.version,
                },
                causation_id=result.result_id,
                correlation_id=run_id,
            )
            for hypothesis_id, before, after in (
                (match.left_id, before_left, after_left),
                (match.right_id, before_right, after_right),
            )
        )

    def handle_result(
        self,
        run_id: str,
        task_id: str,
        result: AgentResult,
        expected_sequence: int,
        *,
        reservation_id: str,
        fence: TaskLeaseFence,
    ) -> CommitResult:
        """Validate and atomically apply a durably submitted worker result."""

        self.uow.assert_domain_fence(
            external_call_id=result.external_call_id,
            reservation_id=reservation_id,
            fence=fence,
        )
        run_state = RunState(self.uow.run_state(run_id))
        validate_run_mutation(
            run_state,
            RunMutationKind.APPLY_SCIENTIFIC_RESULT,
            task_intent=self.uow.task_intent(task_id),
        )
        call = self.uow.get_external_call(result.external_call_id)
        if call.execution_context is None or call.agent_result is None:
            raise ValueError("external call has no durable typed result context")
        persisted_context = AgentExecutionContext.model_validate(call.execution_context)
        resolve_core_skill_contract(
            skill_id=persisted_context.skill_id,
            skill_version=persisted_context.skill_version,
            output_schema_id=persisted_context.output_schema_id,
        )
        persisted_data = dict(call.agent_result)
        context_data = persisted_context.model_dump(mode="json")
        for field, value in context_data.items():
            if persisted_data.get(field) != value:
                raise ValueError("durable AgentResult does not match execution context")
        persisted_status = persisted_data.get("status")
        if persisted_status not in {"completed", "partial", "rejected", "failed"}:
            raise ValueError("durable AgentResult has an invalid status")
        typed_payload = validate_output_payload(
            status=persisted_status,
            schema_id=persisted_context.output_schema_id,
            schema_version=persisted_context.output_schema_version,
            payload=persisted_data.get("payload", {}),
        )
        typed_plan_version = getattr(typed_payload, "research_plan_version", None)
        if (
            typed_plan_version is not None
            and typed_plan_version != persisted_context.research_plan_version
        ):
            raise ValueError("durable payload does not match execution research plan")
        durable_result = AgentResult.model_validate(persisted_data)
        self._validate_submitted_result(
            run_id=run_id,
            task_id=task_id,
            result=result,
            call_state=call.state,
            persisted_result=call.agent_result,
            task_state=TaskState(self.uow.task_state(task_id)),
        )
        if call.run_id != run_id or call.task_id != task_id:
            raise ValueError("external call does not match Supervisor command ownership")
        if (
            result.attempt != fence.attempt
            or result.reservation_id != reservation_id
            or call.attempt != fence.attempt
            or call.reservation_id != reservation_id
        ):
            raise ValueError("AgentResult does not match reservation and task lease fence")
        result = durable_result
        if result.status == "completed":
            rating_events = self._rating_events_for_result(run_id, result)
            events = (*self._events_for_result(result), *rating_events)
            if any(
                event.event_type in {"NoveltyAssessmentRecorded", "ProximityAssessed"}
                for event in events
            ):
                epoch_id = self._active_epoch(run_id).epoch_id
                events = tuple(
                    event.model_copy(
                        update={"payload": {**dict(event.payload), "epoch_id": epoch_id}}
                    )
                    if event.event_type
                    in {"NoveltyAssessmentRecorded", "ProximityAssessed"}
                    else event
                    for event in events
                )
            if result.skill_id == "ranking":
                epoch = self._active_epoch(run_id)
                anchor_ids = {
                    str(member.get("anchor_id"))
                    for anchor_set in self.uow.run_manifest(run_id).get("anchor_sets", [])
                    if anchor_set.get("anchor_set_id") == epoch.anchor_set_id
                    for member in anchor_set.get("members", [])
                }
                events = tuple(
                    event.model_copy(
                        update={
                            "payload": {
                                **dict(event.payload),
                                "anchor_set_id": (
                                    epoch.anchor_set_id
                                    if {
                                        str(event.payload.get("left_id")),
                                        str(event.payload.get("right_id")),
                                    }
                                    & anchor_ids
                                    else None
                                ),
                                "comparison_kind": (
                                    "fixed_anchor"
                                    if {
                                        str(event.payload.get("left_id")),
                                        str(event.payload.get("right_id")),
                                    }
                                    & anchor_ids
                                    else "opportunistic"
                                ),
                            }
                        }
                    )
                    if event.event_type == "MatchEvaluated"
                    else event
                    for event in events
                )
            followups = (
                ()
                if run_state is RunState.STOPPING
                else self._followup_tasks(run_id=run_id, events=events, source_result=result)
            )
            events = (
                *events,
                *(
                    self._task_enqueued_event(
                        task,
                        causation_id=result.result_id,
                        correlation_id=run_id,
                    )
                    for task in followups
                ),
            )
            task_target = TaskState.SUCCEEDED
        else:
            events = (self._audit_event_for_result(result),)
            followups = ()
            task_target = TaskState.PENDING if result.status == "partial" else TaskState.FAILED
        return self.uow.commit_domain_batch(
            run_id=run_id,
            expected_sequence=expected_sequence,
            events=events,
            task_mutations=(TaskMutation(task_id=task_id, target_state=task_target),),
            followup_tasks=followups,
            idempotency_key=result.idempotency_key,
            external_call_id=result.external_call_id,
            reservation_id=reservation_id,
            lease_fence=fence,
            settle_reservation_id=reservation_id,
            cost_entries=(
                self._cost_entry(
                    run_id=run_id,
                    external_call_id=result.external_call_id,
                    usage=call.usage,
                ),
            ),
        )

    def accept_plan_revision(
        self,
        *,
        old: ResearchPlan,
        new: ResearchPlan,
        expected_sequence: int,
        next_epoch_id: str | None = None,
        next_anchor_set_id: str | None = None,
    ) -> PlanRevisionOutcome:
        """Atomically accept a plan and close its epoch, opening or forking by policy."""

        action = plan_revision_action(old, new)
        stream = self.uow.load(old.run_id)
        already_accepted = any(
            event.event_type == "ResearchPlanAccepted"
            and event.payload.get("version") == new.version
            and event.payload.get("action") == action
            for event in stream
        )
        active_epoch, epoch_history = self._epoch_state(old.run_id)
        if already_accepted:
            current_epoch = next(
                (
                    epoch
                    for epoch in reversed(epoch_history)
                    if epoch.research_plan_version == old.version
                ),
                None,
            )
            if current_epoch is None:
                raise ValueError("accepted plan revision has no durable source epoch")
        else:
            if RunState(self.uow.run_state(old.run_id)) is not RunState.RUNNING:
                raise ValueError("plan revision requires a running Run")
            if active_epoch is None:
                raise ValueError(f"run {old.run_id} has no active TournamentEpoch")
            current_epoch = active_epoch
        validate_match_contract(
            current_epoch,
            plan_version=old.version,
            rules_hash=old.evaluation_rules_hash,
            prompt_hash=old.ranking_prompt_hash,
            judge_hash=old.judge_profile_hash,
            rating_policy=old.rating_policy_version,
            admission_policy=old.admission_policy_version,
        )
        next_epoch: TournamentEpoch | None = None
        events = [
            NewEvent(
                event_type="ResearchPlanAccepted",
                payload={"version": new.version, "action": action},
            ),
            NewEvent(
                event_type="TournamentEpochClosed",
                payload={"epoch_id": current_epoch.epoch_id, "plan_version": old.version},
            ),
        ]
        if action == "new_epoch":
            if not next_epoch_id:
                raise ValueError("next_epoch_id is required for an in-run plan revision")
            if not already_accepted and any(
                epoch.epoch_id == next_epoch_id for epoch in epoch_history
            ):
                raise ValueError("new epoch ID was previously used by this Run")
            next_epoch = TournamentEpoch(
                epoch_id=next_epoch_id,
                research_plan_version=new.version,
                evaluation_rules_hash=new.evaluation_rules_hash,
                ranking_prompt_hash=new.ranking_prompt_hash,
                judge_profile_hash=new.judge_profile_hash,
                rating_policy_version=new.rating_policy_version,
                admission_policy_version=new.admission_policy_version,
                anchor_set_id=next_anchor_set_id,
            )
            events.append(
                NewEvent(
                    event_type="TournamentEpochOpened",
                    payload=next_epoch.model_dump(mode="json"),
                )
            )
        else:
            events.append(
                NewEvent(
                    event_type="RunForkRequired",
                    payload={"source_run_id": old.run_id, "plan_version": new.version},
                )
            )
        commit = self.uow.commit_domain_batch(
            run_id=old.run_id,
            expected_sequence=expected_sequence,
            events=events,
            idempotency_key=f"research-plan:{old.run_id}:{new.version}",
        )
        return PlanRevisionOutcome(action=action, commit=commit, next_epoch=next_epoch)

    def admit_hypothesis(
        self,
        *,
        run_id: str,
        hypothesis_id: str,
        expected_sequence: int,
        idempotency_key: str,
    ) -> AdmissionOutcome:
        """Reduce durable evidence and atomically assign an epoch-local entry."""

        prior = self.uow.load_command_commit(run_id, idempotency_key)
        if prior is not None:
            return self._replay_admission(
                prior,
                run_id=run_id,
                hypothesis_id=hypothesis_id,
            )
        if RunState(self.uow.run_state(run_id)) is not RunState.RUNNING:
            raise ValueError("admission requires a running Run")
        events = self.uow.load(run_id)
        loaded_sequence = events[-1].sequence if events else 0
        if loaded_sequence != expected_sequence:
            raise ConcurrencyConflict(f"expected {expected_sequence}, got {loaded_sequence}")
        epoch, _ = self._epoch_state_from_events(events)
        if epoch is None:
            return AdmissionOutcome(
                decision=AdmissionDecision(
                    admitted=False,
                    missing_requirements=("active_epoch",),
                )
            )
        admission_policy = admission_policy_from_manifest(
            self.uow.run_manifest(run_id),
            version=epoch.admission_policy_version,
        )
        snapshot = reduce_admission_evidence(
            run_id=run_id,
            hypothesis_id=hypothesis_id,
            events=events,
            policy=admission_policy,
        )
        decision = AdmissionDecision(
            admitted=not snapshot.missing_requirements and not snapshot.conflicting_evidence,
            missing_requirements=snapshot.missing_requirements,
            conflicting_evidence=snapshot.conflicting_evidence,
        )
        if not decision.admitted:
            return AdmissionOutcome(decision=decision)

        if snapshot.content_hash is None or snapshot.rating_policy_version is None:
            raise AssertionError("admitted evidence snapshot is incomplete")
        rating_policy = get_rating_policy(snapshot.rating_policy_version)
        entry = admit_entry(
            epoch,
            hypothesis_id,
            snapshot.content_hash,
            initial_rating=rating_policy.initial_rating,
        )
        entry_payload = entry.model_dump(mode="json")
        commit = self.uow.commit_domain_batch(
            run_id=run_id,
            expected_sequence=expected_sequence,
            events=(
                NewEvent(
                    event_type="HypothesisTournamentReady",
                    schema_version=2,
                    payload=snapshot.model_dump(mode="json"),
                ),
                NewEvent(event_type="TournamentEntryCreated", payload=entry_payload),
                NewEvent(
                    event_type="InitialRatingAssigned",
                    payload={
                        "epoch_id": epoch.epoch_id,
                        "hypothesis_id": hypothesis_id,
                        "rating": entry.rating,
                        "rating_policy_version": rating_policy.version,
                    },
                ),
            ),
            idempotency_key=idempotency_key,
        )
        return AdmissionOutcome(decision=decision, entry=entry, commit=commit)

    @staticmethod
    def _finalization_task(
        run_id: str, *, checkpoint_id: str, reason: str
    ) -> NewTask:
        return NewTask(
            task_id=f"finalize:{run_id}",
            run_id=run_id,
            idempotency_key=f"finalize:{run_id}",
            intent_type="finalize_run",
            payload={
                "reason": reason,
                "checkpoint_id": checkpoint_id,
                "budget_estimate": BudgetEstimate().model_dump(mode="json"),
            },
        )

    def _ensure_finalization(
        self,
        *,
        checkpoint: ConvergenceCheckpoint,
        expected_sequence: int,
        decision: StopDecision,
        signal_event: NewEvent | None = None,
    ) -> CommitResult:
        run_id = checkpoint.run_id
        if decision.action != "stop":
            raise ValueError("finalization requires a durable stop decision")
        events = self.uow.load(run_id)
        reason = decision.reason or "work_complete"
        finalization_task = self._finalization_task(
            run_id, checkpoint_id=checkpoint.checkpoint_id, reason=reason
        )
        suffix = tuple(
            event
            for event in events
            if event.sequence > checkpoint.source_sequence + 1
        )
        control_types = {
            "StopSignalObserved",
            "StopPolicyTriggered",
            "RunStopping",
            "FinalizationRequested",
            "TaskEnqueued",
        }
        first_progress = next(
            (index for index, event in enumerate(suffix) if event.event_type not in control_types),
            len(suffix),
        )
        if any(event.event_type in control_types for event in suffix[first_progress:]):
            raise ValueError("finalization stop prefix order is invalid")
        persisted_control = suffix[:first_progress]
        if suffix[first_progress:] and len(persisted_control) < 4:
            raise ValueError("finalization progress precedes a complete stop prefix")

        persisted_signal = (
            persisted_control[0]
            if persisted_control
            and persisted_control[0].event_type == "StopSignalObserved"
            else None
        )
        expected_signal: NewEvent | None
        if persisted_signal is not None:
            action = persisted_signal.payload.get("action")
            if action != "soft_stop":
                raise ValueError("finalization stop signal is not a checkpoint-bound soft stop")
            expected_signal = NewEvent(
                event_type="StopSignalObserved",
                payload={"action": "soft_stop", "checkpoint_id": checkpoint.checkpoint_id},
            )
        else:
            expected_signal = signal_event

        expected_control: list[NewEvent] = []
        if expected_signal is not None:
            expected_control.append(expected_signal)
        expected_control.extend(
            (
                NewEvent(
                    event_type="StopPolicyTriggered",
                    payload={
                        "checkpoint_id": checkpoint.checkpoint_id,
                        "checkpoint_source_sequence": checkpoint.source_sequence,
                        "reason": reason,
                    },
                ),
                NewEvent(
                    event_type="RunStopping",
                    payload={"reason": reason, "checkpoint_id": checkpoint.checkpoint_id},
                ),
                NewEvent(
                    event_type="FinalizationRequested",
                    payload={
                        "task_id": finalization_task.task_id,
                        "checkpoint_id": checkpoint.checkpoint_id,
                    },
                ),
                self._task_enqueued_event(finalization_task, correlation_id=run_id),
            )
        )
        if len(persisted_control) > len(expected_control):
            raise ValueError("finalization stop prefix has extra control events")
        for actual, expected in zip(persisted_control, expected_control, strict=False):
            if (
                actual.event_type != expected.event_type
                or actual.schema_version != expected.schema_version
                or dict(actual.payload) != dict(expected.payload)
            ):
                raise ValueError("finalization stop prefix checkpoint, payload, or order mismatch")
        if suffix[first_progress:] and len(persisted_control) != len(expected_control):
            raise ValueError("finalization progress follows an incomplete stop prefix")

        task_event_present = any(
            event.event_type == "TaskEnqueued" for event in persisted_control
        )
        try:
            persisted_task = self.uow.task_definition(finalization_task.task_id)
            task_exists = True
        except KeyError:
            persisted_task = None
            task_exists = False
        if task_exists != task_event_present:
            raise ValueError("finalization task row and ordered enqueue event disagree")
        if persisted_task is not None and persisted_task != finalization_task:
            raise ValueError("finalization task payload is not checkpoint-bound")

        prior = self.uow.load_command_commit(
            run_id, f"ensure-finalization:{checkpoint.checkpoint_id}"
        )
        state = RunState(self.uow.run_state(run_id))
        if state in {RunState.COMPLETED, RunState.COMPLETED_PARTIAL}:
            if prior is None:
                raise ValueError("terminal Run has no checkpoint-bound finalization request")
            return prior
        if state not in {RunState.RUNNING, RunState.STOPPING}:
            raise ValueError(f"run state {state.value} does not allow finalization")

        new_events = expected_control[len(persisted_control) :]
        followup_tasks: tuple[NewTask, ...] = ()
        if any(event.event_type == "TaskEnqueued" for event in new_events):
            followup_tasks = (finalization_task,)
        if not new_events:
            if prior is not None:
                return prior
            return CommitResult(events=(), last_sequence=expected_sequence)
        target_state = (
            RunState.STOPPING
            if any(event.event_type == "RunStopping" for event in new_events)
            else None
        )
        return self.uow.commit_domain_batch(
            run_id=run_id,
            expected_sequence=expected_sequence,
            events=tuple(new_events),
            target_run_state=target_state,
            followup_tasks=followup_tasks,
            idempotency_key=f"ensure-finalization:{checkpoint.checkpoint_id}",
        )

    def ensure_finalization(
        self, *, run_id: str, expected_sequence: int, checkpoint_id: str
    ) -> CommitResult:
        """Resume any durable prefix of a stop request without duplicating work."""

        checkpoint = ConvergenceCheckpointBuilder(self.uow).load_recorded(
            run_id=run_id,
            checkpoint_id=checkpoint_id,
            expected_sequence=expected_sequence,
        )
        signal = next(
            (
                event
                for event in self.uow.load(run_id)
                if event.sequence > checkpoint.source_sequence + 1
                and event.event_type == "StopSignalObserved"
            ),
            None,
        )
        action = signal.payload.get("action") if signal is not None else None
        scientist_action = action if action in {"soft_stop", "hard_cancel"} else None
        decision = evaluate_stop(checkpoint, scientist_action=scientist_action)
        return self._ensure_finalization(
            checkpoint=checkpoint,
            expected_sequence=expected_sequence,
            decision=decision,
        )

    def complete_finalization(
        self,
        *,
        run_id: str,
        expected_sequence: int,
        lease_fence: TaskLeaseFence,
    ) -> CommitResult:
        """Complete through the finalization task lease using durable unresolved work."""

        if lease_fence.run_id != run_id or lease_fence.task_id != f"finalize:{run_id}":
            raise ValueError("finalization lease fence does not match Run")
        key = f"finalization:{run_id}:{lease_fence.attempt}"
        prior = self.uow.load_command_commit(run_id, key)
        state = RunState(self.uow.run_state(run_id))
        if state in {RunState.COMPLETED, RunState.COMPLETED_PARTIAL}:
            self.uow.assert_finalization_replay_fence(fence=lease_fence)
            if prior is None:
                raise ValueError("terminal Run has no matching finalization commit")
            return prior
        self.uow.assert_finalization_fence(fence=lease_fence)
        unresolved = self.uow.unresolved_task_ids(run_id, exclude_intent="finalize_run")
        completeness: Literal["complete", "partial"] = "partial" if unresolved else "complete"
        terminal = "RunCompleted" if completeness == "complete" else "RunCompletedPartial"
        target = RunState.COMPLETED if completeness == "complete" else RunState.COMPLETED_PARTIAL
        return self.uow.commit_lifecycle_batch(
            run_id=run_id,
            expected_sequence=expected_sequence,
            events=(
                NewEvent(
                    event_type="FinalizationCompleted",
                    payload={
                        "completeness": completeness,
                        "unresolved_task_ids": unresolved,
                    },
                ),
                NewEvent(
                    event_type=terminal,
                    payload={
                        "completeness": completeness,
                        "unresolved_task_ids": unresolved,
                    },
                ),
            ),
            target_run_state=target,
            task_mutations=(TaskMutation.succeed(lease_fence.task_id),),
            idempotency_key=key,
            lease_fence=lease_fence,
            release_reservation_id=self.uow.reservation_id_for_task(lease_fence.task_id),
        )

    def create_and_start_run(
        self,
        run_id: str,
        *,
        manifest: dict[str, Any],
        start_payload: dict[str, Any],
    ) -> CommitResult:
        """Atomically create and start a Run under Supervisor authority."""

        return self.uow.create_started_run(
            run_id,
            manifest=manifest,
            event=NewEvent(event_type="RunStarted", payload=start_payload),
            idempotency_key=f"start:{run_id}:0",
        )

    @staticmethod
    def _worker_task(
        *,
        run_id: str,
        task_id: str,
        intent_type: str,
        skill_id: str,
        inputs: dict[str, Any],
        provider_id: str,
        model_or_tool: str,
        matches: int = 0,
        hypotheses: int = 0,
    ) -> NewTask:
        contract = resolve_core_skill_contract(
            skill_id=skill_id,
            skill_version="0.2.0",
            output_schema_id=load_skill(Path("skills") / skill_id).output_schema,
        )
        system_prompt = (Path("skills") / skill_id / contract.prompt_path).read_text(
            encoding="utf-8"
        )
        payload = WorkerTaskPayload(
            skill_id=contract.id,
            skill_version=contract.version,
            output_schema_id=contract.output_schema,
            output_schema_version=1,
            research_plan_version=1,
            provider_id=provider_id,
            model_or_tool=model_or_tool,
            inputs=inputs,
            input_snapshot_hash=request_fingerprint(inputs),
            prompt_hash=prompt_hash(system_prompt),
            budget_estimate=BudgetEstimate(
                model_calls=1,
                hypotheses=hypotheses,
                matches=matches,
            ),
        )
        return NewTask(
            task_id=task_id,
            run_id=run_id,
            idempotency_key=task_id,
            intent_type=intent_type,
            payload=payload.model_dump(mode="json"),
        )

    def bootstrap_run(self, *, run_id: str, manifest: dict[str, Any]) -> CommitResult:
        """Atomically start a Run, freeze epoch 1, and enqueue Generation."""

        goal = manifest.get("goal")
        contract = manifest.get("tournament_contract")
        provider = manifest.get("provider_configuration")
        if not isinstance(goal, Mapping) or not isinstance(contract, Mapping):
            raise TypeError("run manifest lacks goal or tournament contract")
        if not isinstance(provider, Mapping):
            raise TypeError("run manifest lacks provider configuration")
        provider_id = str(provider.get("provider", ""))
        model = str(provider.get("model", ""))
        if not provider_id or not model:
            raise ValueError("run manifest lacks provider identity")
        epoch = TournamentEpoch.model_validate(contract)
        initial = self._worker_task(
            run_id=run_id,
            task_id=f"generation:{run_id}:1",
            intent_type="run_generation",
            skill_id="generation",
            inputs={
                "goal_title": goal.get("title"),
                "research_goal": goal.get("goal"),
                "required_causal_chain": goal.get("required_causal_chain"),
                "required_outputs": goal.get("required_outputs"),
            },
            provider_id=provider_id,
            model_or_tool=model,
            hypotheses=2,
        )
        return self.uow.create_started_run(
            run_id,
            manifest=manifest,
            event=NewEvent(
                event_type="RunStarted",
                payload={
                    "profile_id": manifest.get("profile_id"),
                    "goal_title": goal.get("title"),
                    "provider": provider_id,
                },
            ),
            additional_events=(
                NewEvent(
                    event_type="TournamentEpochOpened",
                    payload=epoch.model_dump(mode="json"),
                ),
                self._task_enqueued_event(initial, correlation_id=run_id),
            ),
            initial_tasks=(initial,),
            idempotency_key=f"bootstrap:{run_id}:0",
        )

    @staticmethod
    def _manifest_provider(manifest: Mapping[str, Any]) -> tuple[str, str]:
        configured = manifest.get("provider_configuration")
        if not isinstance(configured, Mapping):
            raise TypeError("run manifest lacks provider configuration")
        provider_id = configured.get("provider")
        model = configured.get("model")
        if not isinstance(provider_id, str) or not isinstance(model, str):
            raise TypeError("run manifest provider configuration is malformed")
        return provider_id, model

    def _schedule_tasks(
        self,
        *,
        run_id: str,
        expected_sequence: int,
        tasks: Sequence[NewTask],
        phase: str,
    ) -> CommitResult:
        return self.uow.commit_domain_batch(
            run_id=run_id,
            expected_sequence=expected_sequence,
            events=tuple(
                self._task_enqueued_event(task, correlation_id=run_id) for task in tasks
            ),
            followup_tasks=tasks,
            idempotency_key=f"schedule:{run_id}:{phase}",
        )

    def advance(self, *, run_id: str, expected_sequence: int) -> AdvanceOutcome:
        """Advance the fixed Core Preview workflow from durable scientific evidence."""

        state = RunState(self.uow.run_state(run_id))
        if state in {
            RunState.COMPLETED,
            RunState.COMPLETED_PARTIAL,
            RunState.FAILED,
            RunState.CANCELLED,
        }:
            return AdvanceOutcome(action="terminal")
        if state is not RunState.RUNNING:
            return AdvanceOutcome(action="waiting")
        if self.uow.unresolved_task_ids(run_id):
            return AdvanceOutcome(action="waiting")
        events = self.uow.load(run_id)
        if not events or events[-1].sequence != expected_sequence:
            raise ConcurrencyConflict(f"expected {expected_sequence}, got durable stream tip")
        manifest = self.uow.run_manifest(run_id)
        provider_id, model = self._manifest_provider(manifest)
        hypotheses = {
            str(event.payload["hypothesis_id"]): str(event.payload["content_hash"])
            for event in events
            if event.event_type == "HypothesisContentCreated"
        }
        if len(hypotheses) < 2:
            return AdvanceOutcome(action="waiting")
        required_stages = {
            stage.value for stage in {ReviewStage.INITIAL, *self.review_policy.required_before_admission}
        }
        reviewed = {
            (str(event.payload.get("hypothesis_id")), str(event.payload.get("stage")))
            for event in events
            if event.event_type == "ReviewCompleted"
        }
        if any((hypothesis_id, stage) not in reviewed for hypothesis_id in hypotheses for stage in required_stages):
            return AdvanceOutcome(action="waiting")

        proximity_events = [event for event in events if event.event_type == "ProximityAssessed"]
        if len(proximity_events) < 2:
            ordered = sorted(hypotheses)
            pairs = ((ordered[0], ordered[1]), (ordered[1], ordered[0]))
            tasks = tuple(
                self._worker_task(
                    run_id=run_id,
                    task_id=f"proximity:{index}:{left}:{right}",
                    intent_type="run_proximity",
                    skill_id="proximity",
                    inputs={
                        "edge_id": f"edge-{index}",
                        "left_id": left,
                        "left_content_hash": hypotheses[left],
                        "right_id": right,
                        "right_content_hash": hypotheses[right],
                    },
                    provider_id=provider_id,
                    model_or_tool=model,
                )
                for index, (left, right) in enumerate(pairs, start=1)
            )
            commit = self._schedule_tasks(
                run_id=run_id,
                expected_sequence=expected_sequence,
                tasks=tasks,
                phase="proximity",
            )
            return AdvanceOutcome(action="scheduled", commit=commit)

        entry_ids = {
            str(event.payload.get("hypothesis_id"))
            for event in events
            if event.event_type == "TournamentEntryCreated"
        }
        for hypothesis_id in sorted(hypotheses):
            if hypothesis_id not in entry_ids:
                admission = self.admit_hypothesis(
                    run_id=run_id,
                    hypothesis_id=hypothesis_id,
                    expected_sequence=expected_sequence,
                    idempotency_key=f"admit:epoch-1:{hypothesis_id}",
                )
                if admission.commit is None:
                    raise ValueError(
                        f"hypothesis {hypothesis_id} is not admissible: "
                        f"{admission.decision.missing_requirements}"
                    )
                return AdvanceOutcome(action="admitted", commit=admission.commit)

        anchor_sets = manifest.get("anchor_sets")
        if not isinstance(anchor_sets, list) or len(anchor_sets) != 1:
            raise ValueError("run manifest has no unique frozen anchor set")
        members = anchor_sets[0].get("members")
        if not isinstance(members, list) or not members:
            raise ValueError("run manifest has no frozen anchor members")
        missing_anchors = [
            member for member in members if str(member.get("anchor_id")) not in entry_ids
        ]
        if missing_anchors:
            epoch = self._active_epoch(run_id)
            policy = get_rating_policy(epoch.rating_policy_version)
            anchor_events: list[NewEvent] = []
            for member in missing_anchors:
                anchor_id = str(member["anchor_id"])
                anchor_events.extend(
                    (
                        NewEvent(
                            event_type="HypothesisTournamentReady",
                            schema_version=2,
                            payload={
                                "run_id": run_id,
                                "hypothesis_id": anchor_id,
                                "content_id": anchor_id,
                                "content_hash": member["content_hash"],
                                "research_plan_version": epoch.research_plan_version,
                                "admission_policy_version": epoch.admission_policy_version,
                                "required_review_stages": [],
                                "safety_status": "passed",
                                "novelty_assessment_id": None,
                                "duplicate_detected": False,
                                "epoch_id": epoch.epoch_id,
                                "rating_policy_version": policy.version,
                                "missing_requirements": [],
                                "conflicting_evidence": [],
                                "source_event_sequences": [],
                                "review_ids": [],
                                "proximity_edge_ids": [],
                                "content_event_sequence": None,
                                "novelty_event_sequence": None,
                                "proximity_event_sequences": [],
                                "epoch_event_sequence": None,
                            },
                        ),
                        NewEvent(
                            event_type="TournamentEntryCreated",
                            payload={
                                "epoch_id": epoch.epoch_id,
                                "hypothesis_id": anchor_id,
                                "content_hash": member["content_hash"],
                                "rating": policy.initial_rating,
                                "matches_played": 0,
                            },
                        ),
                        NewEvent(
                            event_type="InitialRatingAssigned",
                            payload={
                                "epoch_id": epoch.epoch_id,
                                "hypothesis_id": anchor_id,
                                "rating": policy.initial_rating,
                                "rating_policy_version": policy.version,
                            },
                        ),
                    )
                )
            commit = self.uow.commit_domain_batch(
                run_id=run_id,
                expected_sequence=expected_sequence,
                events=tuple(anchor_events),
                idempotency_key=f"anchors:{run_id}:{epoch.epoch_id}",
            )
            return AdvanceOutcome(action="admitted", commit=commit)

        matches = {
            str(event.payload.get("match_id"))
            for event in events
            if event.event_type == "MatchEvaluated"
        }
        profile = manifest.get("profile")
        stop = profile.get("stop") if isinstance(profile, Mapping) else None
        if not isinstance(stop, Mapping):
            raise TypeError("run manifest has no frozen stop policy")
        minimum_matches = stop.get("minimum_matches")
        top_k_window = stop.get("top_k_stability_window")
        if (
            not isinstance(minimum_matches, int)
            or isinstance(minimum_matches, bool)
            or minimum_matches < 0
            or not isinstance(top_k_window, int)
            or isinstance(top_k_window, bool)
            or top_k_window < 1
        ):
            raise ValueError("run manifest stop policy is malformed")
        opportunistic_matches = max(
            minimum_matches - len(members),
            top_k_window - len(members),
            0,
        )
        expected_match_ids = {
            *(f"opportunistic-match-{index}" for index in range(1, opportunistic_matches + 1)),
            *(f"anchor-match-{index}" for index in range(1, len(members) + 1)),
        }
        if not expected_match_ids.issubset(matches):
            epoch = self._active_epoch(run_id)
            ranking_tasks: list[NewTask] = []
            ordered_hypotheses = sorted(hypotheses)
            for index in range(1, opportunistic_matches + 1):
                match_id = f"opportunistic-match-{index}"
                if match_id in matches:
                    continue
                left_id, right_id = ordered_hypotheses[:2]
                ranking_tasks.append(
                    self._worker_task(
                        run_id=run_id,
                        task_id=f"ranking:01-opportunistic:{index}",
                        intent_type="run_ranking",
                        skill_id="ranking",
                        inputs={
                            "match_id": match_id,
                            "epoch_id": epoch.epoch_id,
                            "left_id": left_id,
                            "left_content_hash": hypotheses[left_id],
                            "right_id": right_id,
                            "right_content_hash": hypotheses[right_id],
                            "research_plan_version": epoch.research_plan_version,
                            "evaluation_rules_hash": epoch.evaluation_rules_hash,
                            "ranking_prompt_hash": epoch.ranking_prompt_hash,
                            "judge_profile_hash": epoch.judge_profile_hash,
                            "rating_policy_version": epoch.rating_policy_version,
                            "admission_policy_version": epoch.admission_policy_version,
                            "anchor_set_id": epoch.anchor_set_id,
                            "comparison_kind": "opportunistic",
                        },
                        provider_id=provider_id,
                        model_or_tool=model,
                        matches=1,
                    )
                )
            for index, (hypothesis_id, member) in enumerate(
                zip(ordered_hypotheses, members, strict=True), start=1
            ):
                match_id = f"anchor-match-{index}"
                if match_id in matches:
                    continue
                ranking_tasks.append(
                    self._worker_task(
                        run_id=run_id,
                        task_id=f"ranking:02-anchor:{index}",
                        intent_type="run_ranking",
                        skill_id="ranking",
                        inputs={
                            "match_id": match_id,
                            "epoch_id": epoch.epoch_id,
                            "left_id": hypothesis_id,
                            "left_content_hash": hypotheses[hypothesis_id],
                            "right_id": member["anchor_id"],
                            "right_content_hash": member["content_hash"],
                            "research_plan_version": epoch.research_plan_version,
                            "evaluation_rules_hash": epoch.evaluation_rules_hash,
                            "ranking_prompt_hash": epoch.ranking_prompt_hash,
                            "judge_profile_hash": epoch.judge_profile_hash,
                            "rating_policy_version": epoch.rating_policy_version,
                            "admission_policy_version": epoch.admission_policy_version,
                            "anchor_set_id": epoch.anchor_set_id,
                            "comparison_kind": "fixed_anchor",
                        },
                        provider_id=provider_id,
                        model_or_tool=model,
                        matches=1,
                    )
                )
            commit = self._schedule_tasks(
                run_id=run_id,
                expected_sequence=expected_sequence,
                tasks=tuple(ranking_tasks),
                phase="ranking",
            )
            return AdvanceOutcome(action="scheduled", commit=commit)

        recorded = ConvergenceCheckpointBuilder(self.uow).build_and_record(
            run_id=run_id,
            expected_sequence=expected_sequence,
        )
        stopped = self.tick(
            run_id=run_id,
            expected_sequence=recorded.commit.last_sequence,
            checkpoint_id=recorded.checkpoint_id,
        )
        if stopped.commit is None:
            return AdvanceOutcome(action="checkpointed", commit=recorded.commit)
        return AdvanceOutcome(action="checkpointed", commit=stopped.commit)

    def start_run(self, run_id: str, *, expected_sequence: int) -> CommitResult:
        """Start an existing created Run using strict lifecycle concurrency."""

        return self.uow.commit_lifecycle_batch(
            run_id=run_id,
            expected_sequence=expected_sequence,
            events=(NewEvent(event_type="RunStarted", payload={}),),
            target_run_state=RunState.RUNNING,
            idempotency_key=f"start:{run_id}:{expected_sequence}",
        )

    def pause_run(self, run_id: str, *, expected_sequence: int) -> CommitResult:
        """Durably traverse running through pausing to paused."""

        pausing = self.uow.commit_lifecycle_batch(
            run_id=run_id,
            expected_sequence=expected_sequence,
            events=(NewEvent(event_type="RunPausing", payload={}),),
            target_run_state=RunState.PAUSING,
            idempotency_key=f"pause-request:{run_id}:{expected_sequence}",
        )
        return self.uow.commit_lifecycle_batch(
            run_id=run_id,
            expected_sequence=pausing.last_sequence,
            events=(NewEvent(event_type="RunPaused", payload={}),),
            target_run_state=RunState.PAUSED,
            idempotency_key=f"pause-complete:{run_id}:{pausing.last_sequence}",
        )

    def resume_run(self, run_id: str, *, expected_sequence: int) -> CommitResult:
        """Resume a paused Run using strict lifecycle concurrency."""

        return self.uow.commit_lifecycle_batch(
            run_id=run_id,
            expected_sequence=expected_sequence,
            events=(NewEvent(event_type="RunResumed", payload={}),),
            target_run_state=RunState.RUNNING,
            idempotency_key=f"resume:{run_id}:{expected_sequence}",
        )

    def cancel_run(
        self,
        run_id: str,
        *,
        expected_sequence: int,
        reason: str = "scientist_cancel",
    ) -> CommitResult:
        """Cancel a Run using strict lifecycle concurrency."""

        return self.uow.commit_lifecycle_batch(
            run_id=run_id,
            expected_sequence=expected_sequence,
            events=(NewEvent(event_type="RunCancelled", payload={"reason": reason}),),
            target_run_state=RunState.CANCELLED,
            idempotency_key=f"cancel:{run_id}:{expected_sequence}",
        )

    def stop_and_finalize_partial(
        self,
        run_id: str,
        *,
        expected_sequence: int,
        reason: str = "scientist_stop",
    ) -> CommitResult:
        """Reject the removed unfenced synchronous finalization entry point."""

        del run_id, expected_sequence, reason
        raise ValueError(
            "synchronous finalization was removed; use checkpoint-bound tick and a worker lease"
        )

    def tick(
        self,
        *,
        run_id: str,
        expected_sequence: int,
        checkpoint_id: str,
        scientist_action: Literal["soft_stop", "hard_cancel"] | None = None,
    ) -> TickOutcome:
        """Evaluate only a recomputed, durable convergence checkpoint."""

        checkpoint = ConvergenceCheckpointBuilder(self.uow).load_recorded(
            run_id=run_id,
            checkpoint_id=checkpoint_id,
            expected_sequence=expected_sequence,
        )
        run_state = RunState(self.uow.run_state(run_id))
        decision = evaluate_stop(checkpoint, scientist_action=scientist_action)
        if decision.action == "cancel":
            commit = self.uow.commit_lifecycle_batch(
                run_id=run_id,
                expected_sequence=expected_sequence,
                events=(
                    NewEvent(
                        event_type="StopSignalObserved",
                        payload={
                            "action": "hard_cancel",
                            "checkpoint_id": checkpoint_id,
                        },
                    ),
                    NewEvent(
                        event_type="RunCancelled",
                        payload={"reason": decision.reason or "scientist_cancel"},
                    ),
                ),
                target_run_state=RunState.CANCELLED,
                idempotency_key=f"cancel:{run_id}:{checkpoint_id}",
            )
            return TickOutcome(decision=decision, commit=commit)
        if decision.action == "continue" and run_state is not RunState.RUNNING:
            raise ValueError("non-terminal tick requires a running Run")
        if decision.action == "continue":
            return TickOutcome(decision=decision)
        signal_event = (
            NewEvent(
                event_type="StopSignalObserved",
                payload={"action": scientist_action, "checkpoint_id": checkpoint_id},
            )
            if scientist_action is not None
            else None
        )
        commit = self._ensure_finalization(
            checkpoint=checkpoint,
            expected_sequence=expected_sequence,
            decision=decision,
            signal_event=signal_event,
        )
        return TickOutcome(decision=decision, commit=commit)
