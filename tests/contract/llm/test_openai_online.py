import os

import pytest

from co_scientist.adapters.llm.openai_responses import OpenAIResponsesProvider


@pytest.mark.online
@pytest.mark.asyncio
async def test_live_provider_returns_schema_valid_payload() -> None:
    if not (
        os.getenv("OPENAI_API_KEY")
        and os.getenv("CO_SCIENTIST_OPENAI_MODEL")
        and os.getenv("CO_SCIENTIST_NETWORK_ONLINE") == "1"
    ):
        pytest.skip(
            "requires OPENAI_API_KEY, CO_SCIENTIST_OPENAI_MODEL, and "
            "CO_SCIENTIST_NETWORK_ONLINE=1"
        )
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
    try:
        raw = await OpenAIResponsesProvider(client).invoke(
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
    finally:
        await client.close()

    assert raw.provider_response_id
    assert raw.usage["output_tokens"] > 0
