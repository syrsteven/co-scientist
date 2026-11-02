"""M11 intent → M03 Inventory-based mapping. M04/M05 decide evidence reuse."""

from dataclasses import dataclass
from enum import StrEnum

from ._validation import require_refs, unique_tuple


@dataclass(frozen=True)
class DeltaProposal:
    """M11 declares intent at child creation, before the real child Inventory."""

    proposal_ref: str
    child_hypothesis_ref: str
    parent_hypothesis_refs: tuple[str, ...]
    operator: str
    intent: str

    def __post_init__(self):
        require_refs(self.proposal_ref, self.child_hypothesis_ref, self.operator, self.intent)
        unique_tuple(self.parent_hypothesis_refs, "parents", nonempty=True)
        require_refs(*self.parent_hypothesis_refs)
        if self.child_hypothesis_ref in self.parent_hypothesis_refs:
            raise ValueError("Child must have a new hypothesis reference")


@dataclass(frozen=True)
class ClaimRef:
    """A Claim is local to an immutable hypothesis and Inventory, not global."""

    hypothesis_ref: str
    inventory_ref: str
    claim_id: str

    def __post_init__(self):
        require_refs(self.hypothesis_ref, self.inventory_ref, self.claim_id)


class ChangeKind(StrEnum):
    RETAINED = "retained"
    MODIFIED = "modified"
    REMOVED = "removed"
    SPLIT = "split"
    COMBINED = "combined"
    NEW = "new"


@dataclass(frozen=True)
class ClaimChange:
    kind: ChangeKind
    parents: tuple[ClaimRef, ...]
    child_claim_ids: tuple[str, ...]

    def __post_init__(self):
        if not isinstance(self.kind, ChangeKind):
            raise TypeError("Explicit ChangeKind required")
        unique_tuple(self.parents, "parent claims")
        unique_tuple(self.child_claim_ids, "child claims")
        if any(not isinstance(ref, ClaimRef) for ref in self.parents):
            raise ValueError("Parent claims require their Inventory provenance")
        require_refs(*self.child_claim_ids)
        p, c = len(self.parents), len(self.child_claim_ids)
        valid = {
            ChangeKind.RETAINED: p == 1 and c == 1,
            ChangeKind.MODIFIED: p == 1 and c == 1,
            ChangeKind.REMOVED: p == 1 and c == 0,
            ChangeKind.SPLIT: p == 1 and c >= 2,
            ChangeKind.COMBINED: p >= 2 and c == 1,
            ChangeKind.NEW: p == 0 and c == 1,
        }
        if not valid[self.kind]:
            raise ValueError("Claim relation cardinality does not match its kind")


@dataclass(frozen=True)
class ResolvedDelta:
    """M03 output after Inventory; an unresolved mapping explicitly falls back.

    No material/appraisal reuse permission, R2 conclusion or rating is carried.
    Partial/unreliable resolution is represented conservatively as unresolved;
    downstream M04/M05 must arrange full checking rather than assume inheritance.
    """

    proposal_ref: str
    child_hypothesis_ref: str
    child_inventory_ref: str
    changes: tuple[ClaimChange, ...] = ()
    unresolved_reason: str | None = None

    def __post_init__(self):
        require_refs(self.proposal_ref, self.child_hypothesis_ref, self.child_inventory_ref)
        unique_tuple(self.changes, "changes")
        if any(not isinstance(change, ClaimChange) for change in self.changes):
            raise ValueError("Resolved changes must be ClaimChange records")
        if self.unresolved_reason is not None:
            require_refs(self.unresolved_reason)
            if self.changes:
                raise ValueError("Unreliable mapping must not claim resolved relations")
        elif not self.changes:
            raise ValueError("Resolved relations or an explicit unresolved reason required")
        children = tuple(child for change in self.changes for child in change.child_claim_ids)
        unique_tuple(children, "resolved child claims")


def check_resolution(proposal: DeltaProposal, resolved: ResolvedDelta) -> None:
    """Reference consistency only; M03 must verify the actual Inventory contents."""
    if (
        resolved.proposal_ref != proposal.proposal_ref
        or resolved.child_hypothesis_ref != proposal.child_hypothesis_ref
    ):
        raise ValueError("Resolution does not match its Proposal/child")
    inventories = {}
    for change in resolved.changes:
        for parent in change.parents:
            if parent.hypothesis_ref not in proposal.parent_hypothesis_refs:
                raise ValueError("Resolved parent is outside the Proposal")
            existing = inventories.setdefault(parent.hypothesis_ref, parent.inventory_ref)
            if existing != parent.inventory_ref:
                raise ValueError("A parent must reference one fixed Inventory snapshot")
