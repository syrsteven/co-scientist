"""Typed mutation requests accepted by the application boundary."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from co_scientist.domain.identifiers import RunId


class CreateRun(BaseModel):
    """Create and start one developer-preview run without invoking a provider."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    goal_file: Path
    profile_file: Path
    provider: Literal["fake", "replay", "openai"] = "fake"


class ExecuteRun(BaseModel):
    """Resolve and execute one Core Preview Run to a durable boundary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    goal_file: Path
    profile_file: Path
    provider: Literal["replay", "openai", "deepseek", "qwen", "gemini", "claude"]
    run_id: RunId | None = None


class RunWorker(BaseModel):
    """Resume durable work for one existing execution-contract-v3 Run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: RunId


class RunCommand(BaseModel):
    """Optimistically concurrent lifecycle command for an existing run."""

    model_config = ConfigDict(frozen=True)

    run_id: RunId
    expected_run_sequence: int = Field(ge=0)
    command: Literal["start", "pause", "resume", "stop", "cancel"]


class RetryInvalidOutput(BaseModel):
    """Authorize one unchanged task attempt, without starting a Worker."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: RunId
    external_call_id: str = Field(min_length=1)
    expected_run_sequence: StrictInt = Field(ge=0)
    confirmed: StrictBool


class ExportRun(BaseModel):
    """Write the deterministic rich bundle to a new directory."""

    model_config = ConfigDict(frozen=True)

    run_id: RunId
    output: Path


class SubmitScientistFeedback(BaseModel):
    """Record a researcher's opinion and request one bounded independent review."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)
    run_id: RunId
    feedback_id: str = Field(min_length=1, max_length=2048)
    expected_run_sequence: StrictInt = Field(ge=0)
    actor: str = Field(min_length=1, max_length=200)
    note: str = Field(min_length=1, max_length=12000)
    confirmed: StrictBool
