"""Versioned baseline boundary, not a replacement scientific scheduler.

Batch 2 has not supplied authoritative Ethics/grounding contracts. Production
therefore cannot project PASS from caller flags or legacy Reflection safety.
Fixture truth tables are explicitly separate from durable production reduction.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any, Literal

from co_scientist.domain.hypothesis import HypothesisContent
from co_scientist.domain.research_protocol import ideation_prerequisite_protocol_v2, protocol_hash
from co_scientist.domain.review import Review
from co_scientist.domain.tournament import TournamentEpoch
from co_scientist.events.models import DomainEvent, NewEvent
from co_scientist.ports.external_provider import thaw_json

BASELINE_PROFILE = "2608-ideation-baseline-v1"
BOUNDARY_VERSION = "2608-core-boundary-v1"
SPEC_SHA256 = "000103561ed701648b3ca9b43521e174571cb4b638f6280263f55f5f6ff59874"


def batch34_execution_enabled(manifest: Mapping[str, Any]) -> bool:
    """Explicit additive search identity, never inferred from task/payload shape."""
    from co_scientist.domain.bayesian_ranking import TrueSkillConfig
    from co_scientist.domain.population_evolution import read_search_policy

    profile = manifest.get("profile", {})
    if profile.get("profile_id") == "single-root-dev-live-v1":
        validate_batch2_boundary(manifest)
        return False
    requested = profile.get("ideation_search") is not None or "ideation_search_contract" in manifest
    if not requested:
        return False
    if not batch2_execution_enabled(manifest):
        raise ValueError("baseline search requires version-bound functional prerequisite execution")
    policy = read_search_policy(profile.get("ideation_search", {}))
    if (policy.version == "2608-ideation-search-g3-v1"
            and profile.get("profile_id") != "ideation-performance-dev-g3-v1"):
        raise ValueError("short-cycle policy requires its exact opt-in profile")
    if (manifest.get("ideation_search_contract") != policy.model_dump(mode="json")
            or manifest.get("ideation_search_contract_hash") != protocol_hash(policy.model_dump(mode="json"))
            or manifest.get("ideation_search_skills_hash") != protocol_hash(thaw_json(manifest.get("ideation_search_skills")))
            or TrueSkillConfig.model_validate(profile["tournament"]["trueskill"]) != TrueSkillConfig()):
        raise ValueError("baseline search frozen policy/skill/rating identity mismatch")
    return True


def boundary_contract() -> dict[str, Any]:
    return {
        "version": BOUNDARY_VERSION,
        "profile_id": BASELINE_PROFILE,
        "spec_sha256": SPEC_SHA256,
        "readiness_projection_version": "durable-core-readiness-v1",
        "authority_validation_version": "operation-scoped-authority-v1",
        "prerequisite_reader_version": "ethics-grounding-unimplemented-v1",
        "core_claim_verification_required": False,
        "core_claim_lineage_audit_required": False,
        "core_semantic_proximity_required": False,
        "ranking_population_consumers": "pending-batch-3",
    }


def batch2_boundary_contract() -> dict[str, Any]:
    """Isolated B2-A identity; never upgrade the original boundary reader."""
    return {
        "version": "ideation-core-boundary-v2", "profile_id": BASELINE_PROFILE,
        "spec_sha256": SPEC_SHA256,
        "readiness_projection_version": "ideation-core-readiness-v2",
        "prerequisite_reader_version": "ideation-prerequisites-v1",
        "authority_validation_version": "ideation-task-binding-v1",
        "activation": "CONTRACTS_ONLY_B2_A",
        "core_claim_verification_required": False,
        "core_claim_lineage_audit_required": False,
        "core_semantic_proximity_required": False,
        "ranking_population_consumers": "pending-batch-3",
    }


def batch2_execution_boundary_contract() -> dict[str, Any]:
    contract = batch2_boundary_contract()
    return {**contract, "prerequisite_reader_version": "ideation-prerequisites-v2",
            "readiness_projection_version": "ideation-operation-readiness-v3",
            "activation": "OFFLINE_FUNCTIONAL_B2",
            "retrieval_request_binding": "retrieval-request-binding-v2",
            "retrieval_completion_contract": "retrieval-completion-fact-v2"}


def batch2_execution_enabled(manifest: Mapping[str, Any]) -> bool:
    contract = manifest.get("ideation_prerequisite_contract", {})
    profile = manifest.get("profile", {})
    if ("ideation_prerequisite_contract" in manifest or (
            isinstance(profile, Mapping)
            and profile.get("admission_policy_version") == "ideation-core-boundary-v2")):
        validate_batch2_boundary(manifest)
    if not isinstance(contract, Mapping) or contract.get("version") != "ideation-prerequisites-v2":
        return False
    validate_batch2_boundary(manifest)
    protocol = ideation_prerequisite_protocol_v2()
    if (manifest.get("ideation_prerequisite_protocol") != protocol
            or manifest.get("ideation_prerequisite_protocol_hash") != protocol_hash(protocol)):
        raise ValueError("functional Batch 2 protocol identity mismatch; no fallback")
    return True


def validate_batch2_boundary(manifest: Mapping[str, Any]) -> None:
    from co_scientist.domain.ideation_prerequisites import (
        PrerequisiteExecutionPolicyV2,
        PrerequisitePolicyV1,
    )

    profile = manifest["profile"]
    from co_scientist.domain.single_root import (
        FULL_MODE,
        G3_MODE,
        MODE,
        FullIdeationConfig,
        SingleRootConfig,
    )

    performance = profile.get("profile_id") in {"generation-performance-v1", MODE, FULL_MODE, G3_MODE}
    supplied = profile.get("ideation_prerequisites", {})
    if isinstance(supplied, Mapping) and supplied.get("version") == "ideation-prerequisites-v2":
        policy: PrerequisitePolicyV1 | PrerequisiteExecutionPolicyV2 = (
            PrerequisiteExecutionPolicyV2.model_validate(supplied))
        contract = batch2_execution_boundary_contract()
    else:
        policy = PrerequisitePolicyV1.model_validate(supplied)
        contract = batch2_boundary_contract()
    expected_profile = profile["profile_id"] if performance else BASELINE_PROFILE
    if performance:
        from co_scientist.domain.generation_integration import GenerationPerformanceConfig

        cls = (FullIdeationConfig if expected_profile in {FULL_MODE, G3_MODE} else
               SingleRootConfig if expected_profile == MODE else GenerationPerformanceConfig)
        cls.model_validate(profile.get("execution_runtime"))
        contract = {**contract, "profile_id": expected_profile,
                    "generation_method": "generation-performance-v1"}
    if (manifest.get("profile_id") != expected_profile
            or profile.get("profile_id") != expected_profile
            or profile.get("admission_policy_version") != contract["version"]
            or manifest.get("ideation_core_contract") != contract
            or manifest.get("ideation_core_contract_hash") != protocol_hash(contract)
            or manifest.get("ideation_prerequisite_contract") != policy.model_dump(mode="json")
            or manifest.get("ideation_prerequisite_contract_hash") != protocol_hash(
                policy.model_dump(mode="json"))
            or profile.get("research_protocol_version") != "research-v2"
            or profile.get("anchor_policy") != "none"
            or profile.get("literature_novelty_required") is not False
            or any(profile.get(key) is not None for key in (
                "claim_verification", "claim_output_protocol", "claim_decomposition_output",
                "population_evolution", "lineage_workflow_contract", "probe_execution_envelope"))
            or profile.get("meta_review", {}).get("max_rounds", 0)
            or profile.get("evolution", {}).get("max_rounds", 0)
            or manifest.get("profile_file_hash") is None):
        raise ValueError("invalid frozen Batch 2 baseline contract/profile identity")


def baseline_enabled(manifest: Mapping[str, Any]) -> bool:
    """Validate exact opt-in identity; never reinterpret a legacy profile."""
    profile = manifest.get("profile", {})
    if not isinstance(profile, Mapping):
        raise TypeError("invalid profile identity")
    if profile.get("ideation_core_boundary") == "ideation-core-boundary-v2":
        validate_batch2_boundary(manifest)
        return True
    ids = (manifest.get("profile_id"), profile.get("profile_id"))
    requested = any(isinstance(value, str) and value.startswith("2608-ideation-baseline")
                    for value in ids) or any(key in manifest for key in (
                        "ideation_core_contract", "ideation_core_contract_hash"))
    requested = requested or profile.get("ideation_core_boundary") is not None
    if not requested:
        return False
    if (ids != (BASELINE_PROFILE, BASELINE_PROFILE)
            or profile.get("ideation_core_boundary") != BOUNDARY_VERSION
            or manifest.get("ideation_core_contract") != boundary_contract()
            or manifest.get("ideation_core_contract_hash") != protocol_hash(boundary_contract())
            or profile.get("claim_verification") is not None
            or profile.get("lineage_workflow_contract") is not None
            or profile.get("population_evolution") is not None
            or profile.get("research_protocol_version") != "research-v2"
            or profile.get("anchor_policy") != "none"
            or profile.get("literature_novelty_required") is not False
            or profile.get("meta_review", {}).get("max_rounds", 0)
            or profile.get("evolution", {}).get("max_rounds", 0)):
        raise ValueError("invalid frozen baseline contract/profile identity")
    return True


@dataclass(frozen=True)
class CoreAuthorityV1:
    run_id: str
    directive_version: int
    target_id: str
    epoch_id: str
    hypothesis_id: str
    content_hash: str
    task_id: str = ""
    result_id: str = ""
    schema_id: str = ""
    schema_version: int = 1
    prompt_hash: str = ""
    input_hash: str = ""
    lease_owner: str = ""
    lease_generation: int = 0


@dataclass(frozen=True)
class OperationValidationV1:
    state: Literal["VALID", "QUARANTINED"]
    failed_fields: tuple[str, ...]
    model_visible: bool = False


def validate_operation(
    expected: CoreAuthorityV1, supplied: CoreAuthorityV1,
    *, operation: Literal["core", "optional_audit"],
) -> OperationValidationV1:
    """Identity comparison only. Shared schema/fence/provenance validators stay intact.

    VALID optional audit facts are still not authoritative model context. This is
    an isolated validation boundary, NOT asynchronous exception containment.
    """
    if operation not in {"core", "optional_audit"}:
        raise ValueError("unknown operation scope")
    failed = tuple(key for key, value in asdict(expected).items()
                   if asdict(supplied)[key] != value)
    if failed and operation == "core":
        raise ValueError(f"core authority mismatch: {','.join(failed)}")
    return OperationValidationV1("QUARANTINED" if failed else "VALID", failed)


@dataclass(frozen=True)
class CoreReadinessV1:
    state: Literal["READY", "NOT_READY"]
    missing: tuple[str, ...]
    identity_hash: str
    source_sequences: tuple[int, ...] = ()
    version: str = "durable-core-readiness-v1"
    production: bool = True
    valid_decisive_comparisons: int = 0
    parent_final_eligible: bool = False


@dataclass(frozen=True)
class IsolatedFixtureFactsV1:
    """Only a pure test input; no production API consumes this object."""

    authority: CoreAuthorityV1
    directive_ethics: str = "MISSING"
    grounding: str = "MISSING"
    candidate_ethics: str = "MISSING"
    reflection_completed: bool = False
    reflection_recommendation: str = ""
    optional_audit_state: str = "absent"
    valid_decisive_comparisons: int = 0
    partial_grounding_usable: bool = False


def project_fixture_readiness(facts: IsolatedFixtureFactsV1) -> CoreReadinessV1:
    if not isinstance(facts, IsolatedFixtureFactsV1):
        raise TypeError("requires isolated fixture facts")
    missing = []
    if facts.directive_ethics != "PASS":
        missing.append("directive_ethics")
    if facts.grounding not in {"SUCCESS_NONEMPTY", "SEARCHED_EMPTY"} and not (
        facts.grounding == "PARTIAL" and facts.partial_grounding_usable
    ):
        missing.append("grounding")
    if facts.candidate_ethics != "PASS":
        missing.append("candidate_ethics")
    if not facts.reflection_completed:
        missing.append("reflection_completed")
    identity = asdict(facts.authority)
    if not all(identity[key] for key in (
        "run_id", "directive_version", "target_id", "epoch_id", "hypothesis_id", "content_hash"
    )):
        missing.append("core_identity")
    return CoreReadinessV1(
        "NOT_READY" if missing else "READY", tuple(missing),
        protocol_hash({"contract": boundary_contract(), "fixture": asdict(facts)}),
        production=False, valid_decisive_comparisons=facts.valid_decisive_comparisons,
        parent_final_eligible=not missing and facts.valid_decisive_comparisons >= 2,
    )


def project_durable_readiness(
    manifest: Mapping[str, Any], events: Sequence[DomainEvent | NewEvent],
    *, run_id: str, hypothesis_id: str | None = None,
) -> CoreReadinessV1:
    """Read existing durable authority, never newly invented Ethics/grounding events.

    Replays the active epoch/content/review boundary. Missing Batch 2 authorities
    are explicit prerequisites, not scientific rejection or optional audit failure.
    Unknown event names/flags cannot supply the unimplemented prerequisites.
    """
    if not baseline_enabled(manifest):
        raise ValueError("durable baseline projection requires explicit opt-in")
    if manifest["profile"].get("ideation_core_boundary") == "ideation-core-boundary-v2":
        # The v2 contract is registered, but B2-B execution wiring is not approved.
        # No new prerequisite, even a valid supplied fact, unlocks dispatch here.
        return CoreReadinessV1(
            "NOT_READY", ("b2a_production_dispatch_unimplemented",),
            protocol_hash({"manifest": manifest["ideation_core_contract_hash"],
                           "run_id": run_id, "hypothesis_id": hypothesis_id}),
            version="ideation-core-readiness-v2",
        )
    if any(isinstance(event, DomainEvent) and event.run_id != run_id for event in events):
        raise ValueError("core authority run mismatch")
    epoch: TournamentEpoch | None = None
    sources: list[int] = []
    for event in events:
        if event.event_type == "TournamentEpochOpened":
            if event.schema_version != 1:
                raise ValueError("core authority epoch schema mismatch")
            epoch = TournamentEpoch.model_validate(event.payload)
            if epoch.model_dump(mode="json") != dict(manifest["tournament_contract"]):
                raise ValueError("core authority epoch mismatch")
            if isinstance(event, DomainEvent):
                sources.append(event.sequence)
        elif event.event_type == "TournamentEpochClosed":
            epoch = None
    missing = ["directive_ethics_authority_unimplemented", "grounding_authority_unimplemented"]
    if epoch is None:
        missing.append("active_epoch")
    content_hash: str | None = None
    if hypothesis_id is not None:
        missing.append("candidate_ethics_authority_unimplemented")
        contents = [event for event in events if event.event_type == "HypothesisContentCreated"
                    and event.payload.get("hypothesis_id") == hypothesis_id]
        if len(contents) > 1:
            raise ValueError("core authority ambiguous content")
        if not contents:
            missing.append("hypothesis_content")
        else:
            event = contents[0]
            content = HypothesisContent.model_validate(event.payload)
            content_hash = content.content_hash
            if (event.schema_version != 2 or event.payload.get("content_hash") != content_hash
                    or epoch is None
                    or event.payload.get("research_plan_version") != epoch.research_plan_version):
                raise ValueError("core authority content version/hash mismatch")
            if isinstance(event, DomainEvent):
                sources.append(event.sequence)
            reviews = [event for event in events if event.event_type == "ReviewCompleted"
                       and event.payload.get("hypothesis_id") == hypothesis_id
                       and event.payload.get("content_hash") == content_hash
                       and event.payload.get("research_plan_version") == epoch.research_plan_version]
            for review in reviews:
                if review.schema_version != 2:
                    raise ValueError("core authority review schema mismatch")
                Review.model_validate(review.payload)
                if isinstance(review, DomainEvent):
                    sources.append(review.sequence)
            required = {"initial_review", *manifest["profile"]["review_policy"]["required_before_admission"]}
            if not required.issubset({review.payload["stage"] for review in reviews}):
                missing.append("reflection_completed")
    identity = {"contract": boundary_contract(), "run_id": run_id,
                "goal": manifest.get("goal"), "epoch": manifest.get("tournament_contract"),
                "hypothesis_id": hypothesis_id, "content_hash": content_hash,
                "source_sequences": sources, "missing": missing}
    return CoreReadinessV1("NOT_READY", tuple(missing), protocol_hash(identity), tuple(sources))
