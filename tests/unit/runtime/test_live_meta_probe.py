import json

import httpx
import pytest

from tests import live_meta_probe as probe


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [False, True])
async def test_meta_probe_persists_raw_before_validation_without_retry(tmp_path, monkeypatch, bad):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    inputs = {"research_plan_version": 1, "source_content_hashes": {"h": "sha256:" + "a" * 64}}
    request = {"model": "test", "system_prompt": "JSON", "user_prompt": "{}",
               "json_schema": {}, "input": inputs}
    monkeypatch.setattr(probe, "prepare", lambda source: (
        {"provider_configuration": {}}, request, {"request_fingerprint": "test-fingerprint"}))
    count = 0

    def respond(request):
        nonlocal count
        count += 1
        result = {"schema_version": 1, **inputs, "system_feedback": [], "overview": "test",
                  "coverage_gaps": ["Untested mechanism"], "safety_direction_check": "clear"}
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop",
            "message": {"content": "{" if bad else json.dumps(result)}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 5}})

    output = tmp_path / "probe"
    report = await probe.run_probe(tmp_path, output, confirmed=True,
                                   transport=httpx.MockTransport(respond))
    assert count == 1
    assert report["state"] == ("failed" if bad else "validated")
    assert report["usage"] == {"input_tokens": 12, "output_tokens": 5}
    assert (output / "artifacts" / report["raw_artifact_ref"]["path"]).exists()
    states = [json.loads(line)["state"] for line in (output / "events.jsonl").read_text().splitlines()]
    assert states.index("raw_response_persisted") < states.index("usage_recorded") < len(states) - 1
    with pytest.raises(FileExistsError):
        await probe.run_probe(tmp_path, output, confirmed=True, transport=httpx.MockTransport(respond))
    assert count == 1


@pytest.mark.asyncio
async def test_meta_probe_requires_confirmation_before_preparation(tmp_path):
    with pytest.raises(ValueError, match="confirmation"):
        await probe.run_probe(tmp_path, tmp_path / "probe", confirmed=False)
    assert not (tmp_path / "probe").exists()
