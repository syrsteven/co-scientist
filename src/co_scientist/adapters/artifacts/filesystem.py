"""Content-addressed filesystem artifact persistence."""

import hashlib
import os
from pathlib import Path

from co_scientist.ports.artifact_store import ArtifactRef


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

    def persist_raw(self, call_id: str, data: bytes, mime_type: str) -> ArtifactRef:
        self._validate_call_id(call_id)
        digest = _sha256(data)
        destination = self._contained_path(
            self.root / "raw" / call_id / digest.removeprefix("sha256:")
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_suffix(".partial")
        with partial.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(partial, destination)
        return ArtifactRef(
            path=str(destination),
            sha256=digest,
            mime_type=mime_type,
            byte_length=len(data),
        )

    def read(self, ref: ArtifactRef) -> bytes:
        data = self._contained_path(Path(ref.path)).read_bytes()
        if len(data) != ref.byte_length or _sha256(data) != ref.sha256:
            raise ValueError("artifact integrity check failed")
        return data
