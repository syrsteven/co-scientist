"""Pure ClaimLineageV2 identities, freezing, and explicit graph resolution.

No source passage, claim text, or model-authored hash is a lineage authority.
The Supervisor will own persistence and state changes in a later slice.
"""

from __future__ import annotations

from collections import Counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from co_scientist.domain.claim_verification import Sha256, Text, scientific_hash
from co_scientist.domain.hypothesis import HypothesisContent
from co_scientist.domain.source_units import SourceUnitV2, resolve_source_units_v2

LineageRelationV2 = Literal[
    "retained_from", "modified_from", "split_from", "combined_from", "new_claim"
]
EdgeRelationV2 = Literal["retained_from", "modified_from", "split_from", "combined_from"]
LineageStateV2 = Literal["complete", "incomplete", "invalid"]
InvalidMappingReasonV2 = Literal[
    "unknown_child_claim", "missing_assignment", "ambiguous_assignment",
    "duplicate_child_assignment", "unknown_target", "duplicate_target_assignment",
]


def _identity(prefix: str, document: dict[str, object]) -> str:
    return prefix + ":" + scientific_hash(document).removeprefix("sha256:")


class ParentClaimRefV2(BaseModel):
    """Qualified identity proposed by Evolution; hashes are never provider fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    parent_hypothesis_id: Text
    parent_claim_id: Text


class ClaimRecordV2(BaseModel):
    """An already accepted V2 claim, bound to locally resolved SourceUnits."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: Text
    hypothesis_id: Text
    hypothesis_content_hash: Sha256
    importance: Literal["critical", "supporting"]
    text: Text
    claim_type: Literal[
        "established_premise", "bridging_inference", "novel_causal_claim",
        "prediction", "competing_explanation",
    ]
    subject: Text
    relation: Text
    object: Text
    source_unit_ids: tuple[Text, ...] = Field(min_length=1)
    semantic_relation: Literal["direct", "paraphrase", "synthesized"]
    source_unit_refs: tuple[SourceUnitV2, ...] = Field(min_length=1)
    diagnostic_quote: str | None = None

    @model_validator(mode="after")
    def validate_source_scope(self) -> ClaimRecordV2:
        resolved = resolve_source_units_v2(
            self.source_unit_ids,
            expected_hypothesis_id=self.hypothesis_id,
            expected_content_hash=self.hypothesis_content_hash,
            allowed_units=self.source_unit_refs,
        )
        if resolved != self.source_unit_refs:
            raise ValueError("claim SourceUnit references do not match their IDs")
        return self


def claim_record_hash_v2(claim: ClaimRecordV2) -> str:
    """Versioned hash of scientific claim identity and authoritative provenance IDs."""
    return scientific_hash({
        "contract_version": "claim-record-v2",
        "claim_id": claim.claim_id,
        "hypothesis_id": claim.hypothesis_id,
        "hypothesis_content_hash": claim.hypothesis_content_hash,
        "importance": claim.importance,
        "text": claim.text,
        "claim_type": claim.claim_type,
        "subject": claim.subject,
        "relation": claim.relation,
        "object": claim.object,
        "source_unit_ids": list(claim.source_unit_ids),
        "semantic_relation": claim.semantic_relation,
    })


class FrozenParentHypothesisV2(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    hypothesis_id: Text
    content: HypothesisContent
    claims: tuple[ClaimRecordV2, ...]

    @model_validator(mode="after")
    def validate_claims(self) -> FrozenParentHypothesisV2:
        if len({claim.claim_id for claim in self.claims}) != len(self.claims):
            raise ValueError("duplicate claim ID within one parent hypothesis")
        if any(
            claim.hypothesis_id != self.hypothesis_id
            or claim.hypothesis_content_hash != self.content.content_hash
            for claim in self.claims
        ):
            raise ValueError("parent claim does not match frozen hypothesis content")
        return self


class AcceptedClaimDecompositionV2(BaseModel):
    """Local view of a V2 result after normal provenance/task validation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    result_id: Text
    research_plan_version: int = Field(ge=1)
    hypothesis_id: Text
    hypothesis_content_hash: Sha256
    claims: tuple[ClaimRecordV2, ...]

    @model_validator(mode="after")
    def validate_claims(self) -> AcceptedClaimDecompositionV2:
        if not self.claims or not any(claim.importance == "critical" for claim in self.claims):
            raise ValueError("accepted decomposition requires a critical child claim")
        if len({claim.claim_id for claim in self.claims}) != len(self.claims):
            raise ValueError("duplicate child claim ID")
        if any(
            claim.hypothesis_id != self.hypothesis_id
            or claim.hypothesis_content_hash != self.hypothesis_content_hash
            for claim in self.claims
        ):
            raise ValueError("child claim does not match accepted decomposition")
        return self

    @property
    def result_hash(self) -> str:
        return scientific_hash(self.model_dump(mode="json"))


class ResolvedParentClaimRefV2(BaseModel):
    """Exact qualified parent ref plus two locally derived immutable hashes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: Literal["resolved-parent-claim-ref-v2"] = "resolved-parent-claim-ref-v2"
    parent_hypothesis_id: Text
    parent_claim_id: Text
    parent_hypothesis_content_hash: Sha256
    parent_claim_record_hash: Sha256


class FrozenParentContextRefV2(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    parent_hypothesis_id: Text
    parent_hypothesis_content_hash: Sha256


class LineageChangeProposalV2(BaseModel):
    """Validated proposed target group; the provider will expose this in Slice 2."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    target_key: Text
    parent_claim_refs: tuple[ParentClaimRefV2, ...]
    relation: LineageRelationV2
    intended_change: Text

    @model_validator(mode="after")
    def validate_relation(self) -> LineageChangeProposalV2:
        keys = [(ref.parent_hypothesis_id, ref.parent_claim_id)
                for ref in self.parent_claim_refs]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate qualified parent claim ref")
        count = len(keys)
        if self.relation == "combined_from" and count < 2:
            raise ValueError("combined_from requires at least two parents")
        if self.relation == "new_claim" and count != 0:
            raise ValueError("new_claim cannot reference a parent")
        if self.relation not in {"combined_from", "new_claim"} and count != 1:
            raise ValueError("lineage relation requires exactly one parent")
        return self


class RemovedParentProposalV2(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    parent_claim_ref: ParentClaimRefV2
    rationale: Text


class ClaimLineageTargetV2(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: Literal["claim-lineage-target-v2"] = "claim-lineage-target-v2"
    lineage_target_id: Text
    proposal_id: Text
    generation_id: Text
    child_hypothesis_id: Text
    child_hypothesis_content_hash: Sha256
    resolved_parent_claim_refs: tuple[ResolvedParentClaimRefV2, ...]
    relation: LineageRelationV2
    intended_change: Text
    target_key_hash: Sha256

    @model_validator(mode="after")
    def validate_identity(self) -> ClaimLineageTargetV2:
        keys = [(ref.parent_hypothesis_id, ref.parent_claim_id)
                for ref in self.resolved_parent_claim_refs]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate resolved parent claim ref")
        count = len(keys)
        if self.relation == "combined_from" and count < 2:
            raise ValueError("combined target requires at least two parents")
        if self.relation == "new_claim" and count != 0:
            raise ValueError("new target cannot have parents")
        if self.relation not in {"combined_from", "new_claim"} and count != 1:
            raise ValueError("lineage target requires exactly one parent")
        expected = _target_id(
            self.proposal_id, self.generation_id, self.child_hypothesis_id,
            self.child_hypothesis_content_hash, self.target_key_hash,
        )
        if self.lineage_target_id != expected:
            raise ValueError("lineage target identity mismatch")
        return self


class RemovedParentRecordV2(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: Literal["removed-parent-claim-v2"] = "removed-parent-claim-v2"
    record_id: Text
    proposal_id: Text
    generation_id: Text
    resolved_parent_claim_ref: ResolvedParentClaimRefV2
    rationale: Text

    @model_validator(mode="after")
    def validate_identity(self) -> RemovedParentRecordV2:
        expected = _identity("removed-parent-claim-v2", {
            "proposal_id": self.proposal_id,
            "generation_id": self.generation_id,
            "resolved_parent_claim_ref": self.resolved_parent_claim_ref.model_dump(mode="json"),
            "rationale": self.rationale,
        })
        if self.record_id != expected:
            raise ValueError("removed parent record identity mismatch")
        return self


class FrozenLineagePlanV2(BaseModel):
    """Persistable local target set; no provider-authored identity or hash."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: Literal["frozen-claim-lineage-v2"] = "frozen-claim-lineage-v2"
    proposal_id: Text
    generation_id: Text
    child_hypothesis_id: Text
    child_hypothesis_content_hash: Sha256
    selected_parents: tuple[FrozenParentContextRefV2, ...]
    lineage_parent_scope: tuple[ResolvedParentClaimRefV2, ...]
    targets: tuple[ClaimLineageTargetV2, ...]
    removed_parent_records: tuple[RemovedParentRecordV2, ...]

    @model_validator(mode="after")
    def validate_context(self) -> FrozenLineagePlanV2:
        selected = {ref.parent_hypothesis_id: ref.parent_hypothesis_content_hash
                    for ref in self.selected_parents}
        if len(selected) != len(self.selected_parents):
            raise ValueError("duplicate selected parent hypothesis")
        scope_by_key = {
            (ref.parent_hypothesis_id, ref.parent_claim_id): ref
            for ref in self.lineage_parent_scope
        }
        if len(scope_by_key) != len(self.lineage_parent_scope):
            raise ValueError("duplicate parent claim in frozen lineage scope")
        if self.lineage_parent_scope != tuple(sorted(
            self.lineage_parent_scope,
            key=lambda ref: (ref.parent_hypothesis_id, ref.parent_claim_id),
        )):
            raise ValueError("frozen lineage parent scope is not canonical")
        if any(selected.get(ref.parent_hypothesis_id)
               != ref.parent_hypothesis_content_hash
               for ref in self.lineage_parent_scope):
            raise ValueError("lineage parent scope differs from frozen selection")
        if len({target.lineage_target_id for target in self.targets}) != len(self.targets):
            raise ValueError("duplicate frozen lineage target")
        use: dict[tuple[str, str], list[str]] = {}
        for target in self.targets:
            if (target.proposal_id != self.proposal_id
                    or target.generation_id != self.generation_id
                    or target.child_hypothesis_id != self.child_hypothesis_id
                    or target.child_hypothesis_content_hash != self.child_hypothesis_content_hash):
                raise ValueError("lineage target differs from frozen proposal or child")
            if any(selected.get(ref.parent_hypothesis_id)
                   != ref.parent_hypothesis_content_hash
                   for ref in target.resolved_parent_claim_refs):
                raise ValueError("lineage target parent context differs from frozen selection")
            for ref in target.resolved_parent_claim_refs:
                if scope_by_key.get((ref.parent_hypothesis_id, ref.parent_claim_id)) != ref:
                    raise ValueError("lineage target parent claim is outside frozen scope")
                use.setdefault((ref.parent_hypothesis_id, ref.parent_claim_id), []).append(
                    target.relation)
        if any(len(relations) > 1 and set(relations) != {"split_from"}
               for relations in use.values()):
            raise ValueError("parent claim has multiple targets without explicit split_from")
        removed: set[tuple[str, str]] = set()
        for removal in self.removed_parent_records:
            ref = removal.resolved_parent_claim_ref
            if (removal.proposal_id != self.proposal_id
                    or removal.generation_id != self.generation_id
                    or selected.get(ref.parent_hypothesis_id)
                    != ref.parent_hypothesis_content_hash):
                raise ValueError("removed parent differs from frozen selection")
            key = (ref.parent_hypothesis_id, ref.parent_claim_id)
            if scope_by_key.get(key) != ref:
                raise ValueError("removed parent claim is outside frozen scope")
            if key in removed or key in use:
                raise ValueError("duplicate or conflicting removed parent claim")
            removed.add(key)
        return self


class ClaimLineageAssignmentV2(BaseModel):
    """Proposed mapping; malformed entries are classified by the pure resolver."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    child_claim_id: Text
    lineage_target_id: str | None = None
    is_explicit_new_claim: bool = False


class InvalidLineageMappingV2(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    child_claim_id: str | None
    lineage_target_id: str | None
    reason: InvalidMappingReasonV2


class ClaimLineageEdgeV2(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: Literal["claim-lineage-edge-v2"] = "claim-lineage-edge-v2"
    lineage_edge_id: Text
    proposal_id: Text
    generation_id: Text
    lineage_target_id: Text
    resolved_parent_claim_ref: ResolvedParentClaimRefV2
    child_hypothesis_id: Text
    child_hypothesis_content_hash: Sha256
    child_claim_id: Text
    child_claim_record_hash: Sha256
    relation: EdgeRelationV2
    decomposition_result_id: Text
    decomposition_result_hash: Sha256


class ExplicitNewChildRecordV2(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: Literal["explicit-new-child-claim-v2"] = "explicit-new-child-claim-v2"
    record_id: Text
    child_hypothesis_id: Text
    child_hypothesis_content_hash: Sha256
    child_claim_id: Text
    child_claim_record_hash: Sha256
    lineage_target_id: str | None
    decomposition_result_id: Text
    decomposition_result_hash: Sha256


class ClaimLineageApplicationV2(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: Literal["claim-lineage-application-v2"] = "claim-lineage-application-v2"
    proposal_id: Text
    generation_id: Text
    child_hypothesis_id: Text
    child_hypothesis_content_hash: Sha256
    decomposition_result_id: Text
    decomposition_result_hash: Sha256
    lineage_parent_scope: tuple[ResolvedParentClaimRefV2, ...]
    frozen_targets: tuple[ClaimLineageTargetV2, ...]
    edges: tuple[ClaimLineageEdgeV2, ...]
    explicit_new_child_records: tuple[ExplicitNewChildRecordV2, ...]
    removed_parent_records: tuple[RemovedParentRecordV2, ...]
    unresolved_target_ids: tuple[str, ...]
    unaccounted_parent_claim_refs: tuple[ResolvedParentClaimRefV2, ...]
    invalid_mappings: tuple[InvalidLineageMappingV2, ...]
    state: LineageStateV2

    @model_validator(mode="after")
    def validate_state(self) -> ClaimLineageApplicationV2:
        accounted = {
            (ref.parent_hypothesis_id, ref.parent_claim_id)
            for target in self.frozen_targets
            for ref in target.resolved_parent_claim_refs
        }
        accounted.update(
            (record.resolved_parent_claim_ref.parent_hypothesis_id,
             record.resolved_parent_claim_ref.parent_claim_id)
            for record in self.removed_parent_records
        )
        expected_unaccounted = tuple(
            ref for ref in self.lineage_parent_scope
            if (ref.parent_hypothesis_id, ref.parent_claim_id) not in accounted
        )
        if self.unaccounted_parent_claim_refs != expected_unaccounted:
            raise ValueError("unaccounted parent claim scope does not match lineage paths")
        expected: LineageStateV2 = (
            "invalid" if self.invalid_mappings else
            "incomplete" if self.unresolved_target_ids or expected_unaccounted else "complete"
        )
        if self.state != expected:
            raise ValueError("lineage application state does not match validation results")
        return self


def _target_id(proposal_id: str, generation_id: str, child_id: str,
               child_hash: str, target_key_hash: str) -> str:
    return _identity("claim-lineage-target-v2", {
        "contract_version": "claim-lineage-target-v2",
        "proposal_id": proposal_id, "generation_id": generation_id,
        "child_hypothesis_id": child_id, "child_hypothesis_content_hash": child_hash,
        "target_key_hash": target_key_hash,
    })


def _resolve_parent(
    ref: ParentClaimRefV2, parents: dict[str, FrozenParentHypothesisV2],
) -> ResolvedParentClaimRefV2:
    parent = parents.get(ref.parent_hypothesis_id)
    if parent is None:
        raise ValueError("parent hypothesis is not in frozen selection")
    claim = next((item for item in parent.claims if item.claim_id == ref.parent_claim_id), None)
    if claim is None:
        raise ValueError("parent claim does not exist in named hypothesis")
    return ResolvedParentClaimRefV2(
        parent_hypothesis_id=parent.hypothesis_id,
        parent_claim_id=claim.claim_id,
        parent_hypothesis_content_hash=parent.content.content_hash,
        parent_claim_record_hash=claim_record_hash_v2(claim),
    )


def _parent_scope(
    parents: tuple[FrozenParentHypothesisV2, ...],
) -> tuple[ResolvedParentClaimRefV2, ...]:
    by_id = {parent.hypothesis_id: parent for parent in parents}
    refs = (
        ParentClaimRefV2(parent_hypothesis_id=parent.hypothesis_id,
                         parent_claim_id=claim.claim_id)
        for parent in parents for claim in parent.claims
    )
    return tuple(sorted(
        (_resolve_parent(ref, by_id) for ref in refs),
        key=lambda ref: (ref.parent_hypothesis_id, ref.parent_claim_id),
    ))


def freeze_claim_lineage_v2(
    *, proposal_id: str, generation_id: str, child_hypothesis_id: str,
    child_content: HypothesisContent,
    parents: tuple[FrozenParentHypothesisV2, ...],
    changes: tuple[LineageChangeProposalV2, ...],
    removed_parent_proposals: tuple[RemovedParentProposalV2, ...] = (),
) -> FrozenLineagePlanV2:
    """Locally freeze qualified parent claims and deterministic target IDs."""
    if len({parent.hypothesis_id for parent in parents}) != len(parents):
        raise ValueError("duplicate frozen parent hypothesis")
    if len({change.target_key for change in changes}) != len(changes):
        raise ValueError("duplicate lineage target key")
    by_id = {parent.hypothesis_id: parent for parent in parents}
    targets: list[ClaimLineageTargetV2] = []
    use: dict[tuple[str, str], list[str]] = {}
    for change in changes:
        refs = tuple(_resolve_parent(ref, by_id) for ref in change.parent_claim_refs)
        for ref in refs:
            use.setdefault((ref.parent_hypothesis_id, ref.parent_claim_id), []).append(
                change.relation)
        key_hash = scientific_hash({"contract_version": "lineage-target-key-v2",
                                    "target_key": change.target_key})
        targets.append(ClaimLineageTargetV2(
            lineage_target_id=_target_id(proposal_id, generation_id, child_hypothesis_id,
                                          child_content.content_hash, key_hash),
            proposal_id=proposal_id, generation_id=generation_id,
            child_hypothesis_id=child_hypothesis_id,
            child_hypothesis_content_hash=child_content.content_hash,
            resolved_parent_claim_refs=refs, relation=change.relation,
            intended_change=change.intended_change, target_key_hash=key_hash,
        ))
    if any(len(relations) > 1 and set(relations) != {"split_from"}
           for relations in use.values()):
        raise ValueError("parent claim has multiple targets without explicit split_from")
    removals: list[RemovedParentRecordV2] = []
    seen_removals: set[tuple[str, str]] = set()
    for proposal in removed_parent_proposals:
        ref = _resolve_parent(proposal.parent_claim_ref, by_id)
        key = (ref.parent_hypothesis_id, ref.parent_claim_id)
        if key in seen_removals or key in use:
            raise ValueError("duplicate or conflicting removed parent claim")
        seen_removals.add(key)
        removals.append(RemovedParentRecordV2(
            record_id=_identity("removed-parent-claim-v2", {
                "proposal_id": proposal_id, "generation_id": generation_id,
                "resolved_parent_claim_ref": ref.model_dump(mode="json"),
                "rationale": proposal.rationale,
            }),
            proposal_id=proposal_id, generation_id=generation_id,
            resolved_parent_claim_ref=ref, rationale=proposal.rationale,
        ))
    return FrozenLineagePlanV2(
        proposal_id=proposal_id, generation_id=generation_id,
        child_hypothesis_id=child_hypothesis_id,
        child_hypothesis_content_hash=child_content.content_hash,
        selected_parents=tuple(FrozenParentContextRefV2(
            parent_hypothesis_id=parent.hypothesis_id,
            parent_hypothesis_content_hash=parent.content.content_hash,
        ) for parent in parents),
        lineage_parent_scope=_parent_scope(parents),
        targets=tuple(targets), removed_parent_records=tuple(removals),
    )


def _assert_frozen_context(
    plan: FrozenLineagePlanV2, parents: tuple[FrozenParentHypothesisV2, ...],
    decomposition: AcceptedClaimDecompositionV2,
) -> None:
    FrozenLineagePlanV2.model_validate(plan.model_dump(mode="python"))
    if (decomposition.hypothesis_id != plan.child_hypothesis_id
            or decomposition.hypothesis_content_hash != plan.child_hypothesis_content_hash):
        raise ValueError("child decomposition does not match frozen lineage content")
    actual = {(parent.hypothesis_id, parent.content.content_hash) for parent in parents}
    expected = {(ref.parent_hypothesis_id, ref.parent_hypothesis_content_hash)
                for ref in plan.selected_parents}
    if len(actual) != len(parents) or actual != expected:
        raise ValueError("parent selection differs from frozen lineage context")
    if plan.lineage_parent_scope != _parent_scope(parents):
        raise ValueError("frozen parent claim scope differs from current parent claims")
    by_id = {parent.hypothesis_id: parent for parent in parents}
    for target in plan.targets:
        for ref in target.resolved_parent_claim_refs:
            current = _resolve_parent(ParentClaimRefV2(
                parent_hypothesis_id=ref.parent_hypothesis_id,
                parent_claim_id=ref.parent_claim_id,
            ), by_id)
            if current != ref:
                raise ValueError("parent claim identity or hash differs from frozen target")
    for removal in plan.removed_parent_records:
        ref = removal.resolved_parent_claim_ref
        current = _resolve_parent(ParentClaimRefV2(
            parent_hypothesis_id=ref.parent_hypothesis_id, parent_claim_id=ref.parent_claim_id,
        ), by_id)
        if current != ref:
            raise ValueError("parent removal differs from frozen proposal")


def resolve_claim_lineage_v2(
    *, plan: FrozenLineagePlanV2,
    parents: tuple[FrozenParentHypothesisV2, ...],
    decomposition: AcceptedClaimDecompositionV2,
    assignments: tuple[ClaimLineageAssignmentV2, ...],
) -> ClaimLineageApplicationV2:
    """Resolve only explicit target/new markers; retain valid independent edges."""
    _assert_frozen_context(plan, parents, decomposition)
    target_by_id = {target.lineage_target_id: target for target in plan.targets}
    if len(target_by_id) != len(plan.targets):
        raise ValueError("duplicate frozen lineage target identity")
    claim_by_id = {claim.claim_id: claim for claim in decomposition.claims}
    assignments_by_claim: dict[str, list[ClaimLineageAssignmentV2]] = {}
    invalid: list[InvalidLineageMappingV2] = []
    for assignment in assignments:
        if assignment.child_claim_id not in claim_by_id:
            invalid.append(InvalidLineageMappingV2(
                child_claim_id=assignment.child_claim_id,
                lineage_target_id=assignment.lineage_target_id,
                reason="unknown_child_claim",
            ))
        else:
            assignments_by_claim.setdefault(assignment.child_claim_id, []).append(assignment)
    target_counts = Counter(
        assignment.lineage_target_id for assignment in assignments
        if assignment.child_claim_id in claim_by_id
        and assignment.lineage_target_id in target_by_id
    )
    edges: list[ClaimLineageEdgeV2] = []
    new_records: list[ExplicitNewChildRecordV2] = []
    resolved_targets: set[str] = set()
    result_hash = decomposition.result_hash
    for claim in decomposition.claims:
        entries = assignments_by_claim.get(claim.claim_id, [])
        if len(entries) != 1:
            invalid.append(InvalidLineageMappingV2(
                child_claim_id=claim.claim_id, lineage_target_id=None,
                reason="missing_assignment" if not entries else "duplicate_child_assignment",
            ))
            continue
        assignment = entries[0]
        target_id = assignment.lineage_target_id
        reason: InvalidMappingReasonV2 | None = None
        if (target_id is None) == (not assignment.is_explicit_new_claim):
            reason = "ambiguous_assignment"
        elif target_id is not None and target_id not in target_by_id:
            reason = "unknown_target"
        elif target_id is not None and target_counts[target_id] != 1:
            reason = "duplicate_target_assignment"
        if reason is not None:
            invalid.append(InvalidLineageMappingV2(
                child_claim_id=claim.claim_id, lineage_target_id=target_id, reason=reason,
            ))
            continue
        claim_hash = claim_record_hash_v2(claim)
        if target_id is None:
            new_records.append(_new_child_record(plan, decomposition, claim, claim_hash, None))
            continue
        target = target_by_id[target_id]
        resolved_targets.add(target_id)
        if target.relation == "new_claim":
            new_records.append(_new_child_record(plan, decomposition, claim, claim_hash, target_id))
            continue
        for parent_ref in target.resolved_parent_claim_refs:
            edge_id = _identity("claim-lineage-edge-v2", {
                "proposal_id": plan.proposal_id, "generation_id": plan.generation_id,
                "lineage_target_id": target_id,
                "parent": parent_ref.model_dump(mode="json"),
                "child_hypothesis_id": plan.child_hypothesis_id,
                "child_claim_id": claim.claim_id, "child_claim_record_hash": claim_hash,
                "decomposition_result_id": decomposition.result_id,
                "decomposition_result_hash": result_hash,
            })
            edges.append(ClaimLineageEdgeV2(
                lineage_edge_id=edge_id, proposal_id=plan.proposal_id,
                generation_id=plan.generation_id, lineage_target_id=target_id,
                resolved_parent_claim_ref=parent_ref,
                child_hypothesis_id=plan.child_hypothesis_id,
                child_hypothesis_content_hash=plan.child_hypothesis_content_hash,
                child_claim_id=claim.claim_id, child_claim_record_hash=claim_hash,
                relation=target.relation, decomposition_result_id=decomposition.result_id,
                decomposition_result_hash=result_hash,
            ))
    unresolved = tuple(target.lineage_target_id for target in plan.targets
                       if target.lineage_target_id not in resolved_targets)
    accounted = {
        (ref.parent_hypothesis_id, ref.parent_claim_id)
        for target in plan.targets for ref in target.resolved_parent_claim_refs
    }
    accounted.update(
        (record.resolved_parent_claim_ref.parent_hypothesis_id,
         record.resolved_parent_claim_ref.parent_claim_id)
        for record in plan.removed_parent_records
    )
    unaccounted = tuple(
        ref for ref in plan.lineage_parent_scope
        if (ref.parent_hypothesis_id, ref.parent_claim_id) not in accounted
    )
    state: LineageStateV2 = (
        "invalid" if invalid else
        "incomplete" if unresolved or unaccounted else "complete"
    )
    return ClaimLineageApplicationV2(
        proposal_id=plan.proposal_id, generation_id=plan.generation_id,
        child_hypothesis_id=plan.child_hypothesis_id,
        child_hypothesis_content_hash=plan.child_hypothesis_content_hash,
        decomposition_result_id=decomposition.result_id, decomposition_result_hash=result_hash,
        lineage_parent_scope=plan.lineage_parent_scope,
        frozen_targets=plan.targets, edges=tuple(edges),
        explicit_new_child_records=tuple(new_records),
        removed_parent_records=plan.removed_parent_records,
        unresolved_target_ids=unresolved,
        unaccounted_parent_claim_refs=unaccounted,
        invalid_mappings=tuple(invalid), state=state,
    )


def _new_child_record(
    plan: FrozenLineagePlanV2, decomposition: AcceptedClaimDecompositionV2,
    claim: ClaimRecordV2, claim_hash: str, target_id: str | None,
) -> ExplicitNewChildRecordV2:
    return ExplicitNewChildRecordV2(
        record_id=_identity("explicit-new-child-claim-v2", {
            "proposal_id": plan.proposal_id, "generation_id": plan.generation_id,
            "child_hypothesis_id": plan.child_hypothesis_id,
            "child_claim_id": claim.claim_id, "child_claim_record_hash": claim_hash,
            "lineage_target_id": target_id,
        }),
        child_hypothesis_id=plan.child_hypothesis_id,
        child_hypothesis_content_hash=plan.child_hypothesis_content_hash,
        child_claim_id=claim.claim_id, child_claim_record_hash=claim_hash,
        lineage_target_id=target_id,
        decomposition_result_id=decomposition.result_id,
        decomposition_result_hash=decomposition.result_hash,
    )
