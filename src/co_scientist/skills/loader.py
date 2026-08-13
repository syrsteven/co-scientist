"""Load and validate project runtime skill manifests."""

from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Literal

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict

from co_scientist.agents.payloads import CoreOutputSchemaId, resolve_output_schema


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
        "meta_review",
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
    }
)


def resolve_core_skill_contract(
    *,
    skill_id: str,
    skill_version: str,
    output_schema_id: str,
) -> SkillManifest:
    """Resolve one exact skill/version/schema identity from the closed Core matrix."""

    contract = CORE_SKILL_CONTRACTS.get(skill_id)
    if (
        contract is None
        or contract.version != skill_version
        or contract.output_schema != output_schema_id
    ):
        raise ValueError("execution identity does not match canonical skill contract")
    return contract


def load_skill(directory: Path) -> SkillManifest:
    """Load a skill and fail closed when its prompt or authority is invalid."""

    manifest = SkillManifest.model_validate(
        yaml.safe_load((directory / "manifest.yaml").read_text(encoding="utf-8"))
    )
    expected = CORE_SKILL_CONTRACTS.get(directory.name)
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
    resolve_output_schema(manifest.output_schema, 1)
    return manifest
