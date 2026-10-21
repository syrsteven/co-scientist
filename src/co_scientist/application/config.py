"""Validated, secret-free Core Preview execution configuration."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal, cast

import yaml  # type: ignore[import-untyped]
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    field_serializer,
    field_validator,
    model_serializer,
    model_validator,
)

from co_scientist.domain.anchors import core_preview_anchor_sets
from co_scientist.domain.bayesian_ranking import TrueSkillConfig, UCBPairingPolicy
from co_scientist.domain.budget import BudgetPolicy
from co_scientist.domain.claim_verification import (
    ClaimDecompositionOutputPolicy,
    ClaimVerificationPolicy,
)
from co_scientist.domain.dispatch_limits import DispatchLimits
from co_scientist.domain.execution_config import EffectiveExecutionConfig
from co_scientist.domain.generation_integration import PROFILE, GenerationPerformanceConfig
from co_scientist.domain.ideation_core_boundary import (
    BASELINE_PROFILE,
    BOUNDARY_VERSION,
    baseline_enabled,
    batch2_boundary_contract,
    batch2_execution_boundary_contract,
    boundary_contract,
)
from co_scientist.domain.ideation_prerequisites import (
    PrerequisiteExecutionPolicyV2,
    PrerequisitePolicyV1,
)
from co_scientist.domain.pilot_pricing import DeepSeekPilotPricing
from co_scientist.domain.population_evolution import (
    BaselineSearchPolicy,
    PopulationEvolutionPolicy,
    ShortSearchPolicy,
)
from co_scientist.domain.probe_execution import ProbeExecutionEnvelopeV1
from co_scientist.domain.ranking_output import strict_ranking_contract
from co_scientist.domain.research_feedback import feedback_contract
from co_scientist.domain.research_protocol import (
    ideation_prerequisite_protocol_v1,
    ideation_prerequisite_protocol_v2,
    protocol_hash,
    research_protocol_v1,
    research_protocol_v2,
)
from co_scientist.domain.review import ReviewPolicy
from co_scientist.domain.single_root import (
    FULL_MODE,
    G3_MODE,
    MODE,
    FullIdeationConfig,
    SingleRootConfig,
)
from co_scientist.ports.external_provider import freeze_json, thaw_json
from co_scientist.runtime.external_calls import prompt_hash
from co_scientist.runtime.lineage_workflow_contract import (
    LINEAGE_WORKFLOW_VERSION,
    freeze_lineage_workflow_contract,
)
from co_scientist.skills.loader import core_skill_directory


class ResearchGoal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    required_causal_chain: tuple[str, ...]
    required_outputs: tuple[str, ...]


class TournamentProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rating_policy_version: str = Field(min_length=1)
    evaluation_rules_id: str = Field(min_length=1)
    judge_profile_id: str = Field(min_length=1)
    match_mode: Literal["research", "paper_faithful_binary"]
    anchor_count: int = Field(ge=0)
    trueskill: TrueSkillConfig | None = None
    selection: UCBPairingPolicy | None = None

    @model_serializer(mode="wrap")
    def serialize_profile(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        document = handler(self)
        if self.trueskill is None:
            document.pop("trueskill", None)
        if self.selection is None:
            document.pop("selection", None)
        return cast(dict[str, Any], document)


class StopProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    minimum_matches: int = Field(ge=0)
    minimum_hypotheses: int = Field(ge=0)
    minimum_model_calls: int = Field(ge=0)
    top_k: int = Field(gt=0)
    top_k_stability_window: int = Field(gt=0)
    cluster_diversity_window: int = Field(gt=0)
    elo_plateau_window: int = Field(gt=0)
    require_anchor_plateau: bool
    require_top_k_stability: bool
    require_cluster_diversity_plateau: bool
    policy_version: Literal["anchor-convergence-v1", "research-no-anchor-v1"] = (
        "anchor-convergence-v1"
    )
    max_wall_seconds: int | None = Field(default=None, ge=0, strict=True)

    @model_serializer(mode="wrap")
    def serialize_profile(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        document = handler(self)
        if self.policy_version == "anchor-convergence-v1":
            document.pop("policy_version", None)
        if self.max_wall_seconds is None:
            document.pop("max_wall_seconds", None)
        return cast(dict[str, Any], document)


class DeepSeekGenerationProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_tokens: int = Field(default=32768, ge=1, le=384000, strict=True)
    thinking: Literal["enabled", "disabled"] = "enabled"
    reasoning_effort: Literal["low", "high", "max"] = "low"
    timeout_seconds: int = Field(default=300, ge=1, le=1800, strict=True)
    pilot_pricing: DeepSeekPilotPricing | None = None

    @model_validator(mode="after")
    def check_pilot_reserve(self) -> DeepSeekGenerationProfile:
        if (
            self.pilot_pricing is not None
            and self.pilot_pricing.reserve_usd_per_call
            < self.pilot_pricing.minimum_reserve(self.max_tokens)
        ):
            raise ValueError("pilot pricing reserve is below the per-call model bound")
        return self

    @model_serializer(mode="wrap")
    def serialize_generation(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        document: dict[str, Any] = handler(self)
        if self.pilot_pricing is None:
            document.pop("pilot_pricing", None)  # Preserve old manifest hashes.
        return document


class ProviderProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    llm: Literal["replay", "openai", "deepseek", "qwen", "gemini", "claude"]
    literature: Literal["replay_pubmed", "pubmed"]
    deepseek_generation: DeepSeekGenerationProfile | None = None


class EvolutionProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # Zero rounds preserves existing replay and frozen-run behavior.
    max_rounds: int = Field(default=0, ge=0, le=10, strict=True)
    max_children_per_round: int = Field(default=2, ge=1, le=10, strict=True)


class ReplayResourcesProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    llm_responses: str = Field(min_length=1)
    pubmed_search: str = Field(min_length=1)
    pubmed_summary: str = Field(min_length=1)


class MetaReviewProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: Literal["meta-review-loop-v1", "meta-review-loop-v2"] = "meta-review-loop-v1"
    max_rounds: int = Field(default=0, ge=0, le=10, strict=True)
    match_interval: int = Field(default=2, ge=1, le=100, strict=True)
    max_children_per_round: int = Field(default=1, ge=1, le=5, strict=True)

    @model_serializer(mode="wrap")
    def serialize_profile(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        document = handler(self)
        if self.contract_version == "meta-review-loop-v1":
            document.pop("contract_version", None)
        return document


class CoreProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    profile_id: str = Field(min_length=1)
    admission_policy_version: str = Field(min_length=1)
    ideation_core_boundary: Literal["2608-core-boundary-v1", "ideation-core-boundary-v2"] | None = None
    ideation_prerequisites: PrerequisitePolicyV1 | PrerequisiteExecutionPolicyV2 | None = None
    review_policy: ReviewPolicy
    literature_novelty_required: bool
    literature_search_queries: tuple[str, ...] = Field(default=(), max_length=5)
    scientific_context: bool = False
    research_protocol_version: Literal["research-v1", "research-v2"] | None = None
    anchor_policy: Literal["none", "benchmark"] | None = None
    anchor_set: Literal["lens-regeneration-v1"] | None = None
    claim_verification: ClaimVerificationPolicy | None = None
    claim_decomposition_output: ClaimDecompositionOutputPolicy | None = None
    claim_output_protocol: (
        Literal[
            "deepseek-claim-slots-v1",
            "deepseek-claim-source-units-v2",
            "deepseek-claim-source-units-v3",
            "deepseek-claim-source-units-v4",
            "claim-source-units-provider-json-v5",
        ]
        | None
    ) = None
    ranking_output_protocol: (
        Literal[
            "deepseek-strict-tool-v1",
            "deepseek-strict-tool-v2",
            "deepseek-strict-tool-v3",
            "deepseek-strict-tool-v4",
            "deepseek-result-json-v5",
        ]
        | None
    ) = None
    literature_content: Literal["metadata", "abstracts"] = "metadata"
    literature_sort: Literal["relevance", "pub_date"] | None = None
    evolution: EvolutionProfile = Field(default_factory=EvolutionProfile)
    population_evolution: PopulationEvolutionPolicy | None = None
    ideation_search: BaselineSearchPolicy | ShortSearchPolicy | None = None
    execution_runtime: EffectiveExecutionConfig | GenerationPerformanceConfig | SingleRootConfig | FullIdeationConfig | None = None
    query_planning_revision: Literal["pubmed-query-planning-v2", "pubmed-query-planning-v3", "pubmed-query-planning-v4"] | None = None
    source_review_revision: Literal["root-source-review-v2"] | None = None
    evolution_output_revision: Literal["evolution-per-parent-output-v1"] | None = None
    lineage_workflow_contract: Literal["source-evidence-binding-claim-lineage-v2"] | None = None
    dispatch_limits: DispatchLimits | None = None
    probe_execution_envelope: ProbeExecutionEnvelopeV1 | None = None
    meta_review: MetaReviewProfile = Field(default_factory=MetaReviewProfile)
    duplicate_likelihood_threshold: float = Field(ge=0.0, le=1.0)
    tournament: TournamentProfile
    stop: StopProfile
    budget: BudgetPolicy
    providers: ProviderProfile
    replay_resources: ReplayResourcesProfile | None = None

    @model_serializer(mode="wrap")
    def serialize_profile(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        document = handler(self)
        if self.query_planning_revision is None:
            document.pop("query_planning_revision", None)
        if self.source_review_revision is None:
            document.pop("source_review_revision", None)
        if self.evolution_output_revision is None:
            document.pop("evolution_output_revision", None)
        if self.ideation_core_boundary is None:
            document.pop("ideation_core_boundary", None)
        if self.ideation_prerequisites is None:
            document.pop("ideation_prerequisites", None)
        if self.research_protocol_version is None:
            # No new field in legacy canonical manifests or saved profile round-trips.
            document.pop("research_protocol_version", None)
        if self.anchor_policy is None:
            document.pop("anchor_policy", None)
        if self.anchor_set is None:
            document.pop("anchor_set", None)
        if self.claim_verification is None:
            document.pop("claim_verification", None)
        if self.claim_decomposition_output is None:
            document.pop("claim_decomposition_output", None)
        if self.claim_output_protocol is None:
            document.pop("claim_output_protocol", None)
        if self.population_evolution is None:
            document.pop("population_evolution", None)
        if self.ideation_search is None:
            document.pop("ideation_search", None)
        if self.execution_runtime is None:
            document.pop("execution_runtime", None)
        if self.lineage_workflow_contract is None:
            document.pop("lineage_workflow_contract", None)
        if self.dispatch_limits is None:
            document.pop("dispatch_limits", None)
        if self.probe_execution_envelope is None:
            document.pop("probe_execution_envelope", None)
        if self.ranking_output_protocol is None:
            document.pop("ranking_output_protocol", None)
        if self.meta_review == MetaReviewProfile():
            document.pop("meta_review", None)
        return cast(dict[str, Any], document)

    @field_validator("literature_search_queries")
    @classmethod
    def validate_search_queries(cls, queries: tuple[str, ...]) -> tuple[str, ...]:
        if any(not query.strip() for query in queries) or len(set(queries)) != len(queries):
            raise ValueError("literature queries must be nonblank and unique")
        return queries

    @model_validator(mode="after")
    def validate_abstract_mode(self) -> CoreProfile:
        if (self.query_planning_revision is not None or self.source_review_revision is not None) and not isinstance(
                self.ideation_prerequisites, PrerequisiteExecutionPolicyV2):
            raise ValueError("query-planning-v2 requires versioned prerequisite execution")
        performance = isinstance(self.execution_runtime, (GenerationPerformanceConfig, SingleRootConfig, FullIdeationConfig))
        expected_performance = (self.execution_runtime.version if isinstance(self.execution_runtime, FullIdeationConfig)
                                else MODE if isinstance(self.execution_runtime, SingleRootConfig) else PROFILE)
        if (self.profile_id == expected_performance) != performance:
            raise ValueError("performance profile requires exact independent execution version")
        if self.execution_runtime is not None:
            if (self.ideation_search is None or self.providers.deepseek_generation is not None
                    or self.dispatch_limits is not None or self.probe_execution_envelope is not None):
                raise ValueError("effective runtime requires independent baseline; no legacy overlays")
            if self.execution_runtime.scientific.search != self.ideation_search:
                raise ValueError("effective scientific profile differs from baseline search")
            e = self.execution_runtime.envelope
            derived = {"max_model_calls": e.max_model_dispatches, "max_input_tokens": e.max_input_tokens,
                       "max_output_tokens": e.max_output_tokens, "max_usd": e.max_reserved_usd,
                       "call_accounting_version": "model-only-v2"}
            for name in ("max_model_calls", "max_input_tokens", "max_output_tokens", "max_usd"):
                configured = getattr(self.budget, name)
                if configured is not None and configured != derived[name]:
                    raise ValueError("legacy budget overlay differs from effective envelope")
            if self.stop.max_wall_seconds is not None and self.stop.max_wall_seconds != e.max_wall_seconds:
                raise ValueError("legacy deadline overlay differs from effective envelope")
            object.__setattr__(self, "budget", self.budget.model_copy(update=derived))
            object.__setattr__(self, "stop", self.stop.model_copy(update={"max_wall_seconds": e.max_wall_seconds}))
        if self.ideation_search is not None and (
                not isinstance(self.ideation_prerequisites, PrerequisiteExecutionPolicyV2)
                or self.tournament.rating_policy_version != "trueskill_v1"
                or self.tournament.trueskill != TrueSkillConfig()):
            raise ValueError("baseline search requires exact functional prerequisites and TrueSkill prior")
        baseline_requested = self.profile_id.startswith("2608-ideation-baseline")
        batch2 = self.ideation_core_boundary == "ideation-core-boundary-v2"
        expected_boundary = "ideation-core-boundary-v2" if batch2 else BOUNDARY_VERSION
        if (batch2 != (self.ideation_prerequisites is not None)):
            raise ValueError("Batch 2 profile/reader revision mismatch")
        if (baseline_requested or self.ideation_core_boundary is not None) and (
                self.profile_id != (expected_performance if performance else BASELINE_PROFILE)
                or self.ideation_core_boundary != expected_boundary
                or self.admission_policy_version != expected_boundary
                or self.research_protocol_version != "research-v2"
                or not self.scientific_context
                or self.anchor_policy != "none"
                or self.literature_novelty_required
                or self.claim_verification is not None
                or self.claim_decomposition_output is not None
                or self.claim_output_protocol is not None
                or self.population_evolution is not None
                or self.lineage_workflow_contract is not None
                or self.evolution.max_rounds
                or self.meta_review.max_rounds
                or self.probe_execution_envelope is not None
        ):
            raise ValueError("baseline profile requires exact isolated core-boundary contract")
        if self.probe_execution_envelope is not None:
            probe = self.probe_execution_envelope
            scientific = self.dispatch_limits
            if (
                self.lineage_workflow_contract != LINEAGE_WORKFLOW_VERSION
                or self.research_protocol_version != "research-v2"
                or scientific is None
                or scientific.pricing != probe.pricing
                or scientific.max_model_calls < probe.max_total_model_calls
                or scientific.max_input_tokens < probe.max_input_tokens
                or scientific.max_output_tokens < probe.max_output_tokens
                or scientific.max_usd < probe.max_reserved_usd
                or scientific.max_wall_seconds < probe.max_wall_seconds
                or scientific.output_tokens_per_call != probe.output_tokens_per_call
                or self.providers.llm != "deepseek"
            ):
                raise ValueError("probe envelope must only restrict a matching scientific Run")
        if self.dispatch_limits is not None:
            limits = self.dispatch_limits
            generation = self.providers.deepseek_generation
            if (
                self.providers.llm != "deepseek"
                or generation is None
                or generation.pilot_pricing != limits.pricing
                or generation.max_tokens != limits.output_tokens_per_call
                or self.budget.max_model_calls != limits.max_model_calls
                or self.budget.call_accounting_version != "model-only-v2"
                or self.budget.max_usd != limits.max_usd
                or self.budget.max_input_tokens != limits.max_input_tokens
                or self.budget.max_output_tokens != limits.max_output_tokens
                or self.stop.max_wall_seconds != limits.max_wall_seconds
            ):
                raise ValueError("dispatch envelope must match normal Run provider/budget/stop")
        elif (
            self.providers.deepseek_generation is not None
            and self.providers.deepseek_generation.pilot_pricing is not None
            and self.providers.deepseek_generation.pilot_pricing.input_token_limit is not None
        ):
            raise ValueError("bounded pricing requires enforced dispatch_limits")
        bayesian = self.tournament.rating_policy_version == "trueskill_v1"
        if bayesian != (
            self.tournament.trueskill is not None and self.tournament.selection is not None
        ):
            raise ValueError("trueskill_v1 requires separate frozen rating and selection policies")
        if bayesian and self.research_protocol_version != "research-v2":
            raise ValueError("trueskill_v1 is only available for new Research v2 runs")
        if not bayesian and (
            self.tournament.trueskill is not None or self.tournament.selection is not None
        ):
            raise ValueError("Bayesian policy fields require trueskill_v1")
        if self.ranking_output_protocol and (
            self.research_protocol_version not in {"research-v1", "research-v2"}
            or self.providers.llm != "deepseek"
        ):
            raise ValueError("ranking_output_protocol requires DeepSeek and research-v1")
        if self.claim_output_protocol and (
            self.research_protocol_version != "research-v2"
            or self.providers.llm != "deepseek"
            or self.claim_verification is None
            or self.claim_decomposition_output is None
            or self.claim_verification.max_queries_per_claim < 4
        ):
            raise ValueError("claim_output_protocol requires bounded DeepSeek Research v2 claims")
        if self.meta_review.max_rounds and (
            self.research_protocol_version not in {"research-v1", "research-v2"}
            or not self.evolution.max_rounds
        ):
            raise ValueError("meta_review requires research-v1 and an evolution round allowance")
        if self.meta_review.max_rounds and (
            self.budget.max_model_calls is None or self.budget.max_matches is None
        ):
            raise ValueError("meta_review requires finite model-call and match budgets")
        if self.research_protocol_version and not self.scientific_context:
            raise ValueError("research_protocol_version requires scientific_context")
        if self.research_protocol_version and self.tournament.match_mode != "research":
            raise ValueError("research-v1 supports research match mode, not binary benchmark")
        if self.research_protocol_version == "research-v2":
            if self.lineage_workflow_contract is not None and (
                self.lineage_workflow_contract != LINEAGE_WORKFLOW_VERSION
                or self.claim_verification is None
                or self.population_evolution is None
                or self.claim_decomposition_output is None
            ):
                raise ValueError(
                    "lineage workflow requires Research v2 claim verification, bounded "
                    "decomposition and population evolution"
                )
            if self.claim_decomposition_output is not None and (
                self.claim_verification is None
                or self.claim_decomposition_output.max_total_claims
                < self.claim_verification.max_critical_claims_per_hypothesis
            ):
                raise ValueError("bounded claim output requires compatible claim verification")
            if self.population_evolution is not None:
                if not bayesian or self.claim_verification is None:
                    raise ValueError(
                        "population evolution requires TrueSkill and claim verification"
                    )
                if "full_review" not in {
                    stage.value for stage in self.review_policy.required_before_admission
                }:
                    raise ValueError("population evolution requires full review before admission")
                if self.evolution.max_rounds or self.meta_review.max_rounds:
                    raise ValueError(
                        "population evolution cannot share legacy repair/feedback rounds"
                    )
                if (
                    self.budget.hypothesis_limit_policy != "capacity-v2"
                    or self.budget.max_hypotheses is None
                    or self.budget.max_hypotheses < self.population_evolution.max_total_hypotheses
                ):
                    raise ValueError("population evolution needs capacity-v2 hypothesis budget")
            if self.claim_verification is not None and (
                self.providers.literature not in {"pubmed", "replay_pubmed"}
                or self.literature_novelty_required
            ):
                raise ValueError("claim verification requires PubMed and separate prior-art policy")
            if self.anchor_policy is None:
                raise ValueError("research-v2 requires an explicit anchor_policy")
            if self.anchor_policy == "none":
                if (
                    self.anchor_set is not None
                    or self.tournament.anchor_count != 0
                    or self.stop.policy_version != "research-no-anchor-v1"
                    or self.stop.require_anchor_plateau
                ):
                    raise ValueError(
                        "research-v2 none requires zero anchors and no-anchor stopping"
                    )
            elif (
                self.anchor_set != "lens-regeneration-v1"
                or self.tournament.anchor_count != 2
                or self.stop.policy_version != "anchor-convergence-v1"
            ):
                raise ValueError("research-v2 benchmark requires the lens-regeneration-v1 set")
            if self.budget.max_model_calls is None or self.budget.max_matches is None:
                raise ValueError("research-v2 requires finite model-call and match budgets")
        elif (
            self.anchor_policy is not None
            or self.anchor_set is not None
            or self.claim_verification is not None
            or self.claim_decomposition_output is not None
            or self.claim_output_protocol is not None
            or self.population_evolution is not None
            or self.lineage_workflow_contract is not None
            or self.stop.policy_version != "anchor-convergence-v1"
            or self.stop.max_wall_seconds is not None
            or self.tournament.anchor_count < 1
        ):
            raise ValueError("legacy and research-v1 require the original anchor contract")
        if self.evolution.max_rounds and not self.scientific_context:
            raise ValueError("evolution requires scientific_context")
        if self.literature_content == "abstracts" and (
            not self.scientific_context or self.providers.literature != "pubmed"
        ):
            raise ValueError("abstract mode requires scientific_context and live PubMed")
        return self


class ResolvedRunConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    goal: ResearchGoal
    profile: CoreProfile
    manifest: Mapping[str, Any]
    manifest_hash: str
    provider_id: str

    @field_validator("manifest")
    @classmethod
    def freeze_manifest(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        return cast(Mapping[str, Any], freeze_json(value))

    @field_serializer("manifest", when_used="json")
    def serialize_manifest(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], thaw_json(value))


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _identity(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _load_yaml(path: Path, *, label: str) -> Mapping[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise ValueError(f"invalid {label} YAML: {path}") from error
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} YAML must contain an object: {path}")
    return cast(Mapping[str, Any], value)


def _resource(
    path_value: str | None,
    *,
    environment_key: str,
    kind: str,
    relative_to: Path | None = None,
) -> dict[str, str]:
    if not path_value:
        raise ValueError(f"{environment_key} is required")
    path = Path(path_value).expanduser()
    if not path.is_absolute() and relative_to is not None:
        path = relative_to / path
    path = path.resolve()
    if not path.is_file():
        raise ValueError(f"{environment_key} does not name a file: {path}")
    body = path.read_bytes()
    return {
        "kind": kind,
        "path": str(path),
        "sha256": "sha256:" + hashlib.sha256(body).hexdigest(),
        "byte_length": str(len(body)),
    }


def _validate_pubmed_replay(path: Path, *, operation: Literal["search", "summary"]) -> None:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, Mapping):
            raise TypeError("envelope is not an object")
        result = document["esearchresult" if operation == "search" else "result"]
        if not isinstance(result, Mapping):
            raise TypeError("result is not an object")
        ids = result["idlist" if operation == "search" else "uids"]
        if not isinstance(ids, list) or any(not isinstance(item, str) or not item for item in ids):
            raise TypeError("identifiers are malformed")
        if operation == "summary":
            for pmid in ids:
                record = result.get(pmid)
                if not isinstance(record, Mapping):
                    raise TypeError("summary record is missing")
                title = record.get("title")
                authors = record.get("authors", [])
                if (
                    not isinstance(title, str)
                    or not title
                    or not isinstance(authors, list)
                    or any(
                        not isinstance(author, Mapping)
                        or not isinstance(author.get("name"), str)
                        or not author["name"]
                        for author in authors
                    )
                ):
                    raise TypeError("summary record is malformed")
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        label = "SEARCH" if operation == "search" else "SUMMARY"
        raise ValueError(f"CO_SCIENTIST_REPLAY_PUBMED_{label} is malformed") from error


def resolve_run_config(
    *,
    goal_file: Path,
    profile_file: Path,
    provider: Literal["replay", "openai", "deepseek", "qwen", "gemini", "claude"],
    environment: Mapping[str, str],
) -> ResolvedRunConfig:
    """Resolve all execution inputs and fail before any Run can be created."""

    if provider not in {"replay", "openai", "deepseek", "qwen", "gemini", "claude"}:
        raise ValueError(f"unsupported provider: {provider}")
    goal = ResearchGoal.model_validate(_load_yaml(goal_file, label="goal"))
    profile = CoreProfile.model_validate(_load_yaml(profile_file, label="profile"))
    if profile.research_protocol_version == "research-v2" and not profile.literature_search_queries:
        # Freeze the initial query before the Run starts; no topic-specific runtime fallback.
        query = " ".join(goal.title.split())
        if not query:
            raise ValueError("research-v2 requires a nonblank goal-derived initial query")
        profile = profile.model_copy(update={"literature_search_queries": (query,)})
    if provider != profile.providers.llm:
        raise ValueError(
            f"selected provider {provider!r} does not match profile provider "
            f"{profile.providers.llm!r}"
        )
    provider_configuration: dict[str, Any]
    replay_resources: list[dict[str, str]] = []
    if provider == "replay":
        replay_profile = profile.replay_resources
        llm_resource = _resource(
            (
                replay_profile.llm_responses
                if replay_profile is not None
                else environment.get("CO_SCIENTIST_REPLAY_RESPONSES")
            ),
            environment_key="CO_SCIENTIST_REPLAY_RESPONSES",
            kind="llm_responses",
            relative_to=profile_file.parent if replay_profile is not None else None,
        )
        replay_resources.append(llm_resource)
        try:
            replay_document = json.loads(Path(llm_resource["path"]).read_text(encoding="utf-8"))
            replay_model = replay_document["model"]
            replay_version = replay_document["replay_version"]
            responses = replay_document["responses"]
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            raise ValueError("CO_SCIENTIST_REPLAY_RESPONSES is malformed") from error
        if replay_version != 1 or not isinstance(replay_model, str) or not replay_model:
            raise ValueError("CO_SCIENTIST_REPLAY_RESPONSES is malformed")
        if not isinstance(responses, list) or not responses:
            raise ValueError("CO_SCIENTIST_REPLAY_RESPONSES has no responses")
        try:
            from co_scientist.adapters.llm.replay import ReplayLLMProvider

            ReplayLLMProvider.from_file(Path(llm_resource["path"]))
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("CO_SCIENTIST_REPLAY_RESPONSES is malformed") from error
        provider_configuration = {"provider": "replay", "model": replay_model}
    else:
        from co_scientist.adapters.llm.multi_provider import KEY_NAMES

        model_key = f"CO_SCIENTIST_{provider.upper()}_MODEL"
        key_name = KEY_NAMES[provider]
        model = environment.get(model_key)
        api_key = environment.get(key_name)
        missing = [
            key
            for key, value in (
                (key_name, api_key),
                (model_key, model),
            )
            if not value
        ]
        if missing:
            raise ValueError(f"{', '.join(missing)} is required")
        provider_configuration = {"provider": provider, "model": model}
        if provider == "deepseek" and profile.providers.deepseek_generation is not None:
            pricing = profile.providers.deepseek_generation.pilot_pricing
            if pricing is not None and pricing.model != model:
                raise ValueError("pilot pricing model differs from frozen DeepSeek model")
            provider_configuration["generation"] = profile.providers.deepseek_generation.model_dump(
                mode="json"
            )
        elif provider != "deepseek" and profile.providers.deepseek_generation is not None:
            raise ValueError("deepseek_generation requires the deepseek provider")
    if profile.providers.literature == "replay_pubmed":
        replay_profile = profile.replay_resources
        search_resource = _resource(
            (
                replay_profile.pubmed_search
                if replay_profile is not None
                else environment.get("CO_SCIENTIST_REPLAY_PUBMED_SEARCH")
            ),
            environment_key="CO_SCIENTIST_REPLAY_PUBMED_SEARCH",
            kind="pubmed_search",
            relative_to=profile_file.parent if replay_profile is not None else None,
        )
        summary_resource = _resource(
            (
                replay_profile.pubmed_summary
                if replay_profile is not None
                else environment.get("CO_SCIENTIST_REPLAY_PUBMED_SUMMARY")
            ),
            environment_key="CO_SCIENTIST_REPLAY_PUBMED_SUMMARY",
            kind="pubmed_summary",
            relative_to=profile_file.parent if replay_profile is not None else None,
        )
        _validate_pubmed_replay(Path(search_resource["path"]), operation="search")
        _validate_pubmed_replay(Path(summary_resource["path"]), operation="summary")
        replay_resources.extend((search_resource, summary_resource))
    else:
        provider_configuration["pubmed"] = {
            "tool": "co-scientist-core",
            "email_configured": bool(environment.get("CO_SCIENTIST_PUBMED_EMAIL")),
        }

    goal_document = goal.model_dump(mode="json")
    profile_document = profile.model_dump(mode="json")
    protocol = (
        research_protocol_v2(
            claim_verification=profile.claim_verification is not None,
            bayesian_rating=profile.tournament.rating_policy_version == "trueskill_v1",
            population_evolution=profile.population_evolution is not None,
        )
        if profile.research_protocol_version == "research-v2"
        else research_protocol_v1()
        if profile.research_protocol_version == "research-v1"
        else None
    )
    ranking_output = (
        strict_ranking_contract(profile.ranking_output_protocol)
        if profile.ranking_output_protocol
        else None
    )
    if ranking_output is not None:
        if provider != "deepseek":
            raise ValueError("ranking_output_protocol requires the deepseek provider")
        provider_configuration["ranking_output_protocol"] = profile.ranking_output_protocol
    if protocol is not None and (
        not goal.required_causal_chain
        or not goal.required_outputs
        or any(
            not value.strip()
            for value in (
                goal.title,
                goal.goal,
                *goal.required_causal_chain,
                *goal.required_outputs,
            )
        )
    ):
        raise ValueError("research-v1 requires a complete research goal")
    tournament = profile.tournament
    ranking_prompt = (core_skill_directory("ranking") / "prompts/system.md").read_text(
        encoding="utf-8"
    )
    tournament_contract = {
        "epoch_id": "epoch-1",
        "research_plan_version": 1,
        "evaluation_rules_hash": _identity(
            {
                "evaluation_rules_id": tournament.evaluation_rules_id,
                "match_mode": tournament.match_mode,
            }
        ),
        "ranking_prompt_hash": prompt_hash(ranking_prompt),
        "judge_profile_hash": _identity({"judge_profile_id": tournament.judge_profile_id}),
        "rating_policy_version": tournament.rating_policy_version,
        "admission_policy_version": profile.admission_policy_version,
        "anchor_set_id": (None if profile.anchor_policy == "none" else "core-preview-anchors-v1"),
    }
    if tournament.trueskill is not None:
        tournament_contract["rating_policy_config"] = tournament.trueskill.model_dump(mode="json")
    if protocol is not None:
        rules: dict[str, Any] = {
            "evaluation_rules_id": tournament.evaluation_rules_id,
            "match_mode": tournament.match_mode,
            "research_protocol_hash": protocol_hash(protocol),
        }
        if profile.meta_review.max_rounds:
            rules["feedback_contract_hash"] = protocol_hash(
                feedback_contract(profile.meta_review.contract_version)
            )
        if ranking_output is not None:
            rules["ranking_output_contract_hash"] = protocol_hash(ranking_output)
        tournament_contract["evaluation_rules_hash"] = _identity(rules)
        tournament_contract["judge_profile_hash"] = _identity(
            {
                "judge_profile_id": tournament.judge_profile_id,
                "provider_configuration": provider_configuration,
            }
        )
    admission_policy = {
        "version": profile.admission_policy_version,
        "review_policy": profile.review_policy.model_dump(mode="json"),
        "literature_novelty_required": profile.literature_novelty_required,
        "duplicate_likelihood_threshold": profile.duplicate_likelihood_threshold,
    }
    manifest = {
        "execution_contract_version": 4
        if profile.research_protocol_version == "research-v2"
        else 3,
        "goal": goal_document,
        "profile": profile_document,
        "profile_id": profile.profile_id,
        "budget": profile.budget.model_dump(mode="json"),
        "admission_policy_version": profile.admission_policy_version,
        "admission_policies": {profile.admission_policy_version: admission_policy},
        "providers": {
            "llm": provider,
            "literature": profile.providers.literature,
        },
        "provider_configuration": provider_configuration,
        "tournament_contract": tournament_contract,
        "anchor_sets": (
            []
            if profile.anchor_policy == "none"
            else core_preview_anchor_sets(tournament.anchor_count)
        ),
        "replay_resources": replay_resources,
    }
    if protocol is not None:
        manifest["research_protocol"] = protocol
        manifest["research_protocol_hash"] = protocol_hash(protocol)
    if profile.meta_review.max_rounds:
        manifest["feedback_contract"] = feedback_contract(profile.meta_review.contract_version)
        manifest["feedback_contract_hash"] = protocol_hash(manifest["feedback_contract"])
    if ranking_output is not None:
        manifest["ranking_output_contract"] = ranking_output
        manifest["ranking_output_contract_hash"] = protocol_hash(ranking_output)
    if profile.lineage_workflow_contract is not None:
        lineage_contract = freeze_lineage_workflow_contract()
        manifest["lineage_workflow_contract"] = lineage_contract
        manifest["lineage_workflow_contract_hash"] = protocol_hash(lineage_contract)
    if profile.probe_execution_envelope is not None:
        envelope = profile.probe_execution_envelope.model_dump(mode="json")
        manifest["probe_execution_envelope"] = envelope
        manifest["probe_execution_envelope_hash"] = protocol_hash(envelope)
    if profile.ideation_core_boundary is not None:
        if profile.ideation_prerequisites is not None:
            policy = profile.ideation_prerequisites
            parameters = policy.policy if isinstance(policy, PrerequisiteExecutionPolicyV2) else policy
            if (parameters.capability.provider != provider
                    or parameters.capability.model != provider_configuration["model"]):
                raise ValueError("Batch 2 pinned provider/model capability mismatch")
            manifest["ideation_core_contract"] = (
                batch2_execution_boundary_contract() if isinstance(policy, PrerequisiteExecutionPolicyV2)
                else batch2_boundary_contract())
            manifest["ideation_prerequisite_contract"] = policy.model_dump(mode="json")
            manifest["ideation_prerequisite_contract_hash"] = protocol_hash(
                manifest["ideation_prerequisite_contract"])
            manifest["ideation_prerequisite_protocol"] = (
                ideation_prerequisite_protocol_v2() if isinstance(policy, PrerequisiteExecutionPolicyV2)
                else ideation_prerequisite_protocol_v1())
            manifest["ideation_prerequisite_protocol_hash"] = protocol_hash(
                manifest["ideation_prerequisite_protocol"])
            manifest["profile_file_hash"] = "sha256:" + hashlib.sha256(
                profile_file.read_bytes()).hexdigest()
            from co_scientist.skills.loader import BASELINE_SKILL_CONTRACTS, load_skill

            manifest["ideation_skill_contracts"] = [
                {"phase": phase, "manifest": load_skill(core_skill_directory(sid),
                    skill_version=version, phase=phase).model_dump(mode="json"),
                 "schema_version": 1,
                 "prompt_hash": prompt_hash((core_skill_directory(sid) / contract.prompt_path)
                                            .read_text(encoding="utf-8"))}
                for (sid, version, phase), contract in BASELINE_SKILL_CONTRACTS.items()
            ]
            manifest["ideation_skill_contracts_hash"] = protocol_hash(
                manifest["ideation_skill_contracts"])
            if profile.query_planning_revision is not None:
                contract = load_skill(core_skill_directory("root_literature_review"),
                    skill_version={"pubmed-query-planning-v2": "0.2.0",
                        "pubmed-query-planning-v3": "0.3.0",
                        "pubmed-query-planning-v4": "0.4.0"}[profile.query_planning_revision],
                    phase="QUERY_PLAN_V1")
                manifest["ideation_skill_contracts"] = [c for c in cast(list[dict[str, Any]], manifest["ideation_skill_contracts"])
                    if c["phase"] != "QUERY_PLAN_V1"] + [{"phase": "QUERY_PLAN_V1",
                    "manifest": contract.model_dump(mode="json"), "schema_version": 1,
                    "prompt_hash": prompt_hash((core_skill_directory(contract.id)
                        / contract.prompt_path).read_text())}]
                manifest["ideation_skill_contracts_hash"] = protocol_hash(manifest["ideation_skill_contracts"])
            if profile.source_review_revision == "root-source-review-v2":
                contract = load_skill(core_skill_directory("root_literature_review"),
                    skill_version="0.4.0", phase="SOURCE_REVIEW_V1")
                manifest["ideation_skill_contracts"] = [c for c in cast(list[dict[str, Any]], manifest["ideation_skill_contracts"])
                    if c["phase"] != "SOURCE_REVIEW_V1"] + [{"phase": "SOURCE_REVIEW_V1",
                    "manifest": contract.model_dump(mode="json"), "schema_version": 1,
                    "prompt_hash": prompt_hash((core_skill_directory(contract.id)
                        / contract.prompt_path).read_text())}]
                manifest["ideation_skill_contracts_hash"] = protocol_hash(manifest["ideation_skill_contracts"])
            if profile.profile_id in {PROFILE, MODE, FULL_MODE, G3_MODE}:
                from co_scientist.skills.loader import PERFORMANCE_SKILL

                contract = load_skill(core_skill_directory("generation"), skill_version="0.4.0")
                manifest["ideation_skill_contracts"] = [c for c in cast(list[dict[str, Any]], manifest["ideation_skill_contracts"])
                    if c["manifest"]["id"] != "generation"] + [{"phase": None,
                    "manifest": contract.model_dump(mode="json"), "schema_version": 1,
                    "prompt_hash": prompt_hash((core_skill_directory("generation") / PERFORMANCE_SKILL.prompt_path).read_text())}]
                manifest["ideation_skill_contracts_hash"] = protocol_hash(manifest["ideation_skill_contracts"])
        else:
            manifest["ideation_core_contract"] = boundary_contract()
        if profile.profile_id in {PROFILE, MODE, FULL_MODE, G3_MODE}:
            manifest["ideation_core_contract"] = {**cast(dict[str, Any], manifest["ideation_core_contract"]),
                "profile_id": profile.profile_id, "generation_method": PROFILE}
        manifest["ideation_core_contract_hash"] = protocol_hash(manifest["ideation_core_contract"])
        baseline_enabled(manifest)
    if profile.ideation_search is not None:
        from co_scientist.skills.loader import BASELINE_SEARCH_SKILL_CONTRACTS, load_skill

        manifest["ideation_search_contract"] = profile.ideation_search.model_dump(mode="json")
        manifest["ideation_search_contract_hash"] = protocol_hash(manifest["ideation_search_contract"])
        manifest["ideation_search_skills"] = [
            {"phase": phase, "manifest": load_skill(core_skill_directory(sid),
                skill_version=version, phase=phase).model_dump(mode="json"),
             "schema_version": 1,
             "prompt_hash": prompt_hash((core_skill_directory(sid) / contract.prompt_path)
                                        .read_text(encoding="utf-8"))}
            for (sid, version, phase), contract in BASELINE_SEARCH_SKILL_CONTRACTS.items()
        ]
        manifest["ideation_search_skills_hash"] = protocol_hash(manifest["ideation_search_skills"])
    if profile.execution_runtime is not None:
        document = profile.execution_runtime.model_dump(mode="json")
        manifest["effective_execution_config"] = document
        manifest["effective_execution_config_hash"] = protocol_hash(document)
    if profile.evolution_output_revision is not None:
        from co_scientist.domain.ideation_prerequisites import evolution_output_contract

        if not isinstance(profile.execution_runtime, FullIdeationConfig) or profile.execution_runtime.continuous_policy is None:
            raise ValueError("Evolution output revision requires explicit continuous opt-in runtime")
        manifest["evolution_output_contract"] = evolution_output_contract()
        manifest["evolution_output_contract_hash"] = protocol_hash(manifest["evolution_output_contract"])
    return ResolvedRunConfig(
        goal=goal,
        profile=profile,
        manifest=manifest,
        manifest_hash=_identity(manifest),
        provider_id=provider,
    )
