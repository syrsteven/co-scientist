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
        self.root = root

    def persist_raw(self, call_id: str, data: bytes, mime_type: str) -> ArtifactRef:
        digest = _sha256(data)
        destination = self.root / "raw" / call_id / digest.removeprefix("sha256:")
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
        return Path(ref.path).read_bytes()
