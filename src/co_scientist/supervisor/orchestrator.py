"""Deterministic application-level orchestration owned by the Supervisor."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from co_scientist.adapters.persistence.sqlite import CommitResult, SqliteUnitOfWork
from co_scientist.agents.result import AgentResult
from co_scientist.domain.budget import BudgetLedger, CostEntry
from co_scientist.domain.convergence import ConvergenceSnapshot, StopDecision, evaluate_stop
from co_scientist.domain.research_plan import ResearchPlan
from co_scientist.domain.review import NoveltyAssessment, ReviewPolicy, ReviewStage
from co_scientist.domain.states import ExternalCallState, RunState, TaskState
from co_scientist.domain.task import NewTask, TaskMutation
from co_scientist.domain.tournament import (
    EpochContractMismatch,
    TournamentEpoch,
    validate_match_contract,
)
from co_scientist.domain.transitions import transition_run
from co_scientist.events.models import NewEvent
from co_scientist.supervisor.followups import FollowupIntent, derive_followup_intents


class AdmissionDecision(BaseModel):
    """Explain whether a candidate satisfies all independent admission gates."""

    model_config = ConfigDict(frozen=True)

    admitted: bool
    missing_requirements: tuple[str, ...] = ()


def evaluate_admission(
    *,
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
    if novelty_required and novelty_assessment is None:
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


class Supervisor:
    """Sole authority for applying results, creating tasks, and ending runs."""

    def __init__(self, *, uow: SqliteUnitOfWork, review_policy: ReviewPolicy) -> None:
        self.uow = uow
        self.review_policy = review_policy

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
        if task_state not in {TaskState.RESULT_RECEIVED, TaskState.SUCCEEDED}:
            raise ValueError("task must be result_received before domain application")
        if result.status not in {"completed", "partial"}:
            raise ValueError("only completed or partial AgentResult can be applied")

    @staticmethod
    def _events_for_result(result: AgentResult) -> tuple[NewEvent, ...]:
        common = {
            "source_result_id": result.result_id,
            "source_task_id": result.task_id,
            "status": result.status,
        }
        payload = result.payload
        if result.skill_id == "generation":
            hypotheses = payload.get("hypotheses")
            if not isinstance(hypotheses, Sequence) or isinstance(hypotheses, str | bytes):
                raise ValueError("generation result requires hypotheses")
            events: list[NewEvent] = []
            for item in hypotheses:
                if not isinstance(item, Mapping):
                    raise TypeError("generation hypothesis must be an object")
                hypothesis_id = item.get("hypothesis_id")
                if not isinstance(hypothesis_id, str) or not hypothesis_id:
                    raise ValueError("generation hypothesis requires hypothesis_id")
                events.append(
                    NewEvent(
                        event_type="HypothesisContentCreated",
                        payload={**dict(item), **common, "hypothesis_id": hypothesis_id},
                        causation_id=result.result_id,
                        correlation_id=result.run_id,
                    )
                )
            if not events:
                raise ValueError("generation result must contain at least one hypothesis")
            return tuple(events)

        event_types = {
            "reflection": "ReviewCompleted",
            "ranking": "MatchEvaluated",
            "proximity": "ProximityAssessed",
            "evolution": "HypothesisContentCreated",
            "meta_review": "MetaReviewCompleted",
        }
        try:
            event_type = event_types[result.skill_id]
        except KeyError as error:
            raise ValueError(f"unsupported skill result: {result.skill_id}") from error
        event_payload = {**dict(payload), **common}
        if event_type == "HypothesisContentCreated":
            hypothesis_id = payload.get("hypothesis_id")
            if not isinstance(hypothesis_id, str) or not hypothesis_id:
                raise ValueError("evolution result requires hypothesis_id")
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

    def handle_result(
        self,
        run_id: str,
        task_id: str,
        result: AgentResult,
        expected_sequence: int,
    ) -> CommitResult:
        """Validate and atomically apply a durably submitted worker result."""

        call = self.uow.get_external_call(result.external_call_id)
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
        events = self._events_for_result(result)
        followups = self._followup_tasks(run_id=run_id, events=events)
        return self.uow.commit_domain_batch(
            run_id=run_id,
            expected_sequence=expected_sequence,
            events=events,
            task_mutations=(TaskMutation.succeed(task_id),),
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
        current_epoch: TournamentEpoch,
        expected_sequence: int,
        next_epoch_id: str | None = None,
        next_anchor_set_id: str | None = None,
    ) -> PlanRevisionOutcome:
        """Atomically accept a plan and close its epoch, opening or forking by policy."""

        validate_match_contract(
            current_epoch,
            plan_version=old.version,
            rules_hash=old.evaluation_rules_hash,
            prompt_hash=old.ranking_prompt_hash,
            judge_hash=old.judge_profile_hash,
            rating_policy=old.rating_policy_version,
            admission_policy=old.admission_policy_version,
        )
        action = plan_revision_action(old, new)
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

    def request_normal_completion(
        self,
        run_id: str,
        *,
        expected_sequence: int,
        reason: str = "work_complete",
        run_state: RunState = RunState.RUNNING,
    ) -> CommitResult:
        """Enter stopping and durably enqueue the required finalization task."""

        transition_run(run_state, RunState.STOPPING)
        finalization_task = NewTask(
            task_id=f"finalize:{run_id}",
            run_id=run_id,
            idempotency_key=f"finalize:{run_id}",
            intent_type="finalize_run",
            payload={"reason": reason},
        )
        return self.uow.commit_domain_batch(
            run_id=run_id,
            expected_sequence=expected_sequence,
            events=(
                NewEvent(event_type="RunStopping", payload={"reason": reason}),
                NewEvent(
                    event_type="FinalizationRequested",
                    payload={"task_id": finalization_task.task_id},
                ),
            ),
            followup_tasks=(finalization_task,),
            idempotency_key=f"stop:{run_id}",
        )

    def apply_finalization(
        self,
        run_id: str,
        *,
        expected_sequence: int,
        completeness: Literal["complete", "partial"],
    ) -> CommitResult:
        """Record finalization before the corresponding normal terminal event."""

        stream = self.uow.load(run_id)
        event_types = [event.event_type for event in stream]
        if "RunStopping" not in event_types:
            raise ValueError("run must enter stopping before finalization")
        terminal = "RunCompleted" if completeness == "complete" else "RunCompletedPartial"
        transition_run(
            RunState.STOPPING,
            RunState.COMPLETED if completeness == "complete" else RunState.COMPLETED_PARTIAL,
        )
        return self.uow.commit_domain_batch(
            run_id=run_id,
            expected_sequence=expected_sequence,
            events=(
                NewEvent(
                    event_type="FinalizationCompleted",
                    payload={"completeness": completeness},
                ),
                NewEvent(event_type=terminal, payload={"completeness": completeness}),
            ),
            task_mutations=(TaskMutation.succeed(f"finalize:{run_id}"),),
            idempotency_key=f"finalization:{run_id}",
        )

    def tick(
        self,
        *,
        run_id: str,
        expected_sequence: int,
        run_state: RunState,
        epoch: TournamentEpoch,
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
        decision = evaluate_stop(
            convergence,
            hard_budget_reached=budget_reached,
            scientist_action=scientist_action,
        )
        if decision.reason == "quality_converged" and (
            convergence.epoch_id != epoch.epoch_id
            or convergence.anchor_set_id != epoch.anchor_set_id
        ):
            raise EpochContractMismatch(
                "convergence snapshot epoch and anchor set must match TournamentEpoch"
            )
        if decision.action == "continue":
            return TickOutcome(decision=decision)
        if decision.action == "cancel":
            transition_run(run_state, RunState.CANCELLED)
            commit = self.uow.commit_domain_batch(
                run_id=run_id,
                expected_sequence=expected_sequence,
                events=(NewEvent(event_type="RunCancelled", payload={"reason": decision.reason}),),
                idempotency_key=f"cancel:{run_id}",
            )
            return TickOutcome(decision=decision, commit=commit)
        commit = self.request_normal_completion(
            run_id,
            expected_sequence=expected_sequence,
            reason=decision.reason or "work_complete",
            run_state=run_state,
        )
        return TickOutcome(decision=decision, commit=commit)
