"""Explicit, additive ClaimLineageV2 event path; V1 replay remains untouched."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from co_scientist.agents.payloads import ClaimDecompositionResultV3
from co_scientist.domain.claim_lineage import (
    AcceptedClaimDecompositionV2,
    ClaimLineageApplicationV2,
    ClaimLineageAssignmentV2,
    ClaimRecordV2,
    FrozenLineagePlanV2,
    FrozenParentHypothesisV2,
    claim_record_hash_v2,
    resolve_claim_lineage_v2,
)
from co_scientist.domain.claim_verification import scientific_hash
from co_scientist.domain.hypothesis import HypothesisContent
from co_scientist.domain.source_units import source_units_v2_for_content
from co_scientist.events.models import DomainEvent, NewEvent
from co_scientist.ports.external_provider import thaw_json
from co_scientist.runtime.task_payload import WorkerTaskPayload


def claim_created_event_v2(
    claim: ClaimRecordV2, *, research_plan_version: int,
    source_result_id: str, run_id: str,
) -> NewEvent:
    """Persist accepted V2 claim and local hash without a synthetic V1 span."""
    if research_plan_version < 1:
        raise ValueError("research plan version must be positive")
    return NewEvent(
        event_type="HypothesisClaimCreated", schema_version=2,
        payload={**claim.model_dump(mode="json"),
                 "claim_record_hash": claim_record_hash_v2(claim),
                 "research_plan_version": research_plan_version,
                 "source_result_id": source_result_id},
        causation_id=source_result_id, correlation_id=run_id,
    )


def _claim_from_event(event: DomainEvent, *, parent_id: str, content_hash: str,
                      plan_version: int) -> ClaimRecordV2:
    if event.schema_version != 2:
        raise ValueError("parent claim requires accepted V2 event")
    data = event.payload
    if (data.get("hypothesis_id") != parent_id
            or data.get("hypothesis_content_hash") != content_hash
            or data.get("research_plan_version") != plan_version):
        raise ValueError("parent claim differs from frozen content or plan")
    claim = ClaimRecordV2.model_validate({key: data[key] for key in ClaimRecordV2.model_fields})
    if data.get("claim_record_hash") != claim_record_hash_v2(claim):
        raise ValueError("parent claim record hash mismatch")
    return claim


def durable_parent_scope_v2(
    *, events: Sequence[DomainEvent], selected_parent_ids: tuple[str, ...],
    selected_parent_hashes: Mapping[str, str],
) -> tuple[FrozenParentHypothesisV2, ...]:
    """Build the *entire* accepted/current claim scope from durable event state.

    Caller-supplied claims are deliberately not accepted. The selected parent
    identity and content hash are checked against the immutable content event.
    """
    if (not selected_parent_ids or len(set(selected_parent_ids)) != len(selected_parent_ids)
            or set(selected_parent_hashes) != set(selected_parent_ids)):
        raise ValueError("selected parent identities are incomplete or duplicated")
    parents: list[FrozenParentHypothesisV2] = []
    for parent_id in selected_parent_ids:
        expected_hash = selected_parent_hashes[parent_id]
        contents = [event for event in events
                    if event.event_type == "HypothesisContentCreated"
                    and event.payload.get("hypothesis_id") == parent_id]
        if len(contents) != 1:
            raise ValueError("selected parent requires one immutable content event")
        content_event = contents[0]
        if content_event.payload.get("content_hash") != expected_hash:
            raise ValueError("selected parent content hash mismatch")
        content = HypothesisContent.model_validate(dict(content_event.payload))
        if content.content_hash != expected_hash:
            raise ValueError("durable parent content hash mismatch")
        plan_version = content_event.payload.get("research_plan_version")
        if not isinstance(plan_version, int) or plan_version < 1:
            raise ValueError("parent research plan version is missing")
        claims = tuple(_claim_from_event(event, parent_id=parent_id,
                                         content_hash=expected_hash,
                                         plan_version=plan_version)
                       for event in events
                       if event.event_type == "HypothesisClaimCreated"
                       and event.schema_version == 2
                       and event.payload.get("hypothesis_id") == parent_id
                       and event.payload.get("hypothesis_content_hash") == expected_hash)
        if not claims:
            raise ValueError("selected parent has no accepted V2 claims")
        allowed_units = {unit.source_unit_id: unit for unit in source_units_v2_for_content({
            "hypothesis_id": parent_id,
            "content_hash": expected_hash,
            "hypothesis_content": content.model_dump(mode="json"),
        })}
        for claim in claims:
            if claim.source_unit_refs != tuple(allowed_units.get(source_id)
                                               for source_id in claim.source_unit_ids):
                raise ValueError("parent claim SourceUnits differ from immutable content")
        parents.append(FrozenParentHypothesisV2(
            hypothesis_id=parent_id, content=content, claims=claims,
        ))
    return tuple(parents)


def durable_evolution_parent_inputs_v2(
    *, events: Sequence[DomainEvent], inputs: Mapping[str, Any],
    active_epoch_id: str, research_plan_version: int,
) -> dict[str, Any]:
    """Derive an exhaustive provider-visible parent scope from current durable state."""
    selected = inputs.get("parent_ids")
    hashes = inputs.get("parent_content_hashes")
    if (not isinstance(selected, list | tuple) or not selected
            or not all(isinstance(item, str) for item in selected)
            or not isinstance(hashes, Mapping)):
        raise ValueError("lineage Evolution has no frozen selected parent identities")
    ids = tuple(selected)
    decisions = [event for event in events
                 if event.event_type == "ParentSelectionDecisionRecorded"
                 and event.payload.get("decision_id") == inputs.get("selection_decision_id")]
    if (len(decisions) != 1
            or decisions[0].payload.get("generation_id") != inputs.get("generation_id")
            or tuple(decisions[0].payload.get("chosen_parent_ids", ())) != ids
            or decisions[0].payload.get("operator") != inputs.get("operator")
            or decisions[0].payload.get("mutation_subtype") != inputs.get("mutation_subtype")):
        raise ValueError("lineage Evolution differs from durable parent selection")
    parents = durable_parent_scope_v2(
        events=events, selected_parent_ids=ids,
        selected_parent_hashes={str(key): str(value) for key, value in hashes.items()},
    )
    for parent in parents:
        if not any(event.event_type == "TournamentEntryCreated"
                   and event.payload.get("epoch_id") == active_epoch_id
                   and event.payload.get("hypothesis_id") == parent.hypothesis_id
                   and event.payload.get("content_hash") == parent.content.content_hash
                   for event in events):
            raise ValueError("lineage Evolution parent is not durably admitted in current epoch")
        contents = [event for event in events
                    if event.event_type == "HypothesisContentCreated"
                    and event.payload.get("hypothesis_id") == parent.hypothesis_id]
        if len(contents) != 1 or contents[0].payload.get(
            "research_plan_version"
        ) != research_plan_version:
            raise ValueError("lineage Evolution parent plan version is not current")
    claims = [{
        "parent_claim_ref": {
            "parent_hypothesis_id": parent.hypothesis_id,
            "parent_claim_id": claim.claim_id,
        },
        "parent_hypothesis_content_hash": parent.content.content_hash,
        "claim_record_hash": claim_record_hash_v2(claim),
        "text": claim.text,
        "importance": claim.importance,
    } for parent in parents for claim in parent.claims]
    return {"selected_parent_claims": claims,
            "lineage_parent_scope_hash": scientific_hash({"claims": claims})}


def validated_event_payload(event: DomainEvent, expected: Mapping[str, Any]) -> None:
    """Compare the actual stored payload rather than trusting a task-supplied ID."""
    if dict(event.payload) != dict(expected):
        raise ValueError("persisted lineage event payload differs from task binding")


def frozen_targets_event_id_v2(*, run_id: str, plan: FrozenLineagePlanV2,
                               source_result_id: str) -> str:
    """Stable identity independent of task input and event stream sequence."""
    return scientific_hash({
        "contract_version": "claim-lineage-targets-frozen-v2",
        "run_id": run_id, "proposal_id": plan.proposal_id,
        "generation_id": plan.generation_id,
        "child_hypothesis_id": plan.child_hypothesis_id,
        "frozen_lineage_plan_hash": scientific_hash(plan.model_dump(mode="json")),
        "source_result_id": source_result_id,
    })


def frozen_targets_event_v2(
    *, run_id: str, plan: FrozenLineagePlanV2, source_result_id: str,
    source_task_id: str, raw_artifact_ref: Mapping[str, Any],
    proposal_payload: Mapping[str, Any],
    lineage_workflow_contract_hash: str, offspring_task_id: str,
    offspring_task_snapshot_hash: str,
) -> NewEvent:
    """Bind the exact local plan and child task to one deterministic event identity."""
    plan_data = plan.model_dump(mode="json")
    plan_hash = scientific_hash(plan_data)
    identity = frozen_targets_event_id_v2(
        run_id=run_id, plan=plan, source_result_id=source_result_id,
    )
    return NewEvent(
        event_type="ClaimLineageTargetsFrozenV2", schema_version=2,
        payload={
            "contract_version": "claim-lineage-targets-frozen-v2",
            "lineage_targets_frozen_event_id": identity,
            "frozen_lineage_plan": plan_data,
            "frozen_lineage_plan_hash": plan_hash,
            "source_result_id": source_result_id,
            "source_task_id": source_task_id,
            "raw_artifact_ref": dict(raw_artifact_ref),
            "proposal_payload": dict(proposal_payload),
            "lineage_workflow_contract_hash": lineage_workflow_contract_hash,
            "offspring_task_id": offspring_task_id,
            "offspring_task_snapshot_hash": offspring_task_snapshot_hash,
        },
        causation_id=source_result_id, correlation_id=run_id,
    )


def validate_persisted_offspring_task_v2(
    *, events: Sequence[DomainEvent], task: WorkerTaskPayload,
    task_id: str, run_id: str,
) -> FrozenLineagePlanV2:
    """Resolve the actual stored target event; a task's claimed event ID is not authority."""
    if (task.output_schema_id != "ClaimDecompositionResultV3"
            or task.output_schema_version != 3):
        raise ValueError("not a lineage-aware offspring decomposition task")
    plan_data = task.inputs.get("frozen_lineage_plan")
    plan = FrozenLineagePlanV2.model_validate(plan_data)
    matches = [event for event in events
               if event.event_type == "ClaimLineageTargetsFrozenV2"
               and event.schema_version == 2
               and event.payload.get("offspring_task_id") == task_id]
    if len(matches) != 1:
        raise ValueError("offspring task has no unique durable frozen lineage event")
    actual = matches[0]
    actual_payload = thaw_json(actual.payload)
    if (actual.run_id != run_id or actual_payload.get("frozen_lineage_plan")
            != plan.model_dump(mode="json")
            or actual_payload.get("lineage_targets_frozen_event_id")
            != frozen_targets_event_id_v2(
                run_id=run_id, plan=plan,
                source_result_id=str(actual_payload.get("source_result_id", "")),
            )
            or actual_payload.get("frozen_lineage_plan_hash")
            != scientific_hash(plan.model_dump(mode="json"))
            or actual_payload.get("lineage_targets_frozen_event_id")
            != task.inputs.get("lineage_targets_frozen_event_id")
            or actual_payload.get("offspring_task_snapshot_hash")
            != task.input_snapshot_hash
            or actual_payload.get("lineage_workflow_contract_hash")
            != task.inputs.get("lineage_workflow_contract_hash")):
        raise ValueError("offspring task differs from persisted frozen lineage event")
    if (task.inputs.get("lineage_targets")
            != [target.model_dump(mode="json") for target in plan.targets]
            or task.inputs.get("lineage_parent_scope")
            != [ref.model_dump(mode="json") for ref in plan.lineage_parent_scope]
            or task.inputs.get("hypothesis_id") != plan.child_hypothesis_id
            or task.inputs.get("content_hash") != plan.child_hypothesis_content_hash):
        raise ValueError("offspring task targets, scope or child identity differ from frozen plan")
    return plan


def resolve_child_decomposition_events_v2(
    *, run_id: str, result_id: str, plan: FrozenLineagePlanV2,
    parents: tuple[FrozenParentHypothesisV2, ...],
    child_content: HypothesisContent, result: ClaimDecompositionResultV3,
) -> tuple[tuple[NewEvent, ...], ClaimLineageApplicationV2]:
    """Persist every accepted V3 claim, then the deterministic lineage aggregate."""
    if child_content.content_hash != plan.child_hypothesis_content_hash:
        raise ValueError("child content differs from frozen lineage plan")
    units = source_units_v2_for_content({
        "hypothesis_id": plan.child_hypothesis_id,
        "content_hash": child_content.content_hash,
        "hypothesis_content": child_content.model_dump(mode="json"),
    })
    allowed_units = {unit.source_unit_id: unit for unit in units}
    if any(tuple(allowed_units.get(source_id) for source_id in claim.source_unit_ids)
           != claim.source_unit_refs for claim in result.claims):
        raise ValueError("child claim source units differ from immutable content")
    claims = tuple(ClaimRecordV2(
        **claim.model_dump(mode="python", exclude={
            "lineage_target_id", "is_explicit_new_claim",
        }),
        hypothesis_id=result.hypothesis_id,
        hypothesis_content_hash=result.hypothesis_content_hash,
    ) for claim in result.claims)
    decomposition = AcceptedClaimDecompositionV2(
        result_id=result_id, research_plan_version=result.research_plan_version,
        hypothesis_id=result.hypothesis_id,
        hypothesis_content_hash=result.hypothesis_content_hash, claims=claims,
    )
    assignments = tuple(ClaimLineageAssignmentV2(
        child_claim_id=claim.claim_id,
        lineage_target_id=claim.lineage_target_id,
        is_explicit_new_claim=claim.is_explicit_new_claim,
    ) for claim in result.claims)
    application = resolve_claim_lineage_v2(
        plan=plan, parents=parents, decomposition=decomposition,
        assignments=assignments,
    )
    events = tuple(claim_created_event_v2(
        claim, research_plan_version=result.research_plan_version,
        source_result_id=result_id, run_id=run_id,
    ) for claim in claims)
    applied = NewEvent(
        event_type="ClaimLineageAppliedV2", schema_version=2,
        payload={"contract_version": "claim-lineage-applied-v2",
                 "source_result_id": result_id,
                 "application": application.model_dump(mode="json"),
                 "application_hash": scientific_hash(application.model_dump(mode="json"))},
        causation_id=result_id, correlation_id=run_id,
    )
    return (*events, applied), application
