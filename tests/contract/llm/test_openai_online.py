import os

import pytest

from co_scientist.adapters.llm.openai_responses import OpenAIResponsesProvider


def live_provider() -> OpenAIResponsesProvider:
    if not os.getenv("OPENAI_API_KEY") or not os.getenv("CO_SCIENTIST_OPENAI_MODEL"):
        pytest.skip("online OpenAI credentials are not configured")
    from openai import AsyncOpenAI

    return OpenAIResponsesProvider(AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"]))


@pytest.mark.online
@pytest.mark.asyncio
async def test_live_provider_returns_schema_valid_payload() -> None:
    raw = await live_provider().invoke(
        {
            "model": os.environ["CO_SCIENTIST_OPENAI_MODEL"],
            "system_prompt": "Return JSON matching the schema.",
            "user_prompt": "Return one object with status equal to ok.",
            "json_schema": {
                "type": "object",
                "properties": {"status": {"type": "string", "enum": ["ok"]}},
                "required": ["status"],
                "additionalProperties": False,
            },
        }
    )

    assert raw.provider_response_id
    assert raw.usage["output_tokens"] > 0
