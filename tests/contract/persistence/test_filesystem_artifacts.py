from co_scientist.adapters.artifacts.filesystem import FilesystemArtifactStore


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
