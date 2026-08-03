import json
from pathlib import Path

import pytest

from co_scientist.skills.loader import load_skill

CORE_SKILL_CONTRACTS = {
    "generation": {
        "id": "generation",
        "agent_type": "generation",
        "version": "0.1.0",
        "prompt_path": "prompts/system.md",
        "input_schema": "GenerationInputV1",
        "output_schema": "GenerationResultV1",
        "allowed_tools": [],
        "allowed_capabilities": ["return_agent_result"],
    },
    "reflection": {
        "id": "reflection",
        "agent_type": "reflection",
        "version": "0.1.0",
        "prompt_path": "prompts/system.md",
        "input_schema": "ReflectionInputV1",
        "output_schema": "ReflectionResultV1",
        "allowed_tools": ["literature_search"],
        "allowed_capabilities": ["return_agent_result"],
    },
    "ranking": {
        "id": "ranking",
        "agent_type": "ranking",
        "version": "0.1.0",
        "prompt_path": "prompts/system.md",
        "input_schema": "RankingInputV1",
        "output_schema": "RankingResultV1",
        "allowed_tools": [],
        "allowed_capabilities": ["return_agent_result"],
    },
    "proximity": {
        "id": "proximity",
        "agent_type": "proximity",
        "version": "0.1.0",
        "prompt_path": "prompts/system.md",
        "input_schema": "ProximityInputV1",
        "output_schema": "ProximityResultV1",
        "allowed_tools": [],
        "allowed_capabilities": ["return_agent_result"],
    },
    "evolution": {
        "id": "evolution",
        "agent_type": "evolution",
        "version": "0.1.0",
        "prompt_path": "prompts/system.md",
        "input_schema": "EvolutionInputV1",
        "output_schema": "EvolutionResultV1",
        "allowed_tools": [],
        "allowed_capabilities": ["return_agent_result"],
    },
    "meta_review": {
        "id": "meta_review",
        "agent_type": "meta_review",
        "version": "0.1.0",
        "prompt_path": "prompts/system.md",
        "input_schema": "MetaReviewInputV1",
        "output_schema": "MetaReviewResultV1",
        "allowed_tools": [],
        "allowed_capabilities": ["return_agent_result"],
    },
}


# Mutation caught: changing any checked-in field in the exact six-skill contract matrix.
def test_all_six_core_skills_match_the_independent_canonical_matrix() -> None:
    actual = {
        name: load_skill(Path("skills") / name).model_dump(mode="json")
        for name in CORE_SKILL_CONTRACTS
    }

    assert actual == CORE_SKILL_CONTRACTS


@pytest.mark.parametrize(
    "mutation",
    [
        {"id": "reflection"},
        {"agent_type": "reflection"},
        {"version": "0.2.0"},
        {"input_schema": "WrongInputV1"},
        {"output_schema": "WrongResultV1"},
        {"allowed_tools": ["literature_search"]},
        {"unexpected_field": True},
    ],
)
# Mutation caught: accepting a runtime manifest that drifts from the canonical matrix.
def test_loader_rejects_manifest_matrix_mutations(tmp_path: Path, mutation: dict) -> None:
    directory = tmp_path / "generation"
    prompt = directory / "prompts" / "system.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("Return JSON.\n", encoding="utf-8")
    manifest = {**CORE_SKILL_CONTRACTS["generation"], **mutation}
    (directory / "manifest.yaml").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError):
        load_skill(directory)
