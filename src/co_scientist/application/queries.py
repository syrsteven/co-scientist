"""Typed read requests accepted by the application boundary."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class CheckConfig(BaseModel):
    """Check that the composed local application is usable."""

    model_config = ConfigDict(frozen=True)

    data_dir: Path | None = None


class GetRunStatus(BaseModel):
    """Fetch the current durable run projection."""

    model_config = ConfigDict(frozen=True)

    run_id: str = Field(min_length=1)


class ReplayRun(BaseModel):
    """Reconstruct a run snapshot from its durable events."""

    model_config = ConfigDict(frozen=True)

    run_id: str = Field(min_length=1)
