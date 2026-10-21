"""Performance Generation through production capture; MockTransport-only revision."""

import json
from typing import Any

import httpx

from co_scientist.domain.execution_config import validate_wire
from co_scientist.domain.generation_integration import PROFILE
from co_scientist.domain.pilot_pricing import effective_task_pricing
from co_scientist.ports.external_provider import RawExternalResponse, capture_http_response
from co_scientist.runtime.bounded_transport import BoundedTransport, read_bounded_response


def response_text(envelope: dict) -> str:
    if envelope.get("status") != "completed":
        raise ValueError("Responses terminal status incomplete")
    content = [c for o in envelope.get("output", []) if o.get("type") == "message"
               for c in o.get("content", [])]
    if any(c.get("type") == "refusal" for c in content):
        raise ValueError("Responses refusal")
    texts = [c["text"] for c in content if c.get("type") == "output_text"]
    if len(texts) != 1 or not isinstance(texts[0], str) or not texts[0].strip():
        raise ValueError("ambiguous or missing Responses output")
    return texts[0]


class PerformanceResponsesProvider:
    provider = "fake"
    response_capture_version = 2

    def __init__(self, client: httpx.AsyncClient):
        self.generation = {"version": PROFILE, "activation": "OFFLINE_FAKE_ONLY"}
        t = client._transport
        if (not isinstance(t, BoundedTransport) or not isinstance(t.inner, httpx.MockTransport)
                or client.follow_redirects):
            raise ValueError("performance integration is MockTransport-only")
        self.client = client

    @classmethod
    def for_single_root(cls, client, *, api_key):
        from co_scientist.domain.single_root import FullIdeationConfig, SingleRootConfig

        t = client._transport
        if (not isinstance(t, BoundedTransport) or not isinstance(t.effective_config, (SingleRootConfig, FullIdeationConfig))
                or t.single_root_gate is None or client.follow_redirects or not api_key.strip()):
            raise ValueError("single-root Responses requires bounded authorized transport")
        instance = object.__new__(cls)
        instance.client, instance.api_key = client, api_key
        instance.provider = "openai"
        instance.generation = {"version": "single-root-dev-live-v1"}
        return instance

    async def invoke(self, request: dict[str, Any]) -> RawExternalResponse:
        t = request["effective_execution"]
        b = request["input"]["ideation_task_binding"]
        if (t["version"] != PROFILE or t["role"] != "generation" or t["temperature"] is not None
                or request["schema_name"] != "GroundedGenerationResultV1"
                or b["skill_version"] != "0.4.0" or b["model"] != "gpt-6.1-sol"
                or b["api"] != "openai-responses-strict-v1"
                or b["provider"] != ("openai" if hasattr(self, "api_key") else "fake") or b["thinking_mode"] != "enabled"
                or b["capability_id"] != t["capability"]["capability_id"]):
            raise ValueError("performance task/role capability mismatch")
        body = {"model": b["model"], "stream": False, "store": False, "service_tier": "default",
            "reasoning": {"effort": "medium"}, "max_output_tokens": t["runtime"]["max_output_tokens"],
            "input": [{"role": "system", "content": request["system_prompt"]},
                      {"role": "user", "content": request["user_prompt"]}],
            "text": {"format": {"type": "json_schema", "name": "scientific_proposal",
                "strict": True, "schema": request["provider_output_schema"]}}}
        wire = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        context_plan = None
        if t.get("continuous_policy") is not None:
            from co_scientist.runtime.context_planning import canonical, persist_plan, plan_context

            attempt = request["input"].get("continuous_attempt", {})
            body, context_plan = plan_context(body, t, attempt=b["attempt"],
                length_failures=attempt.get("length_failures", 0), correction=attempt.get("correction"))
            wire = canonical(body)
            persist_plan(self.client._transport, context_plan)
        validate_wire(t, wire)
        async with self.client.stream("POST", t["capability"]["endpoint"], content=wire,
                headers={"Content-Type": "application/json", **(
                    {"Authorization": "Bearer " + self.api_key} if hasattr(self, "api_key") else {})},
                timeout=t["runtime"]["http_timeout_seconds"], extensions={"effective_execution": t, **(
                    {"context_plan": context_plan} if context_plan is not None else {})}) as response:
            raw = await read_bounded_response(response, t["runtime"]["max_response_bytes"])
            capture_http_response(raw, response.status_code, dict(response.headers))
            # The controlled Worker callback confirms durable capture before
            # parsing. Recovery parses that same original capture without HTTP.
            return self._parse(raw, response.status_code, request)

    def parse_captured_response(self, capture, request):
        return self._parse(capture.body, capture.status, request)

    def _parse(self, raw, status, request):
        if status != 200:
            raise ValueError("non-200 Responses capture")
        e = json.loads(raw)
        if e.get("model") != "gpt-6.1-sol":
            raise ValueError("actual response model mismatch")
        u = e["usage"]
        inp, out = u["input_tokens"], u["output_tokens"]
        cache = u.get("input_tokens_details", {}).get("cached_tokens")
        reasoning = u.get("output_tokens_details", {}).get("reasoning_tokens")
        if (any(type(n) is not int or n < 0 for n in [inp, out])
                or cache is not None and (type(cache) is not int or not 0 <= cache <= inp)
                or reasoning is not None and (type(reasoning) is not int or not 0 <= reasoning <= out)
                or u.get("total_tokens", inp+out) != inp+out):
            raise ValueError("invalid Responses usage")
        t = request["effective_execution"]
        if inp > t["runtime"]["max_input_tokens"] or out > t["runtime"]["max_output_tokens"]:
            raise ValueError("Responses usage exceeds reservation")
        price = effective_task_pricing(t)
        cost = price.conservative_cost(input_tokens=inp, output_tokens=out)
        # Terminal/refusal/domain validation is performed by the executor AFTER
        # raw and trustworthy accounting are persisted, including malformed output.
        return RawExternalResponse(body=raw, mime_type="application/json", usage={
            "input_tokens": inp, "output_tokens": out,
            **({"cached_tokens": cache} if cache is not None else {}),
            **({"reasoning_tokens": reasoning} if reasoning is not None else {}),
            "response_model": e["model"], "cost_usd": str(cost),
            "pricing_version": "estimated:"+price.version})


class PerformanceRoleRouter:
    """Explicit offline composition: only Generation reaches Responses."""

    provider = "fake"
    response_capture_version = 2

    def __init__(self, generation: PerformanceResponsesProvider, other):
        if not isinstance(generation, PerformanceResponsesProvider):
            raise TypeError("performance Generation requires bounded MockTransport adapter")
        self.responses, self.other = generation, other
        self.generation = {"version": "performance-role-router-v1",
                           "responses": generation.generation,
                           "other": getattr(other, "generation", {})}

    def _select(self, request):
        t = request["effective_execution"]
        if t["schema_id"] == "GroundedGenerationResultV1":
            if t["version"] != PROFILE:
                raise ValueError("Generation cannot fall back to baseline")
            return self.responses
        if t["version"] != "effective-task-execution-v1":
            raise ValueError("performance revision cannot activate other roles")
        return self.other

    async def invoke(self, request):
        return await self._select(request).invoke(request)

    def parse_captured_response(self, capture, request):
        return self._select(request).parse_captured_response(capture, request)
