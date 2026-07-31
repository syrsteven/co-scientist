from pathlib import Path

import pytest

from co_scientist.adapters.artifacts.filesystem import FilesystemArtifactStore
from co_scientist.ports.artifact_store import ArtifactRef


def test_raw_artifact_is_content_addressed_and_complete(tmp_path) -> None:
    store = FilesystemArtifactStore(tmp_path)

    ref = store.persist_raw("call-1", b'{"id":"response-1"}', "application/json")

    assert ref.sha256 == (
        "sha256:ea41a4276c4160aabaffeeb962241ed8b039c96ba66203a8909f22ecb92f6097"
    )
    assert ref.mime_type == "application/json"
    assert ref.byte_length == 19
    assert store.read(ref) == b'{"id":"response-1"}'
    assert not list(tmp_path.rglob("*.partial"))


@pytest.mark.parametrize("call_id", ["..", "../escape", "nested/../../escape"])
def test_raw_artifact_rejects_traversal_call_ids(tmp_path, call_id) -> None:
    store = FilesystemArtifactStore(tmp_path / "artifacts")

    with pytest.raises(ValueError, match="call_id"):
        store.persist_raw(call_id, b"raw", "application/octet-stream")


def test_raw_artifact_rejects_absolute_call_id(tmp_path) -> None:
    store = FilesystemArtifactStore(tmp_path / "artifacts")

    with pytest.raises(ValueError, match="call_id"):
        store.persist_raw(str(tmp_path / "outside"), b"raw", "application/octet-stream")


def test_read_rejects_artifact_reference_outside_store(tmp_path) -> None:
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"raw")
    ref = ArtifactRef(
        path=str(outside),
        sha256="sha256:d7439bee24773b46eb79b22b7c1541ef5a0d72e937dd76f7b89368f8a11f5032",
        mime_type="application/octet-stream",
        byte_length=3,
    )

    with pytest.raises(ValueError, match="outside artifact root"):
        store.read(ref)


def test_read_rejects_tampered_artifact(tmp_path) -> None:
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    ref = store.persist_raw("call-1", b"original", "application/octet-stream")
    Path(ref.path).write_bytes(b"tampered")

    with pytest.raises(ValueError, match="integrity"):
        store.read(ref)


def test_read_rejects_byte_length_mismatch(tmp_path) -> None:
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    ref = store.persist_raw("call-1", b"original", "application/octet-stream")
    wrong_length = ref.model_copy(update={"byte_length": 7})

    with pytest.raises(ValueError, match="integrity"):
        store.read(wrong_length)
