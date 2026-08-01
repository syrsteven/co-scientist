"""Port for durable raw-artifact persistence and crash recovery."""

from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ArtifactRef(BaseModel):
    """Immutable metadata identifying one content-addressed artifact."""

    model_config = ConfigDict(frozen=True)

    path: str
    sha256: str
    mime_type: str
    byte_length: int

    @field_validator("path")
    @classmethod
    def require_root_relative_path(cls, value: str) -> str:
        candidate = PurePosixPath(value)
        if (
            not value
            or "\\" in value
            or candidate.is_absolute()
            or not candidate.parts
            or ".." in candidate.parts
            or candidate.as_posix() != value
        ):
            raise ValueError("artifact path must be a normalized root-relative identifier")
        return value


class ArtifactStore(Protocol):
    """Persist and retrieve complete raw response bodies."""

    def persist_raw(
        self,
        call_id: str,
        data: bytes,
        mime_type: str,
        *,
        request_fingerprint: str,
        run_id: str,
        task_id: str,
        execution_context_fingerprint: str,
        provider_response_id: str | None = None,
        usage: Mapping[str, Any] | None = None,
    ) -> ArtifactRef: ...

    def read(self, ref: ArtifactRef) -> bytes: ...

    def discover_raw(self, call_id: str) -> "RawArtifactManifest | None": ...


class RawArtifactManifest(BaseModel):
    """Durable metadata committed after a complete raw response body."""

    model_config = ConfigDict(frozen=True)

    version: Literal[1] = 1
    call_id: str
    artifact_ref: ArtifactRef
    request_fingerprint: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    execution_context_fingerprint: str = Field(min_length=1)
    provider_response_id: str | None = None
    usage: dict[str, Any] = Field(default_factory=dict)
