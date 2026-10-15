"""Closed schema-version matrix for scientific domain events."""

from collections.abc import Mapping
from types import MappingProxyType

from pydantic import BaseModel

from co_scientist.events.models import DomainEvent, NewEvent

EVENT_SCHEMA_VERSIONS: Mapping[str, frozenset[int]] = MappingProxyType(
    {
        "ContinuousAttemptPreparedV1": frozenset({1}),
        "ContinuousCostRiskRetainedV1": frozenset({1}),
        "ContinuousTaskExhaustedV1": frozenset({1}),
        "ContinuousOriginalRecoveryPlannedV1": frozenset({1}),
        "BaselineRankingRecordedV1": frozenset({1}),
        "BaselineEvolutionRecordedV1": frozenset({1}),
        "BaselineReproductionPlannedV1": frozenset({1}),
        "BaselineGenerationCompletedV1": frozenset({1}),
        "IdeationFinalSelectionV1": frozenset({1}),
        "DirectiveEthicsRecordedV1": frozenset({1}),
        "RootReviewPlannedV1": frozenset({1}),
        "RootRetrievalOutcomeRecordedV1": frozenset({1}),
        "RootRetrievalOutcomeRecordedV2": frozenset({2}),
        "RootRetrievalReusedV2": frozenset({2}),
        "GroundedGenerationRecordedV1": frozenset({1}),
        "BaselineReflectionRecordedV1": frozenset({1}),
        "RootSourceReviewRecordedV1": frozenset({1}),
        "RootGroundingFrozenV1": frozenset({1}),
        "CandidateEthicsRecordedV1": frozenset({1}),
        "CandidateSafeRedesignRecordedV1": frozenset({1}),
        "IdeationSlotResolvedV1": frozenset({1}),
        "IdeationSlotResolvedV2": frozenset({2}),
        "HypothesisContentCreated": frozenset({2}),
        "HypothesisClaimCreated": frozenset({1, 2}),
        "ClaimLineageTargetsFrozenV2": frozenset({2}),
        "ClaimLineageAppliedV2": frozenset({2}),
        "ClaimSearchPlanned": frozenset({1}),
        "ToolRequestAuthorized": frozenset({1}),
        "ToolRequestDenied": frozenset({1}),
        "SearchSessionOpened": frozenset({1}),
        "SearchSessionClosed": frozenset({1}),
        "ClaimSearchResultRecorded": frozenset({1}),
        "ClaimSearchReused": frozenset({1}),
        "ClaimRetrievalCompleted": frozenset({1}),
        "EvidenceSnapshotRecorded": frozenset({1}),
        "ClaimEvidenceBindingRecorded": frozenset({1}),
        "PriorArtAssessmentRecorded": frozenset({1}),
        "ClaimVerificationCompleted": frozenset({1}),
        "ClaimVerificationAppliedV2": frozenset({2}),
        "ClaimVerificationBindingRejectedV2": frozenset({2}),
        "ReviewCompleted": frozenset({2}),
        "NoveltyAssessmentRecorded": frozenset({1}),
        "ProximityAssessed": frozenset({2}),
        "MetaReviewCompleted": frozenset({2}),
        "ResearchFeedbackRecorded": frozenset({1}),
        "ScientistFeedbackRecorded": frozenset({1}),
        "HypothesisTournamentReady": frozenset({2}),
        "TournamentEntryCreated": frozenset({1}),
        "InitialRatingAssigned": frozenset({1}),
        "MatchEvaluated": frozenset({2}),
        "RatingUpdated": frozenset({1}),
        "BayesianRatingProjected": frozenset({1}),
        "MatchPairReserved": frozenset({1}),
        "PairSchedulerDecision": frozenset({1}),
        "EvidenceGapRecorded": frozenset({1}),
        "ResearchPlanAccepted": frozenset({1}),
        "TournamentEpochOpened": frozenset({1}),
        "TournamentEpochClosed": frozenset({1}),
        "RunForkRequired": frozenset({1}),
        "EvolutionGenerationStarted": frozenset({1}),
        "ParentSelectionDecisionRecorded": frozenset({1}),
        "EvolutionProposalSubmitted": frozenset({1}),
        "EvolutionProposalValidated": frozenset({1}),
        "OffspringHypothesisCreated": frozenset({1}),
        "OffspringValidationStarted": frozenset({1}),
        "ClaimLineageRecorded": frozenset({1}),
        "OffspringAdmitted": frozenset({1}),
        "OffspringRejected": frozenset({1}),
        "OffspringValidationIncomplete": frozenset({1}),
        "EvolutionGenerationCompleted": frozenset({1}),
        "EvolutionSchedulerDecision": frozenset({1}),
    }
)

# Operational compatibility metadata is intentionally outside scientific
# event mutation/reducer semantics. Its schema is still closed and versioned.
PROBE_OPERATIONAL_EVENT_SCHEMA_VERSIONS: Mapping[str, frozenset[int]] = MappingProxyType(
    {"CompatibilityProbeTerminatedV1": frozenset({1})}
)


def assert_supported_event_version(event: DomainEvent) -> None:
    """Fail closed when a known scientific event uses an unknown schema."""

    supported = (EVENT_SCHEMA_VERSIONS.get(event.event_type)
                 or PROBE_OPERATIONAL_EVENT_SCHEMA_VERSIONS.get(event.event_type))
    if supported is not None and event.schema_version not in supported:
        raise ValueError(
            "unsupported scientific event version: "
            f"{event.event_type} v{event.schema_version}"
        )


def assert_ideation_prerequisite_event_payload(event: DomainEvent | NewEvent) -> None:
    """Validate additive shapes only; durable task authority is checked separately."""
    from co_scientist.domain.ideation_prerequisites import (
        EVENT_RESULTS,
        EVENT_RESULTS_V2,
        IdeationSlotResolvedV1,
        IdeationSlotResolvedV2,
        PrerequisiteFactV1,
        RetrievalCompletionFactV2,
        RetrievalReuseV2,
        RootGroundingFrozenV1,
        SafeRedesignV1,
        validate_fact_result,
    )

    local_models: dict[str, type[BaseModel]] = {
        "RootGroundingFrozenV1": RootGroundingFrozenV1,
        "CandidateSafeRedesignRecordedV1": SafeRedesignV1,
        "IdeationSlotResolvedV1": IdeationSlotResolvedV1,
    }
    if event.event_type == "RootRetrievalReusedV2":
        if event.schema_version != 2:
            raise ValueError("unsupported retrieval reuse event version")
        RetrievalReuseV2.model_validate(event.payload)
        return
    if event.event_type == "IdeationSlotResolvedV2":
        if event.schema_version != 2:
            raise ValueError("unsupported retrieval slot-resolution version")
        IdeationSlotResolvedV2.model_validate(event.payload)
        return
    if event.event_type in EVENT_RESULTS_V2:
        if event.schema_version != 2:
            raise ValueError("unsupported prerequisite event version")
        fact_v2 = RetrievalCompletionFactV2.model_validate(event.payload)
        validate_fact_result(fact_v2, EVENT_RESULTS_V2[event.event_type])
        return
    if event.event_type not in EVENT_RESULTS and event.event_type not in local_models:
        return
    if event.schema_version != 1:
        raise ValueError("unsupported prerequisite event version")
    if event.event_type in EVENT_RESULTS:
        fact = PrerequisiteFactV1.model_validate(event.payload)
        schema = EVENT_RESULTS[event.event_type]
        validate_fact_result(fact, schema)
    else:
        local_models[event.event_type].model_validate(event.payload)


def assert_lineage_v2_event_payload(event: DomainEvent | NewEvent) -> None:
    """Validate only additive V2 shapes; never reinterpret historical V1 events."""
    if event.schema_version != 2:
        return
    if event.event_type not in {
        "HypothesisClaimCreated", "ClaimLineageTargetsFrozenV2", "ClaimLineageAppliedV2",
    }:
        return
    from co_scientist.domain.claim_lineage import (
        ClaimLineageApplicationV2,
        ClaimRecordV2,
        FrozenLineagePlanV2,
        claim_record_hash_v2,
    )
    from co_scientist.domain.claim_verification import scientific_hash

    data = event.payload
    if event.event_type == "HypothesisClaimCreated":
        if "source_span" in data or "source_relation" in data:
            raise ValueError("V2 claim event must not carry synthetic V1 provenance")
        claim = ClaimRecordV2.model_validate({key: data[key]
                                              for key in ClaimRecordV2.model_fields})
        if (data.get("claim_record_hash") != claim_record_hash_v2(claim)
                or not isinstance(data.get("source_result_id"), str)
                or not data["source_result_id"]
                or not isinstance(data.get("research_plan_version"), int)
                or data["research_plan_version"] < 1):
            raise ValueError("V2 claim event has invalid local hash or result identity")
    elif event.event_type == "ClaimLineageTargetsFrozenV2":
        plan = FrozenLineagePlanV2.model_validate(data.get("frozen_lineage_plan"))
        if (data.get("contract_version") != "claim-lineage-targets-frozen-v2"
                or data.get("frozen_lineage_plan_hash")
                != scientific_hash(plan.model_dump(mode="json"))
                or not isinstance(data.get("source_result_id"), str)
                or not data["source_result_id"]):
            raise ValueError("V2 lineage target event identity is invalid")
    else:
        application = ClaimLineageApplicationV2.model_validate(data.get("application"))
        if (data.get("contract_version") != "claim-lineage-applied-v2"
                or data.get("application_hash")
                != scientific_hash(application.model_dump(mode="json"))
                or not isinstance(data.get("source_result_id"), str)
                or not data["source_result_id"]):
            raise ValueError("V2 lineage application event identity is invalid")
