from typing import Literal

from pydantic import BaseModel, ConfigDict


class ConvergenceSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    epoch_id: str
    anchor_set_id: str | None = None
    elo_plateau: bool
    anchor_plateau: bool
    top_k_stable: bool
    cluster_diversity_plateau: bool
    minimum_budget_satisfied: bool


class StopDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    action: Literal["continue", "stop", "cancel"]
    reason: str | None
    auxiliary_signals: tuple[str, ...] = ()

    @property
    def should_stop(self) -> bool:
        return self.action == "stop"


def evaluate_stop(
    snapshot: ConvergenceSnapshot,
    *,
    hard_budget_reached: bool,
    scientist_action: Literal["soft_stop", "hard_cancel"] | None,
) -> StopDecision:
    if scientist_action == "hard_cancel":
        return StopDecision(action="cancel", reason="scientist_cancel")
    if scientist_action == "soft_stop":
        return StopDecision(action="stop", reason="scientist_stop")
    if hard_budget_reached:
        return StopDecision(action="stop", reason="hard_budget_reached")

    primary = (
        bool(snapshot.anchor_set_id)
        and snapshot.anchor_plateau
        and snapshot.top_k_stable
        and snapshot.cluster_diversity_plateau
        and snapshot.minimum_budget_satisfied
    )
    return StopDecision(
        action="stop" if primary else "continue",
        reason="quality_converged" if primary else None,
        auxiliary_signals=("elo_plateau",) if snapshot.elo_plateau else (),
    )
