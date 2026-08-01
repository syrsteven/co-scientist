"""Pure policy derivation for Supervisor-owned follow-up work."""

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from co_scientist.domain.review import ReviewPolicy, ReviewStage, required_review_stages


class FollowupIntent(BaseModel):
    """A policy-approved intent that only the Supervisor may turn into a task."""

    model_config = ConfigDict(frozen=True)

    intent_type: str
    target_id: str
    created_by: Literal["supervisor"] = "supervisor"


def derive_followup_intents(
    *,
    event_type: str,
    payload: Mapping[str, Any],
    review_policy: ReviewPolicy,
) -> tuple[FollowupIntent, ...]:
    """Derive follow-ups from committed domain state, never agent recommendations."""

    if event_type != "HypothesisContentCreated":
        return ()

    target_id = payload.get("hypothesis_id")
    if not isinstance(target_id, str) or not target_id:
        raise ValueError("HypothesisContentCreated requires hypothesis_id")

    required = required_review_stages(review_policy)
    ordered_stages = (ReviewStage.INITIAL, *review_policy.required_before_admission)
    return tuple(
        FollowupIntent(intent_type=f"run_{stage.value}", target_id=target_id)
        for stage in dict.fromkeys(ordered_stages)
        if stage in required
    )
