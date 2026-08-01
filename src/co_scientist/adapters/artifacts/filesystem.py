"""Content-addressed filesystem artifact persistence."""

import hashlib
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from co_scientist.ports.artifact_store import ArtifactRef, RawArtifactManifest
from co_scientist.ports.external_provider import thaw_json


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


class FilesystemArtifactStore:
    """Persist complete raw bodies with an atomic rename boundary."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    @staticmethod
    def _validate_call_id(call_id: str) -> None:
        candidate = Path(call_id)
        if (
            not call_id
            or candidate.is_absolute()
            or len(candidate.parts) != 1
            or candidate.parts[0] in {".", ".."}
        ):
            raise ValueError("call_id must be one relative path segment")

    def _contained_path(self, path: Path) -> Path:
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root):
            raise ValueError("path is outside artifact root")
        return resolved

    @staticmethod
    def _atomic_write(destination: Path, data: bytes) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_suffix(destination.suffix + ".partial")
        with partial.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(partial, destination)
        directory_fd = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

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
    ) -> ArtifactRef:
        self._validate_call_id(call_id)
        digest = _sha256(data)
        relative_path = Path("raw") / call_id / digest.removeprefix("sha256:")
        destination = self._contained_path(self.root / relative_path)
        ref = ArtifactRef(
            path=relative_path.as_posix(),
            sha256=digest,
            mime_type=mime_type,
            byte_length=len(data),
        )
        manifest = RawArtifactManifest(
            call_id=call_id,
            artifact_ref=ref,
            request_fingerprint=request_fingerprint,
            run_id=run_id,
            task_id=task_id,
            execution_context_fingerprint=execution_context_fingerprint,
            provider_response_id=provider_response_id,
            usage=thaw_json(usage or {}),
        )
        manifest_path = destination.with_name(destination.name + ".manifest.json")
        self._atomic_write(destination, data)
        self._atomic_write(manifest_path, manifest.model_dump_json().encode("utf-8"))
        return ref

    def read(self, ref: ArtifactRef) -> bytes:
        data = self._contained_path(self.root / ref.path).read_bytes()
        if len(data) != ref.byte_length or _sha256(data) != ref.sha256:
            raise ValueError("artifact integrity check failed")
        return data

    def discover_raw(self, call_id: str) -> RawArtifactManifest | None:
        self._validate_call_id(call_id)
        directory = self._contained_path(self.root / "raw" / call_id)
        if not directory.exists():
            return None
        manifests = sorted(directory.glob("*.manifest.json"))
        if not manifests:
            return None
        if len(manifests) != 1:
            raise ValueError(f"multiple durable raw manifests for call {call_id}")
        manifest_path = manifests[0]
        try:
            manifest = RawArtifactManifest.model_validate_json(manifest_path.read_bytes())
        except (OSError, ValidationError, ValueError) as error:
            raise ValueError("raw manifest integrity check failed") from error
        ref = manifest.artifact_ref
        expected_path = Path("raw") / call_id / ref.sha256.removeprefix("sha256:")
        expected_manifest = expected_path.name + ".manifest.json"
        if (
            manifest.call_id != call_id
            or ref.path != expected_path.as_posix()
            or manifest_path.name != expected_manifest
        ):
            raise ValueError("raw manifest integrity check failed")
        self.read(ref)
        return manifest

    def confirm_raw(self, manifest: RawArtifactManifest) -> None:
        """Revalidate and fsync a manifest durability boundary after an uncertain write."""

        discovered = self.discover_raw(manifest.call_id)
        if discovered != manifest:
            raise ValueError("raw manifest changed before durability confirmation")
        body_path = self._contained_path(self.root / manifest.artifact_ref.path)
        manifest_path = body_path.with_name(body_path.name + ".manifest.json")
        for path in (body_path, manifest_path):
            descriptor = os.open(path, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        directory_descriptor = os.open(body_path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
        if self.discover_raw(manifest.call_id) != manifest:
            raise ValueError("raw manifest changed during durability confirmation")
