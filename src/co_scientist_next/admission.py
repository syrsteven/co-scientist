"""M09a references and M10 qualification records; no scientific decision maker."""

from dataclasses import dataclass
from enum import StrEnum

from ._validation import require_refs


class AdmissionDecision(StrEnum):
    ADMITTED = "admitted"
    BLOCKED = "blocked"
    INCOMPLETE = "incomplete"


class EligibilityPurpose(StrEnum):
    PARENT = "parent"
    FINAL = "final"


class EligibilityStatus(StrEnum):
    NOT_ASSESSED = "not_assessed"
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"


@dataclass(frozen=True)
class AdmissionRecord:
    """M09 output supplied by its owner, not inferred from the presence of refs.

    References name immutable snapshots. Structural validation cannot prove that
    they exist, are complete or justify the scientific decision.
    """

    admission_ref: str
    run_ref: str
    hypothesis_ref: str
    goal_ref: str
    policy_ref: str
    decision: AdmissionDecision
    reasons: tuple[str, ...]
    ethics_ref: str | None = None
    inventory_ref: str | None = None
    dossier_ref: str | None = None
    final_reflection_ref: str | None = None
    epoch_ref: str | None = None

    def __post_init__(self):
        require_refs(
            self.admission_ref, self.run_ref, self.hypothesis_ref, self.goal_ref, self.policy_ref
        )
        if not isinstance(self.decision, AdmissionDecision):
            raise TypeError("Explicit AdmissionDecision required")
        if not isinstance(self.reasons, tuple) or not self.reasons:
            raise ValueError("Immutable decision reasons required")
        require_refs(*self.reasons)
        refs = (self.ethics_ref, self.inventory_ref, self.dossier_ref, self.final_reflection_ref)
        require_refs(*(ref for ref in refs if ref is not None))
        if self.decision == AdmissionDecision.ADMITTED:
            require_refs(*refs, self.epoch_ref)
        elif self.epoch_ref is not None:
            raise ValueError("Only admitted candidates have an Epoch reference")


@dataclass(frozen=True)
class EligibilityRecord:
    """M10 independently owns parent/final eligibility and its assessment basis."""

    admission_ref: str
    purpose: EligibilityPurpose
    status: EligibilityStatus = EligibilityStatus.NOT_ASSESSED
    basis_ref: str | None = None

    def __post_init__(self):
        require_refs(self.admission_ref)
        if not isinstance(self.purpose, EligibilityPurpose) or not isinstance(
            self.status, EligibilityStatus
        ):
            raise TypeError("Explicit eligibility purpose/status required")
        if self.status != EligibilityStatus.NOT_ASSESSED:
            require_refs(self.basis_ref)
        elif self.basis_ref is not None:
            raise ValueError("An unassessed qualification has no assessment basis")


def check_eligibility(admission: AdmissionRecord, eligibility: EligibilityRecord) -> None:
    """Reject mismatched references or eligible-but-not-admitted combinations.

    This never grants eligibility or selects a parent/winner.
    """
    if eligibility.admission_ref != admission.admission_ref:
        raise ValueError("Eligibility references a different Admission")
    if (
        eligibility.status == EligibilityStatus.ELIGIBLE
        and admission.decision != AdmissionDecision.ADMITTED
    ):
        raise ValueError("Eligibility requires an admitted candidate")


def check_comparison_refs(left: AdmissionRecord, right: AdmissionRecord) -> None:
    """Only reference consistency; no Match, ranking or Epoch registration."""
    if any(a.decision != AdmissionDecision.ADMITTED for a in (left, right)):
        raise ValueError("Both comparison references must be admitted")
    if left.admission_ref == right.admission_ref or left.hypothesis_ref == right.hypothesis_ref:
        raise ValueError("Comparison requires distinct candidates")
    for field in ("run_ref", "epoch_ref", "goal_ref", "policy_ref"):
        if getattr(left, field) != getattr(right, field):
            raise ValueError(f"Comparison references differ in {field}")
