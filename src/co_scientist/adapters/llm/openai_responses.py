"""Raw OpenAI Responses API adapter."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openai import AsyncOpenAI

from co_scientist.ports.external_provider import RawExternalResponse


class OpenAIResponsesProvider:
    """Return OpenAI response envelopes without interpreting their output."""

    def __init__(self, client: "AsyncOpenAI") -> None:
        self.client = client

    async def invoke(self, request: dict[str, Any]) -> RawExternalResponse:
        response = await self.client.responses.create(
            model=request["model"],
            instructions=request["system_prompt"],
            input=request["user_prompt"],
            text={
                "format": {
                    "type": "json_schema",
                    "name": request.get("schema_name", "agent_result"),
                    "schema": request["json_schema"],
                    "strict": True,
                }
            },
        )
        usage = {}
        if response.usage is not None:
            usage = {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            }
        return RawExternalResponse(
            body=response.model_dump_json().encode("utf-8"),
            mime_type="application/json",
            provider_response_id=response.id,
            usage=usage,
        )
