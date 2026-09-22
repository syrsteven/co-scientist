"""The manual paid probe stays one-shot and preserves even rejected responses."""

import json

import httpx
import pytest

from tests.live_ranking_probe import run_probe
from tests.unit.runtime.test_ranking_output import envelope, payload

ENV = {"DEEPSEEK_API_KEY": "test-secret", "CO_SCIENTIST_DEEPSEEK_MODEL": "offline-model"}


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["valid", "bad_json", "rejected", "network_failure"])
@pytest.mark.parametrize("protocol", ["deepseek-strict-tool-v1", "deepseek-strict-tool-v2"])
async def test_probe_is_raw_first_and_never_retries(tmp_path, mode, protocol):
    output = tmp_path / "probe"
    observed = []

    def handle(request):
        observed.append(request)
        assert json.loads((output / "events.jsonl").read_text().splitlines()[-1])["state"] == "started"
        if mode == "network_failure":
            raise httpx.ConnectError("synthetic", request=request)
        if mode == "rejected":
            return httpx.Response(400, json={"error": {"message": "unsupported schema"}})
        inputs = json.loads((output / "request.json").read_text())["input"]
        value = payload(inputs)
        if protocol == "deepseek-strict-tool-v2":
            reasons = value.pop("dimension_reasons")
            value.update({f"reason_{key}": text for key, text in reasons.items()})
        body = envelope(value, name=inputs["ranking_output_contract"]["tool_name"])
        if mode == "bad_json":
            body["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = '{"bad":['
        body["usage"] = {"prompt_tokens": 11, "completion_tokens": 22}
        return httpx.Response(200, json=body)

    report = await run_probe(output, ENV, confirmed=True, protocol=protocol, transport=httpx.MockTransport(handle))
    assert report["protocol"] == protocol
    assert len(observed) == report["http_requests"] == 1
    assert report["state"] == ("validated" if mode == "valid" else "failed")
    states = [json.loads(line)["state"] for line in (output / "events.jsonl").read_text().splitlines()]
    assert states[:2] == ["planned", "started"]
    if mode != "network_failure":
        assert states[2] == "raw_response_persisted"
        raw = output / "artifacts" / report["raw_artifact_ref"]["path"]
        assert raw.is_file()
    if mode in {"valid", "bad_json"}:
        assert report["usage"] == {"input_tokens": 11, "output_tokens": 22}
    assert not list(output.rglob("*.db"))
    assert all("test-secret" not in p.read_text() for p in output.rglob("*") if p.is_file())
    with pytest.raises(FileExistsError):
        await run_probe(output, ENV, confirmed=True, protocol=protocol, transport=httpx.MockTransport(handle))
    assert len(observed) == 1


@pytest.mark.asyncio
async def test_probe_needs_confirmation_before_creating_evidence(tmp_path):
    output = tmp_path / "probe"
    with pytest.raises(ValueError, match="confirmation"):
        await run_probe(output, ENV, confirmed=False)
    assert not output.exists()
