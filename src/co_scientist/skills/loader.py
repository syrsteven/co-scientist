"""Load and validate project runtime skill manifests."""

from collections.abc import Mapping
from importlib.resources import files
from pathlib import Path
from types import MappingProxyType
from typing import Literal

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict

from co_scientist.agents.payloads import (
    CoreOutputSchemaId,
    output_schema_version,
    resolve_output_schema,
)


class SkillManifest(BaseModel):
    """Immutable capability boundary for one worker skill."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    agent_type: Literal[
        "generation",
        "reflection",
        "ranking",
        "proximity",
        "evolution",
        "population_evolution",
        "meta_review",
        "claim_decomposition",
        "claim_search_plan",
        "claim_verification",
        "directive_ethics",
        "root_literature_review",
        "candidate_ethics",
        "root_retrieval",
    ]
    version: str
    prompt_path: str
    input_schema: str
    output_schema: CoreOutputSchemaId
    allowed_tools: tuple[str, ...] = ()
    allowed_capabilities: tuple[Literal["return_agent_result"], ...]


CORE_SKILL_CONTRACTS: Mapping[str, SkillManifest] = MappingProxyType(
    {
        "generation": SkillManifest(
            id="generation",
            agent_type="generation",
            version="0.2.0",
            prompt_path="prompts/system.md",
            input_schema="GenerationInputV1",
            output_schema="GenerationResultV1",
            allowed_tools=(),
            allowed_capabilities=("return_agent_result",),
        ),
        "reflection": SkillManifest(
            id="reflection",
            agent_type="reflection",
            version="0.2.0",
            prompt_path="prompts/system.md",
            input_schema="ReflectionInputV1",
            output_schema="ReflectionResultV1",
            allowed_tools=("literature_search",),
            allowed_capabilities=("return_agent_result",),
        ),
        "ranking": SkillManifest(
            id="ranking",
            agent_type="ranking",
            version="0.2.0",
            prompt_path="prompts/system.md",
            input_schema="RankingInputV1",
            output_schema="RankingResultV1",
            allowed_tools=(),
            allowed_capabilities=("return_agent_result",),
        ),
        "proximity": SkillManifest(
            id="proximity",
            agent_type="proximity",
            version="0.2.0",
            prompt_path="prompts/system.md",
            input_schema="ProximityInputV1",
            output_schema="ProximityResultV1",
            allowed_tools=(),
            allowed_capabilities=("return_agent_result",),
        ),
        "evolution": SkillManifest(
            id="evolution",
            agent_type="evolution",
            version="0.2.0",
            prompt_path="prompts/system.md",
            input_schema="EvolutionInputV1",
            output_schema="EvolutionResultV1",
            allowed_tools=(),
            allowed_capabilities=("return_agent_result",),
        ),
        "population_evolution": SkillManifest(
            id="population_evolution", agent_type="population_evolution",
            version="0.1.0", prompt_path="prompts/system.md",
            input_schema="PopulationEvolutionInputV1",
            output_schema="PopulationEvolutionResultV1", allowed_tools=(),
            allowed_capabilities=("return_agent_result",),
        ),
        "meta_review": SkillManifest(
            id="meta_review",
            agent_type="meta_review",
            version="0.2.0",
            prompt_path="prompts/system.md",
            input_schema="MetaReviewInputV1",
            output_schema="MetaReviewResultV1",
            allowed_tools=(),
            allowed_capabilities=("return_agent_result",),
        ),
        "claim_decomposition": SkillManifest(
            id="claim_decomposition", agent_type="claim_decomposition", version="0.1.0",
            prompt_path="prompts/system.md", input_schema="ClaimDecompositionInputV1",
            output_schema="ClaimDecompositionResultV1", allowed_tools=(),
            allowed_capabilities=("return_agent_result",),
        ),
        "claim_search_plan": SkillManifest(
            id="claim_search_plan", agent_type="claim_search_plan", version="0.1.0",
            prompt_path="prompts/system.md", input_schema="ClaimSearchPlanInputV1",
            output_schema="ClaimSearchPlanResultV1", allowed_tools=(),
            allowed_capabilities=("return_agent_result",),
        ),
        "claim_verification": SkillManifest(
            id="claim_verification", agent_type="claim_verification", version="0.1.0",
            prompt_path="prompts/system.md", input_schema="ClaimVerificationInputV1",
            output_schema="ClaimVerificationResultV1", allowed_tools=(),
            allowed_capabilities=("return_agent_result",),
        ),
    }
)

CORE_SKILL_CONTRACTS_V2: Mapping[str, SkillManifest] = MappingProxyType({
    "population_evolution": SkillManifest(
        id="population_evolution", agent_type="population_evolution", version="0.2.0",
        prompt_path="prompts/system-v2.md", input_schema="PopulationEvolutionInputV2",
        output_schema="PopulationEvolutionResultV2", allowed_tools=(),
        allowed_capabilities=("return_agent_result",),
    ),
    "claim_decomposition": SkillManifest(
        id="claim_decomposition", agent_type="claim_decomposition", version="0.2.0",
        prompt_path="prompts/system-v2.md", input_schema="ClaimDecompositionInputV2",
        output_schema="ClaimDecompositionResultV2", allowed_tools=(),
        allowed_capabilities=("return_agent_result",),
    ),
    "claim_verification": SkillManifest(
        id="claim_verification", agent_type="claim_verification", version="0.2.0",
        prompt_path="prompts/system-v2.md", input_schema="ClaimVerificationInputV2",
        output_schema="ClaimVerificationResultV2", allowed_tools=(),
        allowed_capabilities=("return_agent_result",),
    ),
})

CORE_SKILL_CONTRACTS_V3: Mapping[str, SkillManifest] = MappingProxyType({
    "claim_decomposition": SkillManifest(
        id="claim_decomposition", agent_type="claim_decomposition", version="0.3.0",
        prompt_path="prompts/system-v3.md", input_schema="ClaimDecompositionInputV3",
        output_schema="ClaimDecompositionResultV3", allowed_tools=(),
        allowed_capabilities=("return_agent_result",),
    ),
})


BASELINE_SKILL_CONTRACTS: Mapping[tuple[str, str, str | None], SkillManifest] = MappingProxyType({
    ("directive_ethics", "0.1.0", None): SkillManifest(
        id="directive_ethics", agent_type="directive_ethics", version="0.1.0",
        prompt_path="prompts/system.md", input_schema="DirectiveEthicsInputV1",
        output_schema="DirectiveEthicsResultV1", allowed_capabilities=("return_agent_result",)),
    ("candidate_ethics", "0.1.0", None): SkillManifest(
        id="candidate_ethics", agent_type="candidate_ethics", version="0.1.0",
        prompt_path="prompts/system.md", input_schema="CandidateEthicsInputV1",
        output_schema="CandidateEthicsResultV1", allowed_capabilities=("return_agent_result",)),
    ("root_literature_review", "0.1.0", "QUERY_PLAN_V1"): SkillManifest(
        id="root_literature_review", agent_type="root_literature_review", version="0.1.0",
        prompt_path="prompts/system.md", input_schema="RootQueryPlanInputV1",
        output_schema="RootQueryPlanResultV1", allowed_capabilities=("return_agent_result",)),
    ("root_literature_review", "0.1.0", "SOURCE_REVIEW_V1"): SkillManifest(
        id="root_literature_review", agent_type="root_literature_review", version="0.1.0",
        prompt_path="prompts/system.md", input_schema="RootLiteratureReviewInputV1",
        output_schema="RootLiteratureReviewResultV1", allowed_capabilities=("return_agent_result",)),
    ("generation", "0.3.0", None): SkillManifest(
        id="generation", agent_type="generation", version="0.3.0",
        prompt_path="prompts/system-baseline-v1.md", input_schema="GroundedGenerationInputV1",
        output_schema="GroundedGenerationResultV1", allowed_capabilities=("return_agent_result",)),
    ("reflection", "0.3.0", None): SkillManifest(
        id="reflection", agent_type="reflection", version="0.3.0",
        prompt_path="prompts/system-baseline-v1.md", input_schema="BaselineReflectionInputV1",
        output_schema="BaselineReflectionResultV1", allowed_capabilities=("return_agent_result",)),
})


PERFORMANCE_SKILL = SkillManifest(id="generation", agent_type="generation", version="0.4.0",
    prompt_path="prompts/system-performance-v1.md", input_schema="GroundedGenerationInputV1",
    output_schema="GroundedGenerationResultV1", allowed_capabilities=("return_agent_result",))

QUERY_PLANNING_V2_SKILL = SkillManifest(
    id="root_literature_review", agent_type="root_literature_review", version="0.2.0",
    prompt_path="prompts/system-query-v2.md", input_schema="RootQueryPlanInputV1",
    output_schema="RootQueryPlanResultV1", allowed_capabilities=("return_agent_result",))

QUERY_PLANNING_V3_SKILL = QUERY_PLANNING_V2_SKILL.model_copy(update={
    "version": "0.3.0", "prompt_path": "prompts/system-query-v3.md"})

ROOT_REVIEW_V4_SKILLS = {
    "QUERY_PLAN_V1": QUERY_PLANNING_V2_SKILL.model_copy(update={
        "version": "0.4.0", "prompt_path": "prompts/system-query-v4.md"}),
    "SOURCE_REVIEW_V1": SkillManifest(
        id="root_literature_review", agent_type="root_literature_review", version="0.4.0",
        prompt_path="prompts/system-source-review-v2.md", input_schema="RootLiteratureReviewInputV1",
        output_schema="RootLiteratureReviewResultV1", allowed_capabilities=("return_agent_result",)),
}


def core_skills_root() -> Path:
    """Locate the package-owned Core skill catalog independently of caller CWD."""

    root = files("co_scientist.skills").joinpath("resources")
    if not isinstance(root, Path) or not root.is_dir():
        raise RuntimeError("installed Core skill resources are not filesystem-backed")
    return root


BASELINE_SEARCH_SKILL_CONTRACTS: Mapping[tuple[str, str, str | None], SkillManifest] = MappingProxyType({
    ("ranking", "0.3.0", None): SkillManifest(
        id="ranking", agent_type="ranking", version="0.3.0",
        prompt_path="prompts/system-baseline-v1.md", input_schema="BaselineRankingInputV1",
        output_schema="BaselineRankingResultV1", allowed_capabilities=("return_agent_result",)),
    ("population_evolution", "0.3.0", None): SkillManifest(
        id="population_evolution", agent_type="population_evolution", version="0.3.0",
        prompt_path="prompts/system-baseline-v1.md", input_schema="BaselineEvolutionInputV1",
        output_schema="BaselineEvolutionResultV1", allowed_capabilities=("return_agent_result",)),
})


def core_skill_directory(skill_id: str) -> Path:
    """Resolve one Core skill directory from installed package resources."""

    if skill_id not in CORE_SKILL_CONTRACTS and skill_id not in {
        contract.id for contract in BASELINE_SKILL_CONTRACTS.values()
    }:
        raise KeyError(f"unknown Core skill: {skill_id}")
    return core_skills_root() / skill_id


def resolve_core_skill_contract(
    *,
    skill_id: str,
    skill_version: str,
    output_schema_id: str,
    phase: str | None = None,
) -> SkillManifest:
    """Resolve one exact skill/version/schema identity from the closed Core matrix."""
    if (skill_id, skill_version) == ("root_literature_review", "0.4.0"):
        for selected_phase, v4_contract in ROOT_REVIEW_V4_SKILLS.items():
            if v4_contract.output_schema == output_schema_id and phase in {None, selected_phase}:
                return v4_contract
        raise ValueError("root-review-v4 schema/phase mismatch")
    if (skill_id, skill_version, output_schema_id) == (
            "root_literature_review", "0.2.0", "RootQueryPlanResultV1") and phase in {None, "QUERY_PLAN_V1"}:
        return QUERY_PLANNING_V2_SKILL
    if (skill_id, skill_version, output_schema_id) == (
            "root_literature_review", "0.3.0", "RootQueryPlanResultV1") and phase in {None, "QUERY_PLAN_V1"}:
        return QUERY_PLANNING_V3_SKILL
    if (skill_id, skill_version, output_schema_id, phase) == (
            "generation", "0.4.0", "GroundedGenerationResultV1", None):
        return PERFORMANCE_SKILL

    # A retrieval tool has no model prompt or installed skill resource. Its
    # versioned envelope still participates in the closed execution registry.
    if (skill_id, skill_version, output_schema_id, phase) == (
        "root_retrieval", "0.2.0", "RootRetrievalResultV2", None,
    ):
        return SkillManifest(
            id="root_retrieval", agent_type="root_retrieval", version="0.2.0",
            prompt_path="", input_schema="RetrievalRequestBindingV2",
            output_schema="RootRetrievalResultV2", allowed_capabilities=("return_agent_result",),
        )

    baseline = [contract for (sid, version, mode), contract in {
                    **BASELINE_SKILL_CONTRACTS, **BASELINE_SEARCH_SKILL_CONTRACTS}.items()
                if sid == skill_id and version == skill_version
                and contract.output_schema == output_schema_id
                and (phase is None or mode == phase)]
    if baseline:
        if len(baseline) != 1:
            raise ValueError("ambiguous baseline skill phase")
        return baseline[0]
    if phase is not None:
        raise ValueError("skill/schema/phase identity mismatch")
    contract = next((candidate for candidate in (
        CORE_SKILL_CONTRACTS.get(skill_id), CORE_SKILL_CONTRACTS_V2.get(skill_id),
        CORE_SKILL_CONTRACTS_V3.get(skill_id),
    ) if candidate is not None and candidate.version == skill_version
        and candidate.output_schema == output_schema_id), None)
    if contract is None:
        raise ValueError("execution identity does not match canonical skill contract")
    return contract


def load_skill(directory: Path, *, skill_version: str | None = None,
               phase: str | None = None) -> SkillManifest:
    """Load a skill and fail closed when its prompt or authority is invalid."""
    if directory.name == "root_literature_review" and skill_version == "0.4.0":
        document = yaml.safe_load((directory / "manifest-v4.yaml").read_text())
        if (phase not in ROOT_REVIEW_V4_SKILLS
                or set(document) != {"id", "version", "phases"}
                or document["id"] != directory.name or document["version"] != skill_version
                or set(document["phases"]) != set(ROOT_REVIEW_V4_SKILLS)):
            raise ValueError("root-review-v4 requires exact phase manifest")
        for selected_phase, v4_expected in ROOT_REVIEW_V4_SKILLS.items():
            if (SkillManifest.model_validate(document["phases"][selected_phase]) != v4_expected
                    or not (directory / v4_expected.prompt_path).is_file()):
                raise ValueError("root-review-v4 skill/phase mismatch")
        return ROOT_REVIEW_V4_SKILLS[phase]
    if directory.name == "root_literature_review" and skill_version in {"0.2.0", "0.3.0"}:
        selected = QUERY_PLANNING_V3_SKILL if skill_version == "0.3.0" else QUERY_PLANNING_V2_SKILL
        manifest = SkillManifest.model_validate(yaml.safe_load(
            (directory / ("manifest-v3.yaml" if skill_version == "0.3.0" else "manifest-v2.yaml")).read_text()))
        if (phase != "QUERY_PLAN_V1" or manifest != selected
                or not (directory / manifest.prompt_path).is_file()):
            raise ValueError("query-v2 skill/phase mismatch")
        return manifest
    if directory.name == "generation" and skill_version == "0.4.0":
        import hashlib

        from co_scientist.domain.generation_integration import PROMPT_SHA

        manifest = SkillManifest.model_validate(yaml.safe_load((directory / "manifest-v3.yaml").read_text()))
        if (phase is not None or manifest != PERFORMANCE_SKILL
                or hashlib.sha256((directory / manifest.prompt_path).read_bytes()).hexdigest() != PROMPT_SHA):
            raise ValueError("performance prompt/skill identity mismatch")
        return manifest

    expected = CORE_SKILL_CONTRACTS.get(directory.name)
    manifest_path = directory / "manifest.yaml"
    baseline = [contract for (sid, version, mode), contract in {
                    **BASELINE_SKILL_CONTRACTS, **BASELINE_SEARCH_SKILL_CONTRACTS}.items()
                if sid == directory.name and (skill_version is None or version == skill_version)
                and mode == phase]
    # Existing default skills remain historical. New independent skills have
    # no historical default. Two-phase review always requires an explicit phase.
    if baseline and (skill_version is not None or expected is None):
        if len(baseline) != 1:
            raise ValueError("ambiguous baseline skill version/phase")
        expected = baseline[0]
        filename = "manifest-v3.yaml" if directory.name == "population_evolution" else (
            "manifest-v2.yaml" if directory.name in {"generation", "reflection", "ranking"} else (
            "manifest.yaml"
        ))
        document = yaml.safe_load((directory / filename).read_text(encoding="utf-8"))
        if directory.name == "root_literature_review":
            if (set(document) != {"id", "version", "phases"}
                    or document["id"] != expected.id or document["version"] != expected.version
                    or set(document["phases"]) != {"QUERY_PLAN_V1", "SOURCE_REVIEW_V1"}):
                raise ValueError("invalid phase manifest")
            # Validate BOTH phase bodies, not only the selected one.
            for mode, body in document["phases"].items():
                if SkillManifest.model_validate(body) != BASELINE_SKILL_CONTRACTS[
                    (directory.name, expected.version, mode)
                ]:
                    raise ValueError("phase manifest is not canonical")
            document = document["phases"][phase]
        manifest = SkillManifest.model_validate(document)
        if manifest != expected or not (directory / manifest.prompt_path).is_file():
            raise ValueError("baseline manifest/prompt contract mismatch")
        resolve_core_skill_contract(skill_id=manifest.id, skill_version=manifest.version,
                                   output_schema_id=manifest.output_schema, phase=phase)
        resolve_output_schema(manifest.output_schema, output_schema_version(manifest.output_schema))
        return manifest
    if phase is not None or directory.name == "root_literature_review":
        raise ValueError("baseline skill requires exact version/schema/phase")
    if skill_version is not None:
        if expected is not None and expected.version == skill_version:
            pass
        else:
            variants = (
                (CORE_SKILL_CONTRACTS_V2.get(directory.name), "manifest-v2.yaml"),
                (CORE_SKILL_CONTRACTS_V3.get(directory.name), "manifest-v3.yaml"),
            )
            matching = [(contract, filename) for contract, filename in variants
                        if contract is not None and contract.version == skill_version]
            if len(matching) != 1:
                raise ValueError("unknown canonical skill version")
            expected, filename = matching[0]
            manifest_path = directory / filename
    manifest = SkillManifest.model_validate(
        yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    )
    if expected is None or manifest != expected:
        raise ValueError("skill manifest does not match the canonical Core Preview contract")
    prompt = directory / manifest.prompt_path
    if not prompt.is_file():
        raise FileNotFoundError(prompt)
    if manifest.allowed_capabilities != ("return_agent_result",):
        raise ValueError("skills may only return AgentResult")
    resolve_core_skill_contract(
        skill_id=manifest.id,
        skill_version=manifest.version,
        output_schema_id=manifest.output_schema,
    )
    schema_version = output_schema_version(manifest.output_schema)
    resolve_output_schema(manifest.output_schema, schema_version)
    return manifest
