"""Deterministic Supervisor orchestration contracts."""

from co_scientist.supervisor.followups import FollowupIntent, derive_followup_intents
from co_scientist.supervisor.orchestrator import (
    AdmissionDecision,
    AdmissionOutcome,
    PlanRevisionOutcome,
    Supervisor,
    TickOutcome,
    plan_revision_action,
)

__all__ = [
    "AdmissionDecision",
    "AdmissionOutcome",
    "FollowupIntent",
    "PlanRevisionOutcome",
    "Supervisor",
    "TickOutcome",
    "derive_followup_intents",
    "plan_revision_action",
]
