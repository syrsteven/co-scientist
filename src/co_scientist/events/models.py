"""Immutable, versioned domain-event models."""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DomainEvent(BaseModel):
    """An event persisted with its stream sequence."""

    model_config = ConfigDict(frozen=True)

    sequence: int
    run_id: str
    event_type: str
    schema_version: int = 1
    payload: dict[str, Any]
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    causation_id: str | None = None
    correlation_id: str | None = None


class NewEvent(BaseModel):
    """An immutable event request awaiting assignment of a sequence."""

    model_config = ConfigDict(frozen=True)

    event_type: str
    schema_version: int = 1
    payload: dict[str, Any]
    causation_id: str | None = None
    correlation_id: str | None = None
