"""Fixed structural counterexamples; no science is inferred or implemented here."""

import json
from dataclasses import FrozenInstanceError, asdict, replace
from pathlib import Path

import pytest

from co_scientist_next.admission import (
    AdmissionDecision,
    AdmissionRecord,
    EligibilityPurpose,
    EligibilityRecord,
    EligibilityStatus,
    check_comparison_refs,
    check_eligibility,
)
from co_scientist_next.delta import (
    ChangeKind,
    ClaimChange,
    ClaimRef,
    DeltaProposal,
    ResolvedDelta,
    check_resolution,
)

FIXTURES = json.loads(
    (Path(__file__).resolve().parents[2] / "examples/w0-t2-contracts.json").read_text()
)


def admission(
    candidate="A", decision=AdmissionDecision.ADMITTED, reason="Synthetic review complete"
):
    return AdmissionRecord(
        admission_ref=f"admission-{candidate}",
        run_ref="run-1",
        hypothesis_ref=f"H-{candidate}",
        goal_ref="goal-1",
        policy_ref="policy-1",
        decision=decision,
        reasons=(reason,),
        ethics_ref=f"ethics-{candidate}",
        inventory_ref=f"inventory-{candidate}",
        dossier_ref=f"dossier-{candidate}",
        final_reflection_ref=f"R2-{candidate}",
        epoch_ref="epoch-1" if decision == AdmissionDecision.ADMITTED else None,
    )


@pytest.mark.parametrize("case", FIXTURES["admission_cases"], ids=lambda c: c["candidate"])
def test_admission_and_qualifications_are_separate_records(case):
    assert FIXTURES["synthetic"] is True
    record = admission(case["candidate"], AdmissionDecision(case["decision"]), case["reason"])
    qualifications = []
    for purpose in EligibilityPurpose:
        status = EligibilityStatus(case[purpose.value])
        q = EligibilityRecord(
            record.admission_ref,
            purpose,
            status,
            f"M10-fixture-{purpose}" if status != EligibilityStatus.NOT_ASSESSED else None,
        )
        check_eligibility(record, q)
        qualifications.append(q)
    assert qualifications[0].purpose != qualifications[1].purpose
    # No helper assigns qualification from admission or a strong revision suggestion.
    assert [q.status for q in qualifications] == [case["parent"], case["final"]]


@pytest.mark.parametrize("decision", [AdmissionDecision.BLOCKED, AdmissionDecision.INCOMPLETE])
@pytest.mark.parametrize("purpose", list(EligibilityPurpose))
def test_nonadmitted_eligible_counterexample_rejected(decision, purpose):
    record = admission(decision=decision)
    eligible = EligibilityRecord(
        record.admission_ref, purpose, EligibilityStatus.ELIGIBLE, "fixture-basis"
    )
    with pytest.raises(ValueError, match="requires an admitted"):
        check_eligibility(record, eligible)


def test_qualification_basis_and_reference_mismatch():
    record = admission()
    with pytest.raises(ValueError, match="nonempty"):
        EligibilityRecord(
            record.admission_ref, EligibilityPurpose.PARENT, EligibilityStatus.ELIGIBLE
        )
    wrong = EligibilityRecord("other-admission", EligibilityPurpose.FINAL)
    with pytest.raises(ValueError, match="different Admission"):
        check_eligibility(record, wrong)


def test_admitted_refs_are_fixed_and_require_all_review_refs():
    record = admission()
    assert asdict(record)["final_reflection_ref"] == "R2-A"
    with pytest.raises(FrozenInstanceError):
        record.dossier_ref = "quietly-replaced-dossier"
    for field in (
        "ethics_ref",
        "inventory_ref",
        "dossier_ref",
        "final_reflection_ref",
        "epoch_ref",
    ):
        with pytest.raises(ValueError, match="nonempty"):
            replace(record, **{field: None})
    with pytest.raises(ValueError, match="Only admitted"):
        replace(record, decision=AdmissionDecision.BLOCKED)
    with pytest.raises(ValueError, match="Immutable decision reasons"):
        replace(record, reasons=["mutable reason"])


@pytest.mark.parametrize("field", ["run_ref", "epoch_ref", "goal_ref", "policy_ref"])
def test_comparison_refs_reject_mixed_run_epoch_or_policy(field):
    left, right = admission("A"), admission("B")
    check_comparison_refs(left, right)
    with pytest.raises(ValueError, match=field):
        check_comparison_refs(left, replace(right, **{field: "other"}))


def test_fixed_epoch_refs_allow_child_but_not_self_or_blocked_comparison():
    # Only reference compatibility is tested: there is no Epoch registry or Match.
    left, child = admission("A"), admission("child-generation-1")
    check_comparison_refs(left, child)
    assert left.epoch_ref == child.epoch_ref == "epoch-1"
    assert left.dossier_ref == "dossier-A"
    with pytest.raises(ValueError, match="distinct"):
        check_comparison_refs(left, left)
    with pytest.raises(ValueError, match="distinct"):
        check_comparison_refs(left, replace(child, admission_ref=left.admission_ref))
    with pytest.raises(ValueError, match="must be admitted"):
        check_comparison_refs(left, admission("blocked", AdmissionDecision.BLOCKED))


def test_context_change_intent_precedes_inventory_based_resolution():
    fixture = FIXTURES["context_change"]
    proposal = DeltaProposal(
        "proposal-1",
        fixture["child_hypothesis"],
        (fixture["parent_hypothesis"],),
        "mutation",
        fixture["intent"],
    )
    # Proposal intentionally has no Inventory, resolved claims or reuse decision.
    assert fixture["parent_context"] != fixture["child_context"]
    parent = ClaimRef(
        fixture["parent_hypothesis"], fixture["parent_inventory"], fixture["parent_claim"]
    )
    resolved = ResolvedDelta(
        proposal.proposal_ref,
        fixture["child_hypothesis"],
        fixture["child_inventory"],
        (
            ClaimChange(ChangeKind.MODIFIED, (parent,), (fixture["modified_child_claim"],)),
            ClaimChange(ChangeKind.NEW, (), (fixture["new_child_claim"],)),
        ),
    )
    check_resolution(proposal, resolved)
    assert resolved.changes[0].kind == ChangeKind.MODIFIED
    with pytest.raises(ValueError, match="nonempty"):
        replace(resolved, child_inventory_ref="")
    with pytest.raises(ValueError, match="new hypothesis"):
        replace(proposal, child_hypothesis_ref=fixture["parent_hypothesis"])


def test_two_parent_combined_mapping_preserves_parent_inventory_provenance():
    proposal = DeltaProposal(
        "proposal-2", "H-child", ("H-p1", "H-p2"), "crossover", "Synthetic merge intent"
    )
    parents = (ClaimRef("H-p1", "I-p1", "same-local-id"), ClaimRef("H-p2", "I-p2", "same-local-id"))
    change = ClaimChange(ChangeKind.COMBINED, parents, ("child-bridge",))
    resolved = ResolvedDelta(proposal.proposal_ref, "H-child", "I-child", (change,))
    check_resolution(proposal, resolved)
    assert parents[0] != parents[1]  # Local Claim spelling alone does not identify a source.
    with pytest.raises(ValueError, match="outside the Proposal"):
        check_resolution(replace(proposal, parent_hypothesis_refs=("H-p1",)), resolved)
    with pytest.raises(ValueError, match="Proposal/child"):
        check_resolution(replace(proposal, proposal_ref="another"), resolved)


def test_unreliable_delta_has_explicit_full_check_fallback():
    proposal = DeltaProposal(
        "proposal-3", "H-child", ("H-parent",), "mutation", "Uncertain mapping fixture"
    )
    unresolved = ResolvedDelta(
        proposal.proposal_ref,
        "H-child",
        "I-child",
        unresolved_reason=FIXTURES["unresolved_mapping_reason"],
    )
    check_resolution(proposal, unresolved)
    assert unresolved.changes == ()
    assert "full evidence checking" in unresolved.unresolved_reason
    fake_retained = ClaimChange(
        ChangeKind.RETAINED, (ClaimRef("H-parent", "I-parent", "p"),), ("c",)
    )
    with pytest.raises(ValueError, match="must not claim resolved"):
        replace(unresolved, changes=(fake_retained,))


@pytest.mark.parametrize(
    ("kind", "parent_count", "children"),
    [
        (ChangeKind.RETAINED, 1, ("c",)),
        (ChangeKind.MODIFIED, 1, ("c",)),
        (ChangeKind.REMOVED, 1, ()),
        (ChangeKind.SPLIT, 1, ("c1", "c2")),
        (ChangeKind.COMBINED, 2, ("c",)),
        (ChangeKind.NEW, 0, ("c",)),
    ],
)
def test_relation_shapes(kind, parent_count, children):
    parents = tuple(ClaimRef("H-parent", "I-parent", f"p-{i}") for i in range(parent_count))
    assert ClaimChange(kind, parents, children).kind == kind
    with pytest.raises(ValueError, match="cardinality"):
        ClaimChange(kind, parents, ("invalid-child",) if kind == ChangeKind.REMOVED else ())


def test_resolution_rejects_mixed_parent_inventory_snapshots():
    proposal = DeltaProposal("p", "H-child", ("H-parent",), "mutation", "Fixture")
    resolved = ResolvedDelta(
        "p",
        "H-child",
        "I-child",
        (
            ClaimChange(ChangeKind.MODIFIED, (ClaimRef("H-parent", "I-v1", "p1"),), ("c1",)),
            ClaimChange(ChangeKind.MODIFIED, (ClaimRef("H-parent", "I-v2", "p2"),), ("c2",)),
        ),
    )
    with pytest.raises(ValueError, match="one fixed Inventory"):
        check_resolution(proposal, resolved)
