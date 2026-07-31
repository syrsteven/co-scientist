"""Port for providers that return complete, uninterpreted response bytes."""

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field


class RawExternalResponse(BaseModel):
    """Immutable response returned at the provider boundary."""

    model_config = ConfigDict(frozen=True)

    body: bytes
    mime_type: str
    provider_response_id: str | None = None
    usage: dict[str, int] = Field(default_factory=dict)


class ExternalProvider(Protocol):
    """External provider capable of returning a complete raw response."""

    async def invoke(self, request: dict[str, Any]) -> RawExternalResponse: ...
