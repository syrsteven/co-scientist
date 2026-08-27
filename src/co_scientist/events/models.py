"""Immutable, versioned domain-event models."""

from collections.abc import Mapping
from datetime import UTC, datetime
from math import isfinite
from types import MappingProxyType
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("payload values must be JSON-compatible")
        return MappingProxyType({key: _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_deep_freeze(item) for item in value)
    if value is None or isinstance(value, str | int | bool):
        return value
    if isinstance(value, float) and isfinite(value):
        return value
    raise ValueError("payload values must be JSON-compatible")


def _deep_thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _deep_thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_deep_thaw(item) for item in value]
    return value


class DomainEvent(BaseModel):
    """An event persisted with its stream sequence."""

    model_config = ConfigDict(frozen=True)

    sequence: int
    run_id: str
    event_type: str
    schema_version: int = 1
    payload: Mapping[str, Any]
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    causation_id: str | None = None
    correlation_id: str | None = None

    @field_validator("payload")
    @classmethod
    def freeze_payload(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        return _deep_freeze(value)

    @field_serializer("payload", when_used="json")
    def serialize_payload(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return _deep_thaw(value)


class NewEvent(BaseModel):
    """An immutable event request awaiting assignment of a sequence."""

    model_config = ConfigDict(frozen=True)

    event_type: str
    schema_version: int = 1
    payload: Mapping[str, Any]
    causation_id: str | None = None
    correlation_id: str | None = None

    @field_validator("payload")
    @classmethod
    def freeze_payload(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        return _deep_freeze(value)

    @field_serializer("payload", when_used="json")
    def serialize_payload(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return _deep_thaw(value)
