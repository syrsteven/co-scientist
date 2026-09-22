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
from co_scientist.domain.budget import BudgetPolicy
from co_scientist.domain.ranking_output import strict_ranking_contract
from co_scientist.domain.research_feedback import feedback_contract
from co_scientist.domain.research_protocol import protocol_hash, research_protocol_v1
from co_scientist.domain.review import ReviewPolicy
from co_scientist.ports.external_provider import freeze_json, thaw_json
from co_scientist.runtime.external_calls import prompt_hash
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
    anchor_count: int = Field(gt=0)


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


class DeepSeekGenerationProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_tokens: int = Field(default=32768, ge=1, le=384000, strict=True)
    thinking: Literal["enabled", "disabled"] = "enabled"
    reasoning_effort: Literal["low", "high", "max"] = "low"
    timeout_seconds: int = Field(default=300, ge=1, le=1800, strict=True)


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
    review_policy: ReviewPolicy
    literature_novelty_required: bool
    literature_search_queries: tuple[str, ...] = Field(default=(), max_length=5)
    scientific_context: bool = False
    research_protocol_version: Literal["research-v1"] | None = None
    ranking_output_protocol: Literal["deepseek-strict-tool-v1", "deepseek-strict-tool-v2"] | None = None
    literature_content: Literal["metadata", "abstracts"] = "metadata"
    literature_sort: Literal["relevance", "pub_date"] | None = None
    evolution: EvolutionProfile = Field(default_factory=EvolutionProfile)
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
        if self.research_protocol_version is None:
            # No new field in legacy canonical manifests or saved profile round-trips.
            document.pop("research_protocol_version", None)
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
        if self.ranking_output_protocol and (
            self.research_protocol_version != "research-v1" or self.providers.llm != "deepseek"
        ):
            raise ValueError("ranking_output_protocol requires DeepSeek and research-v1")
        if self.meta_review.max_rounds and (
            self.research_protocol_version != "research-v1" or not self.evolution.max_rounds
        ):
            raise ValueError("meta_review requires research-v1 and an evolution round allowance")
        if self.meta_review.max_rounds and (self.budget.max_model_calls is None or self.budget.max_matches is None):
            raise ValueError("meta_review requires finite model-call and match budgets")
        if self.research_protocol_version and not self.scientific_context:
            raise ValueError("research_protocol_version requires scientific_context")
        if self.research_protocol_version and self.tournament.match_mode != "research":
            raise ValueError("research-v1 supports research match mode, not binary benchmark")
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
        if (
            not isinstance(ids, list)
            or any(not isinstance(item, str) or not item for item in ids)
        ):
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
            provider_configuration["generation"] = (
                profile.providers.deepseek_generation.model_dump(mode="json")
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
    protocol = research_protocol_v1() if profile.research_protocol_version else None
    ranking_output = (
        strict_ranking_contract(profile.ranking_output_protocol) if profile.ranking_output_protocol else None
    )
    if ranking_output is not None:
        if provider != "deepseek":
            raise ValueError("ranking_output_protocol requires the deepseek provider")
        provider_configuration["ranking_output_protocol"] = profile.ranking_output_protocol
    if protocol is not None and (not goal.required_causal_chain or not goal.required_outputs
          or any(not value.strip() for value in
                 (goal.title, goal.goal, *goal.required_causal_chain, *goal.required_outputs))):
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
        "judge_profile_hash": _identity(
            {"judge_profile_id": tournament.judge_profile_id}
        ),
        "rating_policy_version": tournament.rating_policy_version,
        "admission_policy_version": profile.admission_policy_version,
        "anchor_set_id": "core-preview-anchors-v1",
    }
    if protocol is not None:
        rules: dict[str, Any] = {
            "evaluation_rules_id": tournament.evaluation_rules_id,
            "match_mode": tournament.match_mode,
            "research_protocol_hash": protocol_hash(protocol),
        }
        if profile.meta_review.max_rounds:
            rules["feedback_contract_hash"] = protocol_hash(feedback_contract(profile.meta_review.contract_version))
        if ranking_output is not None:
            rules["ranking_output_contract_hash"] = protocol_hash(ranking_output)
        tournament_contract["evaluation_rules_hash"] = _identity(rules)
        tournament_contract["judge_profile_hash"] = _identity({
            "judge_profile_id": tournament.judge_profile_id,
            "provider_configuration": provider_configuration,
        })
    admission_policy = {
        "version": profile.admission_policy_version,
        "review_policy": profile.review_policy.model_dump(mode="json"),
        "literature_novelty_required": profile.literature_novelty_required,
        "duplicate_likelihood_threshold": profile.duplicate_likelihood_threshold,
    }
    manifest = {
        "execution_contract_version": 3,
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
        "anchor_sets": core_preview_anchor_sets(tournament.anchor_count),
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
    return ResolvedRunConfig(
        goal=goal,
        profile=profile,
        manifest=manifest,
        manifest_hash=_identity(manifest),
        provider_id=provider,
    )
