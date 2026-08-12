"""Deterministic application-level orchestration owned by the Supervisor."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from co_scientist.adapters.persistence.sqlite import CommitResult, SqliteUnitOfWork
from co_scientist.agents.payloads import (
    EvolutionResultV1,
    GenerationResultV1,
    RankingResultV1,
    validate_output_payload,
)
from co_scientist.agents.result import AgentExecutionContext, AgentResult
from co_scientist.domain.budget import BudgetLedger, CostEntry
from co_scientist.domain.convergence import ConvergenceSnapshot, StopDecision, evaluate_stop
from co_scientist.domain.hypothesis import (
    compute_hypothesis_content_hash,
    hypothesis_content_from_draft,
)
from co_scientist.domain.research_plan import ResearchPlan
from co_scientist.domain.review import (
    NoveltyAssessment,
    NoveltyVerdict,
    ReviewPolicy,
    ReviewStage,
)
from co_scientist.domain.states import ExternalCallState, RunState, TaskState
from co_scientist.domain.task import NewTask, TaskMutation
from co_scientist.domain.tournament import (
    EpochContractMismatch,
    MatchDecision,
    MatchResult,
    TournamentEntry,
    TournamentEpoch,
    admit_entry,
    apply_match,
    get_rating_policy,
    validate_match_contract,
)
from co_scientist.events.models import NewEvent
from co_scientist.events.reducers import replay_tournament
from co_scientist.supervisor.followups import FollowupIntent, derive_followup_intents


class AdmissionDecision(BaseModel):
    """Explain whether a candidate satisfies all independent admission gates."""

    model_config = ConfigDict(frozen=True)

    admitted: bool
    missing_requirements: tuple[str, ...] = ()


class AdmissionOutcome(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    decision: AdmissionDecision
    entry: TournamentEntry | None = None
    commit: CommitResult | None = None


def evaluate_admission(
    *,
    hypothesis_id: str | None = None,
    content_hash: str | None = None,
    research_plan_version: int | None = None,
    safety_passed: bool,
    required_stages: AbstractSet[str | ReviewStage],
    completed_stages: AbstractSet[str | ReviewStage],
    novelty_required: bool,
    novelty_assessment: NoveltyAssessment | None,
    proximity_complete: bool,
    duplicate: bool,
) -> AdmissionDecision:
    """Evaluate review, novelty, and candidate-proximity gates independently."""

    required = {ReviewStage(stage).value for stage in required_stages}
    required.add(ReviewStage.INITIAL.value)
    completed = {ReviewStage(stage).value for stage in completed_stages}

    missing: list[str] = []
    if not safety_passed:
        missing.append("safety")
    missing.extend(sorted(required - completed))
    if novelty_required:
        novelty_qualifies = (
            novelty_assessment is not None
            and hypothesis_id is not None
            and content_hash is not None
            and research_plan_version is not None
            and novelty_assessment.hypothesis_id == hypothesis_id
            and novelty_assessment.content_hash == content_hash
            and novelty_assessment.research_plan_version == research_plan_version
            and novelty_assessment.verdict
            in {NoveltyVerdict.NOVEL, NoveltyVerdict.PARTIALLY_NOVEL}
        )
        if not novelty_qualifies:
            missing.append("novelty_assessment")
    if not proximity_complete:
        missing.append("proximity")
    if duplicate:
        missing.append("candidate_duplicate")
    return AdmissionDecision(admitted=not missing, missing_requirements=tuple(missing))


def plan_revision_action(
    old: ResearchPlan,
    new: ResearchPlan,
) -> Literal["new_epoch", "fork_run"]:
    """Classify an accepted plan revision without carrying ratings across epochs."""

    if old.run_id != new.run_id:
        raise ValueError("ResearchPlan revision must belong to the same run")
    if new.version <= old.version:
        raise ValueError("ResearchPlan version must increase")
    return (
        "fork_run"
        if old.scientific_scope_hash != new.scientific_scope_hash
        else "new_epoch"
    )


class PlanRevisionOutcome(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    action: Literal["new_epoch", "fork_run"]
    commit: CommitResult
    next_epoch: TournamentEpoch | None = None


class TickOutcome(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    decision: StopDecision
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
        active: TournamentEpoch | None = None
        history: list[TournamentEpoch] = []
        for event in self.uow.load(run_id):
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
            task_state is TaskState.RESULT_RECEIVED
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
                            "generation_strategy": draft.generation_strategy,
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
                        "generation_strategy": draft.generation_strategy,
                        "change_rationale": evolution.change_rationales[draft.hypothesis_id],
                        **common,
                    },
                    causation_id=result.result_id,
                    correlation_id=result.run_id,
                )
                for draft in evolution.children
                for content in (hypothesis_content_from_draft(draft),)
            )

        event_types = {
            "reflection": "ReviewCompleted",
            "ranking": "MatchEvaluated",
            "proximity": "ProximityAssessed",
            "meta_review": "MetaReviewCompleted",
        }
        try:
            event_type = event_types[result.skill_id]
        except KeyError as error:
            raise ValueError(f"unsupported skill result: {result.skill_id}") from error
        event_payload = {**dict(payload), **common}
        if (
            event_type == "ReviewCompleted"
            and payload.get("stage") == ReviewStage.INITIAL.value
        ):
            safety_status = payload.get("safety_status")
            event_payload["safety_passed"] = safety_status == "passed"
        elif event_type == "MatchEvaluated":
            ranking = RankingResultV1.model_validate(payload)
            event_payload["decision"] = ranking.decision_status.value
            event_payload["winner_id"] = (
                ranking.left_id
                if ranking.winner_slot == 1
                else ranking.right_id
                if ranking.winner_slot == 2
                else None
            )
        return (
            NewEvent(
                event_type=event_type,
                payload=event_payload,
                causation_id=result.result_id,
                correlation_id=result.run_id,
            ),
        )

    def _followup_tasks(
        self,
        *,
        run_id: str,
        events: Sequence[NewEvent],
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
        return tuple(
            NewTask(
                task_id=task_id,
                run_id=run_id,
                idempotency_key=task_id,
                intent_type=intent.intent_type,
                payload={
                    "hypothesis_id": intent.target_id,
                    "review_stage": intent.intent_type.removeprefix("run_"),
                },
            )
            for task_id, intent in approved.items()
        )

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
            expected_payload = {
                **dict(result.payload),
                "decision": match.decision.value,
                "winner_id": match.winner_id,
                "source_result_id": result.result_id,
                "source_task_id": result.task_id,
                "status": result.status,
            }
            if (
                len(persisted_matches) != 1
                or persisted_matches[0].payload != expected_payload
                or persisted_matches[0].causation_id != result.result_id
                or persisted_matches[0].correlation_id != run_id
            ):
                raise ValueError(f"conflicting duplicate match_id: {match.match_id}")
            if match.decision is not MatchDecision.DECISIVE:
                if persisted_ratings:
                    raise ValueError(f"non-decisive duplicate match has ratings: {match.match_id}")
                return ()
            if len(persisted_ratings) != 2:
                raise ValueError(f"decisive duplicate match has incomplete ratings: {match.match_id}")
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
                    raise ValueError(f"duplicate match rating provenance mismatch: {match.match_id}")
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
            raise ValueError(f"match {match.match_id} references an unrated TournamentEntry") from error
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
    ) -> CommitResult:
        """Validate and atomically apply a durably submitted worker result."""

        call = self.uow.get_external_call(result.external_call_id)
        if call.execution_context is None or call.agent_result is None:
            raise ValueError("external call has no durable typed result context")
        persisted_context = AgentExecutionContext.model_validate(call.execution_context)
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
        result = durable_result
        if result.status == "completed":
            rating_events = self._rating_events_for_result(run_id, result)
            events = (*self._events_for_result(result), *rating_events)
            followups = self._followup_tasks(run_id=run_id, events=events)
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
            task_target = (
                TaskState.PENDING if result.status == "partial" else TaskState.FAILED
            )
        return self.uow.commit_domain_batch(
            run_id=run_id,
            expected_sequence=expected_sequence,
            events=events,
            task_mutations=(TaskMutation(task_id=task_id, target_state=task_target),),
            followup_tasks=followups,
            idempotency_key=result.idempotency_key,
            external_call_id=result.external_call_id,
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
        expected_sequence: int,
        hypothesis_id: str,
        content_hash: str,
        safety_passed: bool,
        required_stages: AbstractSet[str | ReviewStage],
        completed_stages: AbstractSet[str | ReviewStage],
        novelty_required: bool,
        novelty_assessment: NoveltyAssessment | None,
        proximity_complete: bool,
        duplicate: bool,
    ) -> AdmissionOutcome:
        """Admit a candidate and assign its epoch-local initial rating atomically."""

        if RunState(self.uow.run_state(run_id)) is not RunState.RUNNING:
            raise ValueError("admission requires a running Run")
        epoch = self._active_epoch(run_id)
        decision = evaluate_admission(
            hypothesis_id=hypothesis_id,
            content_hash=content_hash,
            research_plan_version=epoch.research_plan_version,
            safety_passed=safety_passed,
            required_stages=required_stages,
            completed_stages=completed_stages,
            novelty_required=novelty_required,
            novelty_assessment=novelty_assessment,
            proximity_complete=proximity_complete,
            duplicate=duplicate,
        )
        if not decision.admitted:
            return AdmissionOutcome(decision=decision)

        entry = admit_entry(epoch, hypothesis_id, content_hash)
        entry_payload = entry.model_dump(mode="json")
        commit = self.uow.commit_domain_batch(
            run_id=run_id,
            expected_sequence=expected_sequence,
            events=(
                NewEvent(
                    event_type="HypothesisTournamentReady",
                    payload={
                        "hypothesis_id": hypothesis_id,
                        "content_hash": content_hash,
                        "epoch_id": epoch.epoch_id,
                    },
                ),
                NewEvent(event_type="TournamentEntryCreated", payload=entry_payload),
                NewEvent(
                    event_type="InitialRatingAssigned",
                    payload={
                        "epoch_id": epoch.epoch_id,
                        "hypothesis_id": hypothesis_id,
                        "rating": entry.rating,
                    },
                ),
            ),
            idempotency_key=f"admit:{epoch.epoch_id}:{hypothesis_id}:{content_hash}",
        )
        return AdmissionOutcome(decision=decision, entry=entry, commit=commit)

    def request_normal_completion(
        self,
        run_id: str,
        *,
        expected_sequence: int,
        reason: str = "work_complete",
    ) -> CommitResult:
        """Enter stopping and durably enqueue the required finalization task."""

        finalization_task = NewTask(
            task_id=f"finalize:{run_id}",
            run_id=run_id,
            idempotency_key=f"finalize:{run_id}",
            intent_type="finalize_run",
            payload={"reason": reason},
        )
        return self.uow.commit_lifecycle_batch(
            run_id=run_id,
            expected_sequence=expected_sequence,
            events=(
                NewEvent(event_type="RunStopping", payload={"reason": reason}),
                NewEvent(
                    event_type="FinalizationRequested",
                    payload={"task_id": finalization_task.task_id},
                ),
                self._task_enqueued_event(finalization_task, correlation_id=run_id),
            ),
            target_run_state=RunState.STOPPING,
            followup_tasks=(finalization_task,),
            idempotency_key=f"stop:{run_id}:{expected_sequence}",
        )

    def apply_finalization(
        self,
        run_id: str,
        *,
        expected_sequence: int,
        completeness: Literal["complete", "partial"],
    ) -> CommitResult:
        """Record finalization before the corresponding normal terminal event."""

        terminal = "RunCompleted" if completeness == "complete" else "RunCompletedPartial"
        return self.uow.commit_lifecycle_batch(
            run_id=run_id,
            expected_sequence=expected_sequence,
            events=(
                NewEvent(
                    event_type="FinalizationCompleted",
                    payload={"completeness": completeness},
                ),
                NewEvent(event_type=terminal, payload={"completeness": completeness}),
            ),
            target_run_state=(
                RunState.COMPLETED
                if completeness == "complete"
                else RunState.COMPLETED_PARTIAL
            ),
            task_mutations=(TaskMutation.succeed(f"finalize:{run_id}"),),
            idempotency_key=f"finalization:{run_id}:{expected_sequence}",
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
        """Synchronously finish the Core Preview's durable partial-finalization path."""

        stopping = self.request_normal_completion(
            run_id,
            expected_sequence=expected_sequence,
            reason=reason,
        )
        finalization_task_id = f"finalize:{run_id}"
        self.uow.transition_task(finalization_task_id, TaskState.LEASED)
        self.uow.transition_task(finalization_task_id, TaskState.RUNNING)
        self.uow.transition_task(finalization_task_id, TaskState.RESULT_RECEIVED)
        return self.apply_finalization(
            run_id,
            expected_sequence=stopping.last_sequence,
            completeness="partial",
        )

    def tick(
        self,
        *,
        run_id: str,
        expected_sequence: int,
        convergence: ConvergenceSnapshot,
        hard_budget_reached: bool | None = None,
        budget: BudgetLedger | None = None,
        scientist_action: Literal["soft_stop", "hard_cancel"] | None = None,
    ) -> TickOutcome:
        """Evaluate stopping policy, enforcing the epoch's frozen anchor contract."""

        if budget is not None and hard_budget_reached is not None:
            raise ValueError("provide budget or hard_budget_reached, not both")
        budget_reached = (
            budget.hard_limit_reached if budget is not None else bool(hard_budget_reached)
        )
        run_state = RunState(self.uow.run_state(run_id))
        decision = evaluate_stop(
            convergence,
            hard_budget_reached=budget_reached,
            scientist_action=scientist_action,
        )
        if decision.action == "cancel":
            commit = self.cancel_run(
                run_id,
                expected_sequence=expected_sequence,
                reason=decision.reason or "scientist_cancel",
            )
            return TickOutcome(decision=decision, commit=commit)
        if decision.action == "stop" and decision.reason != "quality_converged":
            commit = self.request_normal_completion(
                run_id,
                expected_sequence=expected_sequence,
                reason=decision.reason or "work_complete",
            )
            return TickOutcome(decision=decision, commit=commit)
        if decision.action == "continue" and run_state is not RunState.RUNNING:
            raise ValueError("non-terminal tick requires a running Run")

        epoch = self._active_epoch(run_id)
        if convergence.epoch_id != epoch.epoch_id:
            raise EpochContractMismatch(
                "convergence snapshot does not match the active TournamentEpoch"
            )
        if (
            decision.reason == "quality_converged"
            and convergence.anchor_set_id != epoch.anchor_set_id
        ):
            raise EpochContractMismatch(
                "convergence snapshot anchor set must match the active TournamentEpoch"
            )
        if decision.action == "continue":
            return TickOutcome(decision=decision)
        commit = self.request_normal_completion(
            run_id,
            expected_sequence=expected_sequence,
            reason=decision.reason or "work_complete",
        )
        return TickOutcome(decision=decision, commit=commit)
