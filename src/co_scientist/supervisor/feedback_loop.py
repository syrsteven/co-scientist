"""Bounded task planning owned by Supervisor, not by scientific agents."""

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from co_scientist.agents.result import AgentResult
from co_scientist.domain.research_feedback import ResearchFeedback, latest_research_feedback
from co_scientist.domain.research_protocol import protocol_hash
from co_scientist.domain.review import ReviewStage
from co_scientist.domain.task import NewTask
from co_scientist.events.models import DomainEvent, NewEvent
from co_scientist.events.reducers import replay_tournament
from co_scientist.ports.external_provider import thaw_json

if TYPE_CHECKING:
    from co_scientist.supervisor.orchestrator import Supervisor


def feedback_event(result: AgentResult, inputs: Mapping[str, Any]) -> NewEvent:
    feedback = ResearchFeedback(
        feedback_id=f"{result.run_id}:feedback:{inputs['meta_review_round']}",
        feedback_version=inputs["meta_review_round"],
        source_task_id=result.task_id, source_result_id=result.result_id,
        research_plan_version=result.research_plan_version, epoch_id=inputs["epoch_id"],
        source_content_hashes=result.payload["source_content_hashes"],
        source_match_ids=tuple(inputs["source_match_ids"]),
        system_feedback=tuple(result.payload["system_feedback"]),
        overview=result.payload["overview"], coverage_gaps=tuple(result.payload["coverage_gaps"]),
        safety_direction_check=result.payload["safety_direction_check"],
    ).model_dump(mode="json")
    return NewEvent(event_type="ResearchFeedbackRecorded", schema_version=1,
                    payload={**feedback, "feedback_hash": protocol_hash(feedback)},
                    causation_id=result.result_id, correlation_id=result.run_id)


def next_feedback_task(
    supervisor: "Supervisor", *, run_id: str, manifest: Mapping[str, Any],
    events: Sequence[DomainEvent], hypotheses: Mapping[str, str], eligible: set[str],
) -> NewTask | None:
    """Called at an idle, non-converged checkpoint. No writes and no provider calls."""
    profile, budget = manifest["profile"], manifest["budget"]
    policy, evolution = profile["meta_review"], profile["evolution"]
    snapshot = supervisor.uow.load_budget_snapshot(run_id)
    if snapshot.hard_limit_reached:
        return None
    remaining_calls = budget["max_model_calls"] - snapshot.total_usage.model_calls
    remaining_matches = budget["max_matches"] - snapshot.total_usage.matches
    epoch = supervisor._active_epoch(run_id)
    feedback = latest_research_feedback(manifest, events)
    tasks = [e.payload for e in events if e.event_type == "TaskEnqueued"]
    evolution_tasks = [t for t in tasks if t.get("intent_type") == "run_evolution"]
    consumed = {t.get("payload", {}).get("inputs", {}).get("research_feedback", {}).get("feedback_id")
                for t in evolution_tasks}
    contents = {str(e.payload["hypothesis_id"]): e.payload for e in events
                if e.event_type == "HypothesisContentCreated"}
    provider_id, model = supervisor._manifest_provider(manifest)
    if (feedback and feedback["safety_direction_check"] == "clear"
            and (feedback["system_feedback"] or feedback["coverage_gaps"])
            and feedback["feedback_id"] not in consumed
            and len(evolution_tasks) < evolution["max_rounds"] and remaining_matches > 0):
        required_reviews = len({ReviewStage.INITIAL, *supervisor.review_policy.required_before_admission})
        # Conservative planning headroom, not a replacement for Worker reservations.
        count = min(policy["max_children_per_round"], evolution["max_children_per_round"],
                    (remaining_calls - 2) // (required_reviews + 5))
        if budget.get("max_hypotheses") is not None:
            headroom = 0 if budget.get("hypothesis_limit_policy") == "capacity-v2" else 1
            count = min(count, budget["max_hypotheses"] - len(hypotheses) - headroom)
        ratings = replay_tournament(list(events)).ratings.get(epoch.epoch_id, {})
        # Feedback cannot authorize parents that fail current admission/safety evidence.
        parents = sorted(set(feedback["source_content_hashes"]) & eligible,
                         key=lambda key: (-ratings.get(key, 1200), key))[:2]
        if count > 0 and parents:
            inputs: dict[str, Any] = {
                "research_plan_version": epoch.research_plan_version,
                "evolution_round": len(evolution_tasks) + 1, "max_children": count,
                "source_content_ids": [contents[key]["content_id"] for key in parents],
                "existing_hypothesis_ids": sorted(contents),
                "existing_content_ids": sorted(str(c["content_id"]) for c in contents.values()),
                "review_feedback": [
                    {"event_type": e.event_type, "sequence": e.sequence, "assessment": thaw_json(e.payload)}
                    for e in events if e.event_type in {"ReviewCompleted", "NoveltyAssessmentRecorded"}
                    and e.payload.get("hypothesis_id") in parents
                ],
                "task_goal": manifest["feedback_contract"]["evolution_instruction"],
            }
            if profile["literature_novelty_required"]:
                inputs["literature_evidence"] = supervisor._persisted_review_evidence(run_id)
            return supervisor._worker_task(
                run_id=run_id, task_id=f"{run_id}:feedback-evolution:{feedback['feedback_version']}",
                intent_type="run_evolution", skill_id="evolution", inputs=inputs,
                provider_id=provider_id, model_or_tool=model, hypotheses=count,
            )
    meta_tasks = [t for t in tasks if t.get("intent_type") == "run_meta_review"
                  and t.get("payload", {}).get("inputs", {}).get("meta_review_round")]
    if len(meta_tasks) >= policy["max_rounds"] or remaining_calls <= 1:
        return None
    matches = [e for e in events if e.event_type == "MatchEvaluated"
               and e.payload.get("epoch_id") == epoch.epoch_id]
    seen = set(feedback["source_match_ids"]) if feedback else set()
    if sum(e.payload["match_id"] not in seen for e in matches) < policy["match_interval"]:
        return None
    round_number = len(meta_tasks) + 1
    return supervisor._worker_task(
        run_id=run_id, task_id=f"{run_id}:meta-review:{round_number}",
        intent_type="run_meta_review", skill_id="meta_review",
        inputs={
            "research_plan_version": epoch.research_plan_version, "epoch_id": epoch.epoch_id,
            "meta_review_round": round_number, "source_content_hashes": dict(hypotheses),
            "source_match_ids": [e.payload["match_id"] for e in matches],
            "matches": [thaw_json(e.payload) for e in matches],
            "task_goal": manifest["feedback_contract"]["meta_review_instruction"],
        }, provider_id=provider_id, model_or_tool=model,
    )


def exploration_pair(
    candidates: Sequence[str], anchors: Sequence[str], events: Sequence[DomainEvent], *, epoch_id: str,
) -> tuple[str, str, str]:
    """Favor least-compared candidates, then underused pairs; deterministic slot rotation."""
    def pair_key(left: str, right: str) -> tuple[str, str]:
        return (left, right) if left <= right else (right, left)

    pair_counts: Counter[tuple[str, str]] = Counter()
    counts: Counter[str] = Counter()
    for event in events:
        if event.event_type == "MatchEvaluated" and event.payload.get("epoch_id") == epoch_id:
            left, right = str(event.payload["left_id"]), str(event.payload["right_id"])
            pair_counts[pair_key(left, right)] += 1
            counts.update((left, right))
    pairs = [(left, right, "opportunistic") for index, left in enumerate(candidates)
             for right in candidates[index + 1:]]
    pairs += [(left, right, "fixed_anchor") for left in candidates for right in anchors]
    chosen = min(pairs, key=lambda pair: (
        min(counts[pair[0]], counts[pair[1]]) if pair[2] == "opportunistic" else counts[pair[0]],
        pair_counts[pair_key(pair[0], pair[1])],
        pairs.index(pair),
    ))
    return (chosen[1], chosen[0], chosen[2]) if pair_counts[pair_key(chosen[0], chosen[1])] % 2 else chosen
