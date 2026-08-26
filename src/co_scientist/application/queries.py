"""Typed read requests accepted by the application boundary."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from co_scientist.domain.identifiers import RunId


class CheckConfig(BaseModel):
    """Check that the composed local application is usable."""

    model_config = ConfigDict(frozen=True)

    data_dir: Path | None = None


class GetRunStatus(BaseModel):
    """Fetch the current durable run projection."""

    model_config = ConfigDict(frozen=True)

    run_id: RunId


class ReplayRun(BaseModel):
    """Reconstruct a run snapshot from its durable events."""

    model_config = ConfigDict(frozen=True)

    run_id: RunId
