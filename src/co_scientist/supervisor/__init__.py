"""Deterministic Supervisor orchestration contracts."""

from co_scientist.supervisor.followups import FollowupIntent, derive_followup_intents
from co_scientist.supervisor.orchestrator import (
    AdmissionDecision,
    PlanRevisionOutcome,
    Supervisor,
    TickOutcome,
    evaluate_admission,
    plan_revision_action,
)

__all__ = [
    "AdmissionDecision",
    "FollowupIntent",
    "PlanRevisionOutcome",
    "Supervisor",
    "TickOutcome",
    "derive_followup_intents",
    "evaluate_admission",
    "plan_revision_action",
]
