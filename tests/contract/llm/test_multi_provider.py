import json
from pathlib import Path

import httpx
import pytest

from co_scientist.adapters.llm.multi_provider import KEY_NAMES, NativeJSONProvider, output_text
from co_scientist.application.config import resolve_run_config


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["deepseek", "qwen", "gemini", "claude"])
async def test_native_raw_bytes_and_structured_output(provider):
    content = '{"research_plan_version":1}'
    if provider in {"deepseek", "qwen"}:
        envelope = {"id": "r1", "choices": [{"finish_reason": "stop", "message": {"content": content}}],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 4}}
    elif provider == "claude":
        envelope = {"id": "r1", "stop_reason": "end_turn", "content": [{"type": "text", "text": content}],
                    "usage": {"input_tokens": 3, "output_tokens": 4}}
    else:
        envelope = {"responseId": "r1", "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": content}]}}],
                    "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 4}}
    raw = json.dumps(envelope).encode()

    def handle(request):
        assert request.method == "POST"
        assert "secret" not in request.content.decode()
        assert "Return only JSON" in request.content.decode()
        return httpx.Response(200, content=raw)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await NativeJSONProvider(client, provider=provider, api_key="secret").invoke(
            {"model": "test-model", "system_prompt": "science", "user_prompt": "goal",
             "json_schema": {"type": "object"}})
    assert result.body == raw
    assert result.provider_response_id == "r1"
    assert result.usage["input_tokens"] == 3
    assert result.usage["output_tokens"] == 4
    assert output_text(provider, envelope) == content


@pytest.mark.parametrize("provider", ["openai", "deepseek", "qwen", "gemini", "claude"])
def test_provider_profile_resolution(provider):
    profile = "online" if provider == "openai" else provider
    env = {KEY_NAMES[provider]: "secret-value", f"CO_SCIENTIST_{provider.upper()}_MODEL": "test-model"}
    config = resolve_run_config(
        goal_file=Path("examples/lens_regeneration_goal.yaml"),
        profile_file=Path(f"configs/profiles/core_preview_{profile}.yaml"),
        provider=provider, environment=env)
    assert config.manifest["provider_configuration"]["provider"] == provider
    assert "secret-value" not in config.model_dump_json()
    with pytest.raises(ValueError, match=KEY_NAMES[provider]):
        resolve_run_config(
            goal_file=Path("examples/lens_regeneration_goal.yaml"),
            profile_file=Path(f"configs/profiles/core_preview_{profile}.yaml"),
            provider=provider, environment={})


@pytest.mark.parametrize("provider", ["deepseek", "qwen"])
def test_truncated_output_rejected(provider):
    with pytest.raises(ValueError, match="finish"):
        output_text(provider, {"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]})


@pytest.mark.asyncio
@pytest.mark.parametrize("thinking", ["enabled", "disabled"])
async def test_deepseek_frozen_generation_controls_reach_wire(thinking):
    from co_scientist.application.config import DeepSeekGenerationProfile

    settings = DeepSeekGenerationProfile(thinking=thinking).model_dump()

    def handle(request):
        body = json.loads(request.content)
        assert body["max_tokens"] == 32768
        assert body["thinking"] == {"type": thinking}
        assert body.get("reasoning_effort") == ("low" if thinking == "enabled" else None)
        return httpx.Response(200, json={"id": "r1", "usage": {}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        await NativeJSONProvider(client, provider="deepseek", api_key="secret",
                                 generation=settings).invoke(
            {"model": "test", "system_prompt": "science", "user_prompt": "goal",
             "json_schema": {"type": "object"}})


def test_deepseek_settings_are_frozen_in_manifest():
    config = resolve_run_config(
        goal_file=Path("examples/lens_regeneration_goal.yaml"),
        profile_file=Path("configs/profiles/core_preview_deepseek.yaml"),
        provider="deepseek",
        environment={"DEEPSEEK_API_KEY": "secret", "CO_SCIENTIST_DEEPSEEK_MODEL": "test"})
    assert config.manifest["provider_configuration"]["generation"]["max_tokens"] == 32768
    with pytest.raises(TypeError):
        config.manifest["provider_configuration"]["generation"]["max_tokens"] = 1
