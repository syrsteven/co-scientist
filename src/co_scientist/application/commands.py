"""Typed mutation requests accepted by the application boundary."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CreateRun(BaseModel):
    """Create and start one developer-preview run without invoking a provider."""

    model_config = ConfigDict(frozen=True)

    goal_file: Path
    profile_file: Path
    provider: Literal["fake", "replay", "openai"] = "fake"
    data_dir: Path = Path(".co-scientist")


class RunCommand(BaseModel):
    """Optimistically concurrent lifecycle command for an existing run."""

    model_config = ConfigDict(frozen=True)

    run_id: str = Field(min_length=1)
    expected_run_sequence: int = Field(ge=0)
    command: Literal["start", "pause", "resume", "stop", "cancel"]


class ExportRun(BaseModel):
    """Write a deterministic read snapshot to a user-selected path."""

    model_config = ConfigDict(frozen=True)

    run_id: str = Field(min_length=1)
    output: Path
