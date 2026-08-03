"""Load and validate project runtime skill manifests."""

from pathlib import Path
from typing import Literal

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict


class SkillManifest(BaseModel):
    """Immutable capability boundary for one worker skill."""

    model_config = ConfigDict(frozen=True)

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
    output_schema: str
    allowed_tools: tuple[str, ...] = ()
    allowed_capabilities: tuple[Literal["return_agent_result"], ...]


def load_skill(directory: Path) -> SkillManifest:
    """Load a skill and fail closed when its prompt or authority is invalid."""

    manifest = SkillManifest.model_validate(
        yaml.safe_load((directory / "manifest.yaml").read_text(encoding="utf-8"))
    )
    prompt = directory / manifest.prompt_path
    if not prompt.is_file():
        raise FileNotFoundError(prompt)
    if manifest.allowed_capabilities != ("return_agent_result",):
        raise ValueError("skills may only return AgentResult")
    return manifest
