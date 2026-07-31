"""Port for durable raw-artifact persistence."""

from typing import Protocol

from pydantic import BaseModel, ConfigDict


class ArtifactRef(BaseModel):
    """Immutable metadata identifying one content-addressed artifact."""

    model_config = ConfigDict(frozen=True)

    path: str
    sha256: str
    mime_type: str
    byte_length: int


class ArtifactStore(Protocol):
    """Persist and retrieve complete raw response bodies."""

    def persist_raw(self, call_id: str, data: bytes, mime_type: str) -> ArtifactRef: ...

    def read(self, ref: ArtifactRef) -> bytes: ...
