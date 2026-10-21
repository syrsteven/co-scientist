"""Raw OpenAI Responses API adapter."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openai import AsyncOpenAI

from co_scientist.domain.pilot_pricing import OpenAIJudgePilotPricing
from co_scientist.ports.external_provider import RawExternalResponse


class OpenAIResponsesProvider:
    """Return OpenAI response envelopes without interpreting their output."""

    def __init__(self, client: "AsyncOpenAI") -> None:
        self.client = client

    async def invoke(self, request: dict[str, Any]) -> RawExternalResponse:
        pilot_pricing: OpenAIJudgePilotPricing | None = None
        result_contract = request.get("provider_result")
        if result_contract is not None and result_contract.get("mode") != "json_schema":
            raise ValueError("OpenAI Responses provider requires JSON Schema result mode")
        schema = (
            result_contract.get("schema") if result_contract is not None else request["json_schema"]
        )
        schema_name = (
            result_contract.get("schema_name")
            if result_contract is not None
            else request.get("schema_name", "agent_result")
        )
        options: dict[str, Any] = {
            "model": request["model"],
            "instructions": request["system_prompt"],
            "input": request["user_prompt"],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "schema": schema,
                    "strict": True,
                }
            },
        }
        if request.get("operation") is not None:
            parameters = (
                request.get("judge_parameters")
                if request["operation"] == "blind_evaluate"
                else request.get("generation_parameters")
            )
            if not isinstance(parameters, dict) or set(parameters) - {
                "max_output_tokens",
                "reasoning_effort",
                "pilot_pricing",
            }:
                raise ValueError("live OpenAI benchmark requires frozen call parameters")
            maximum = parameters.get("max_output_tokens")
            if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum < 1:
                raise ValueError("live OpenAI benchmark requires max_output_tokens")
            options["max_output_tokens"] = maximum
            if "reasoning_effort" in parameters:
                options["reasoning"] = {"effort": parameters["reasoning_effort"]}
            if parameters.get("pilot_pricing") is not None:
                if request["operation"] != "blind_evaluate":
                    raise ValueError("OpenAI pilot pricing is only verified for the judge")
                pilot_pricing = OpenAIJudgePilotPricing.model_validate(parameters["pilot_pricing"])
                if pilot_pricing.model != request[
                    "model"
                ] or pilot_pricing.reserve_usd_per_call < pilot_pricing.minimum_reserve(maximum):
                    raise ValueError("OpenAI judge pricing reserve/model mismatch")
        if pilot_pricing is not None and pilot_pricing.input_token_limit is not None:
            from co_scientist.runtime.bounded_transport import require_bounded_client

            require_bounded_client(self.client._client, pilot_pricing, options["max_output_tokens"])
        response = await self.client.responses.create(**options)
        usage: dict[str, Any] = {}
        response_model = getattr(response, "model", None)
        if isinstance(response_model, str):
            usage["response_model"] = response_model
        if response.usage is not None:
            usage["input_tokens"] = response.usage.input_tokens
            usage["output_tokens"] = response.usage.output_tokens
            input_details = getattr(response.usage, "input_tokens_details", None)
            output_details = getattr(response.usage, "output_tokens_details", None)
            if input_details is not None:
                cached = getattr(input_details, "cached_tokens", None)
                if cached is not None:
                    usage["cached_tokens"] = cached
            if output_details is not None:
                reasoning = getattr(output_details, "reasoning_tokens", None)
                if reasoning is not None:
                    usage["reasoning_tokens"] = reasoning
        if pilot_pricing is not None:
            usage["cost_usd"] = str(
                pilot_pricing.conservative_cost(
                    input_tokens=usage.get("input_tokens"),
                    output_tokens=usage.get("output_tokens"),
                )
            )
            usage["pricing_version"] = f"estimated:{pilot_pricing.version}"
        return RawExternalResponse(
            body=response.model_dump_json().encode("utf-8"),
            mime_type="application/json",
            provider_response_id=response.id,
            usage=usage,
        )
