"""Read-only V2 lineage projection; historical V1 reducers are unchanged."""

from __future__ import annotations

from collections.abc import Sequence

from co_scientist.domain.claim_lineage import (
    ClaimLineageApplicationV2,
    ClaimRecordV2,
    FrozenLineagePlanV2,
    claim_record_hash_v2,
)
from co_scientist.events.contracts import (
    assert_lineage_v2_event_payload,
    assert_supported_event_version,
)
from co_scientist.events.models import DomainEvent


def replay_claim_lineage_v2(
    events: Sequence[DomainEvent],
) -> dict[str, ClaimLineageApplicationV2]:
    """Rebuild exactly the saved V2 aggregate without inferring V1 lineage."""
    frozen: dict[tuple[str, str], FrozenLineagePlanV2] = {}
    claims: dict[tuple[str, str, str], ClaimRecordV2] = {}
    applications: dict[str, ClaimLineageApplicationV2] = {}
    last_sequence = 0
    for event in events:
        if event.sequence <= last_sequence:
            raise ValueError("lineage replay requires ordered event sequence")
        last_sequence = event.sequence
        assert_supported_event_version(event)
        assert_lineage_v2_event_payload(event)
        data = event.payload
        if event.event_type == "ClaimLineageTargetsFrozenV2":
            plan = FrozenLineagePlanV2.model_validate(data["frozen_lineage_plan"])
            key = (plan.child_hypothesis_id, plan.proposal_id)
            if key in frozen:
                raise ValueError("duplicate frozen lineage target set")
            frozen[key] = plan
        elif event.event_type == "HypothesisClaimCreated" and event.schema_version == 2:
            claim = ClaimRecordV2.model_validate({field: data[field]
                                                   for field in ClaimRecordV2.model_fields})
            claim_key = (claim.hypothesis_id, claim.hypothesis_content_hash,
                         claim.claim_id)
            if (claim_key in claims
                    or data["claim_record_hash"] != claim_record_hash_v2(claim)):
                raise ValueError("duplicate or altered V2 child claim record")
            claims[claim_key] = claim
        elif event.event_type == "ClaimLineageAppliedV2":
            application = ClaimLineageApplicationV2.model_validate(data["application"])
            key = (application.child_hypothesis_id, application.proposal_id)
            matched_plan = frozen.get(key)
            if matched_plan is None or application.child_hypothesis_id in applications:
                raise ValueError("lineage application lacks one prior frozen target set")
            if (application.child_hypothesis_content_hash
                    != matched_plan.child_hypothesis_content_hash
                    or application.lineage_parent_scope != matched_plan.lineage_parent_scope
                    or application.frozen_targets != matched_plan.targets
                    or application.removed_parent_records != matched_plan.removed_parent_records):
                raise ValueError("lineage application differs from frozen target event")
            if any(claims.get((application.child_hypothesis_id,
                               application.child_hypothesis_content_hash,
                               edge.child_claim_id)) is None
                   or claim_record_hash_v2(claims[(application.child_hypothesis_id,
                                                   application.child_hypothesis_content_hash,
                                                   edge.child_claim_id)])
                   != edge.child_claim_record_hash for edge in application.edges):
                raise ValueError("lineage edge references a missing or altered child claim")
            if any(claims.get((application.child_hypothesis_id,
                               application.child_hypothesis_content_hash,
                               record.child_claim_id)) is None
                   or claim_record_hash_v2(claims[(application.child_hypothesis_id,
                                                   application.child_hypothesis_content_hash,
                                                   record.child_claim_id)])
                   != record.child_claim_record_hash
                   for record in application.explicit_new_child_records):
                raise ValueError("new-claim record references a missing or altered child claim")
            applications[application.child_hypothesis_id] = application
    return applications
