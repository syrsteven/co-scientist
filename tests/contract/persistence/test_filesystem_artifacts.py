import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from co_scientist.adapters.artifacts.filesystem import FilesystemArtifactStore
from co_scientist.ports.artifact_store import ArtifactRef


def _provenance() -> dict[str, str]:
    return {
        "request_fingerprint": "request-fingerprint",
        "run_id": "r-1",
        "task_id": "task-1",
        "execution_context_fingerprint": "context-fingerprint",
    }


def test_raw_artifact_is_content_addressed_and_complete(tmp_path) -> None:
    store = FilesystemArtifactStore(tmp_path)

    ref = store.persist_raw(
        "call-1",
        b'{"id":"response-1"}',
        "application/json",
        provider_response_id="response-1",
        usage={"input_tokens": 7},
        **_provenance(),
    )

    assert ref.sha256 == (
        "sha256:ea41a4276c4160aabaffeeb962241ed8b039c96ba66203a8909f22ecb92f6097"
    )
    assert ref.mime_type == "application/json"
    assert ref.byte_length == 19
    assert ref.path == (
        "raw/call-1/ea41a4276c4160aabaffeeb962241ed8b039c96ba66203a8909f22ecb92f6097"
    )
    assert not Path(ref.path).is_absolute()
    assert store.read(ref) == b'{"id":"response-1"}'
    discovered = store.discover_raw("call-1")
    assert discovered is not None
    assert discovered.artifact_ref == ref
    assert discovered.provider_response_id == "response-1"
    assert discovered.usage == {"input_tokens": 7}
    assert discovered.request_fingerprint == "request-fingerprint"
    assert discovered.run_id == "r-1"
    assert discovered.task_id == "task-1"
    assert discovered.execution_context_fingerprint == "context-fingerprint"
    assert not list(tmp_path.rglob("*.partial"))


@pytest.mark.parametrize("call_id", ["..", "../escape", "nested/../../escape"])
def test_raw_artifact_rejects_traversal_call_ids(tmp_path, call_id) -> None:
    store = FilesystemArtifactStore(tmp_path / "artifacts")

    with pytest.raises(ValueError, match="call_id"):
        store.persist_raw(call_id, b"raw", "application/octet-stream", **_provenance())


def test_raw_artifact_rejects_absolute_call_id(tmp_path) -> None:
    store = FilesystemArtifactStore(tmp_path / "artifacts")

    with pytest.raises(ValueError, match="call_id"):
        store.persist_raw(
            str(tmp_path / "outside"),
            b"raw",
            "application/octet-stream",
            **_provenance(),
        )


def test_read_rejects_artifact_reference_outside_store(tmp_path) -> None:
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"raw")
    ref = ArtifactRef.model_construct(
        path="../outside.bin",
        sha256="sha256:d7439bee24773b46eb79b22b7c1541ef5a0d72e937dd76f7b89368f8a11f5032",
        mime_type="application/octet-stream",
        byte_length=3,
    )

    with pytest.raises(ValueError, match="outside artifact root"):
        store.read(ref)


@pytest.mark.parametrize("path", ["/absolute/raw", "../outside", "raw/../../outside", ""])
def test_artifact_reference_requires_safe_root_relative_path(path) -> None:
    with pytest.raises(ValidationError, match="relative"):
        ArtifactRef(
            path=path,
            sha256="sha256:d7439bee24773b46eb79b22b7c1541ef5a0d72e937dd76f7b89368f8a11f5032",
            mime_type="application/octet-stream",
            byte_length=3,
        )


def test_read_rejects_tampered_artifact(tmp_path) -> None:
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    ref = store.persist_raw(
        "call-1", b"original", "application/octet-stream", **_provenance()
    )
    (tmp_path / "artifacts" / ref.path).write_bytes(b"tampered")

    with pytest.raises(ValueError, match="integrity"):
        store.read(ref)


def test_read_rejects_byte_length_mismatch(tmp_path) -> None:
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    ref = store.persist_raw(
        "call-1", b"original", "application/octet-stream", **_provenance()
    )
    wrong_length = ref.model_copy(update={"byte_length": 7})

    with pytest.raises(ValueError, match="integrity"):
        store.read(wrong_length)


def test_discover_raw_rejects_tampered_manifest(tmp_path) -> None:
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    store.persist_raw("call-1", b"original", "application/octet-stream", **_provenance())
    manifest = next((tmp_path / "artifacts").rglob("*.manifest.json"))
    document = json.loads(manifest.read_text())
    document["artifact_ref"]["sha256"] = (
        "sha256:0000000000000000000000000000000000000000000000000000000000000000"
    )
    manifest.write_text(json.dumps(document))

    with pytest.raises(ValueError, match="integrity"):
        store.discover_raw("call-1")


def test_discover_raw_rejects_unknown_manifest_version(tmp_path) -> None:
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    store.persist_raw("call-1", b"original", "application/octet-stream", **_provenance())
    manifest = next((tmp_path / "artifacts").rglob("*.manifest.json"))
    document = json.loads(manifest.read_text())
    document["version"] = 2
    manifest.write_text(json.dumps(document))

    with pytest.raises(ValueError, match="integrity"):
        store.discover_raw("call-1")


def test_discover_raw_ignores_body_without_durable_manifest(tmp_path) -> None:
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    body_dir = tmp_path / "artifacts" / "raw" / "call-1"
    body_dir.mkdir(parents=True)
    (body_dir / "uncommitted-body").write_bytes(b"raw")

    assert store.discover_raw("call-1") is None
