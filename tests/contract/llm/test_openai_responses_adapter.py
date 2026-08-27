import pytest
from pydantic import BaseModel

from co_scientist.adapters.llm.openai_responses import OpenAIResponsesProvider


class FakeUsage(BaseModel):
    input_tokens: int = 10
    output_tokens: int = 5


class FakeResponse(BaseModel):
    id: str = "resp-1"
    usage: FakeUsage = FakeUsage()


class FakeResponseWithoutUsage(BaseModel):
    id: str = "resp-without-usage"
    usage: FakeUsage | None = None


class FakeResponses:
    async def create(self, **kwargs):
        return FakeResponse()


class FakeClient:
    responses = FakeResponses()


class FakeResponsesWithoutUsage:
    async def create(self, **kwargs):
        return FakeResponseWithoutUsage()


class FakeClientWithoutUsage:
    responses = FakeResponsesWithoutUsage()


@pytest.mark.asyncio
async def test_adapter_returns_unparsed_raw_json() -> None:
    provider = OpenAIResponsesProvider(FakeClient())

    raw = await provider.invoke(
        {
            "model": "configured-model",
            "system_prompt": "Return JSON.",
            "user_prompt": "Generate one hypothesis.",
            "json_schema": {"type": "object"},
        }
    )

    assert raw.mime_type == "application/json"
    assert b'"id":"resp-1"' in raw.body
    assert raw.provider_response_id == "resp-1"


@pytest.mark.asyncio
async def test_adapter_preserves_raw_response_without_usage() -> None:
    provider = OpenAIResponsesProvider(FakeClientWithoutUsage())

    raw = await provider.invoke(
        {
            "model": "configured-model",
            "system_prompt": "Return JSON.",
            "user_prompt": "Generate one hypothesis.",
            "json_schema": {"type": "object"},
        }
    )

    assert b'"id":"resp-without-usage"' in raw.body
    assert raw.usage == {}
