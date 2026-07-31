"""Port for providers that return complete, uninterpreted response bytes."""

from collections.abc import Mapping
from math import isfinite
from types import MappingProxyType
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator


class _FrozenList(tuple[Any, ...]):
    """Immutable JSON array retaining value equality with ordinary lists."""

    def __eq__(self, other: object) -> bool:
        if isinstance(other, list | tuple):
            return tuple(self) == tuple(other)
        return NotImplemented

    __hash__ = tuple.__hash__


def freeze_json(value: Any) -> Any:
    """Validate and recursively freeze one JSON-compatible value."""

    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("values must be JSON-compatible")
        return MappingProxyType({key: freeze_json(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return _FrozenList(freeze_json(item) for item in value)
    if value is None or isinstance(value, str | int | bool):
        return value
    if isinstance(value, float) and isfinite(value):
        return value
    raise ValueError("values must be JSON-compatible")


def thaw_json(value: Any) -> Any:
    """Convert recursively frozen JSON values to standard containers."""

    if isinstance(value, Mapping):
        return {key: thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    return value


class RawExternalResponse(BaseModel):
    """Immutable response returned at the provider boundary."""

    model_config = ConfigDict(frozen=True)

    body: bytes
    mime_type: str
    provider_response_id: str | None = None
    usage: Mapping[str, Any] = Field(default_factory=dict)

    @field_validator("usage")
    @classmethod
    def freeze_usage(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        return freeze_json(value)

    @field_serializer("usage", when_used="json")
    def serialize_usage(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return thaw_json(value)


class ExternalProvider(Protocol):
    """External provider capable of returning a complete raw response."""

    async def invoke(self, request: dict[str, Any]) -> RawExternalResponse: ...
