from typing import Literal

from pydantic import BaseModel, ConfigDict

from co_scientist.domain.budget import DurableBudgetSnapshot


class ConvergenceCheckpoint(BaseModel):
    """Frozen, source-bound evidence used by the Supervisor stopping policy."""

    model_config = ConfigDict(frozen=True)

    checkpoint_id: str
    run_id: str
    source_sequence: int
    policy_version: str
    epoch_id: str
    research_plan_version: int
    evaluation_rules_hash: str
    ranking_prompt_hash: str
    judge_profile_hash: str
    rating_policy_version: str
    admission_policy_version: str
    anchor_set_id: str
    anchor_member_ids: tuple[str, ...]
    anchor_member_content_hashes: tuple[str, ...]
    anchor_comparison_ids: tuple[str, ...]
    top_k: int
    top_k_stability_window: int
    top_k_ids: tuple[str, ...]
    top_k_window_sequences: tuple[int, ...]
    top_k_stable: bool
    cluster_ids: tuple[str, ...]
    cluster_membership_ids: tuple[str, ...]
    cluster_diversity_window: int
    cluster_window_sequences: tuple[int, ...]
    cluster_diversity_satisfied: bool
    novelty_window_sequences: tuple[int, ...]
    novelty_plateau: bool
    minimum_hypotheses: int
    hypothesis_count: int
    minimum_model_calls: int
    model_call_count: int
    minimum_matches: int
    match_count: int
    minimum_coverage: int
    coverage_count: int
    elo_plateau_window: int
    elo_window_sequences: tuple[int, ...]
    elo_plateau: bool
    budget_snapshot: DurableBudgetSnapshot
    unresolved_task_ids: tuple[str, ...]
    evidence_source_sequences: tuple[int, ...]

    @property
    def quality_converged(self) -> bool:
        return (
            bool(self.anchor_member_ids)
            and len(self.anchor_member_ids) == len(self.anchor_member_content_hashes)
            and len(self.anchor_comparison_ids) >= self.minimum_coverage
            and self.match_count >= self.minimum_matches
            and len(self.top_k_ids) == self.top_k
            and len(self.top_k_window_sequences) == self.top_k_stability_window
            and self.top_k_stable
            and len(self.cluster_membership_ids) == self.cluster_diversity_window
            and len(self.cluster_window_sequences) == self.cluster_diversity_window
            and self.cluster_diversity_satisfied
            and len(self.novelty_window_sequences) == self.cluster_diversity_window
            and self.novelty_plateau
            and self.hypothesis_count >= self.minimum_hypotheses
            and self.model_call_count >= self.minimum_model_calls
            and self.coverage_count >= self.minimum_coverage
        )


class StopDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    action: Literal["continue", "stop", "cancel"]
    reason: str | None
    auxiliary_signals: tuple[str, ...] = ()

    @property
    def should_stop(self) -> bool:
        return self.action == "stop"


def evaluate_stop(
    snapshot: ConvergenceCheckpoint,
    *,
    scientist_action: Literal["soft_stop", "hard_cancel"] | None,
) -> StopDecision:
    if scientist_action == "hard_cancel":
        return StopDecision(action="cancel", reason="scientist_cancel")
    if scientist_action == "soft_stop":
        return StopDecision(action="stop", reason="scientist_stop")
    if snapshot.budget_snapshot.hard_limit_reached:
        return StopDecision(action="stop", reason="hard_budget_reached")

    primary = snapshot.quality_converged
    return StopDecision(
        action="stop" if primary else "continue",
        reason="quality_converged" if primary else None,
        auxiliary_signals=("elo_plateau",) if snapshot.elo_plateau else (),
    )
