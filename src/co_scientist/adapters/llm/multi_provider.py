"""Native HTTP adapters; domain output is decoded only after raw persistence."""

import hashlib
import json
from typing import Any
from urllib.parse import quote

import httpx

from co_scientist.domain.pilot_output import (
    BASELINE_NORMALIZED_VERSION,
    baseline_output_spec,
    claim_output_spec,
    normalized_baseline_output_spec,
)
from co_scientist.domain.pilot_pricing import DeepSeekPilotPricing
from co_scientist.domain.probe_execution import (
    GenerationCapabilityProbeEnvelopeV2,
    GenerationProbePermitV2,
    generation_probe_envelope,
    generation_probe_permit,
)
from co_scientist.domain.ranking_output import ranking_output_spec
from co_scientist.ports.external_provider import (
    CapturedHTTPResponseV2,
    RawExternalResponse,
    capture_http_response,
)

ENDPOINTS = {
    "deepseek": "https://api.deepseek.com/chat/completions",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/models",
    "claude": "https://api.anthropic.com/v1/messages",
}
KEY_NAMES = {
    "openai": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "qwen": "DASHSCOPE_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "claude": "ANTHROPIC_API_KEY",
}


def generation_probe_wire_body(request: dict[str, Any]) -> dict[str, Any]:
    """Exact probe-only wire body, shared by preparation and actual dispatch."""
    system = (request["system_prompt"] + "\nReturn only JSON matching this schema:\n"
              + json.dumps(request["provider_output_schema"])
              + "\nReturn a JSON object, not a tool call.")
    version = request.get("generation_probe_version", "generation-capability-probe-v1")
    if version not in {"generation-capability-probe-v1", "generation-capability-probe-v2"}:
        raise ValueError("unsupported Generation probe wire version")
    return {"model": "deepseek-flash", "messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": request["user_prompt"]}],
        "response_format": {"type": "json_object"},
        "max_tokens": 16384 if version == "generation-capability-probe-v2" else 1024,
        "thinking": {"type": "disabled"}, "temperature": 1.6, "stream": False}


def output_text(provider: str, envelope: dict[str, Any]) -> str:
    if provider in {"deepseek", "qwen"}:
        choice = envelope["choices"][0]
        if choice.get("finish_reason") != "stop":
            raise ValueError("provider output did not finish normally")
        result = choice["message"]["content"]
    elif provider == "claude":
        if envelope.get("stop_reason") != "end_turn":
            raise ValueError("Claude output did not finish normally")
        result = "".join(p["text"] for p in envelope["content"] if p.get("type") == "text")
    else:
        candidate = envelope["candidates"][0]
        if candidate.get("finishReason") != "STOP":
            raise ValueError("Gemini output did not finish normally")
        result = "".join(
            p.get("text", "") for p in candidate["content"]["parts"] if not p.get("thought")
        )
    if not isinstance(result, str) or not result.strip():
        raise ValueError("provider returned no JSON output")
    return result


class NativeJSONProvider:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        provider: str,
        api_key: str,
        generation: dict[str, Any] | None = None,
        offline_capability_testing: bool = False,
        response_capture_version: int | None = None,
    ) -> None:
        self.client, self.provider, self.api_key = client, provider, api_key
        self.generation = dict(generation or {})
        self.offline_capability_testing = offline_capability_testing
        if response_capture_version not in (None, 2):
            raise ValueError("unsupported response capture version")
        self.response_capture_version = response_capture_version
        if offline_capability_testing and not isinstance(client._transport, httpx.MockTransport):
            raise ValueError("offline capability testing requires MockTransport")

    async def invoke(self, request: dict[str, Any]) -> RawExternalResponse:
        pricing_document = self.generation.get("pilot_pricing")
        system = (
            request["system_prompt"]
            + "\nReturn only JSON matching this schema:\n"
            + json.dumps(request.get("provider_output_schema", request["json_schema"]))
        )
        url = ENDPOINTS[self.provider]
        headers = {"Authorization": f"Bearer {self.api_key}"}
        body: dict[str, Any]
        if self.provider in {"deepseek", "qwen"}:
            body = {
                "model": request["model"],
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": request["user_prompt"]},
                ],
                "response_format": {"type": "json_object"},
                "max_tokens": 8192,
            }
            if self.provider == "qwen":
                body["enable_thinking"] = False
            elif self.generation:
                body["max_tokens"] = self.generation["max_tokens"]
                body["thinking"] = {"type": self.generation["thinking"]}
                if self.generation["thinking"] == "enabled":
                    body["reasoning_effort"] = self.generation["reasoning_effort"]
            if self.provider == "deepseek" and request.get("operation") is not None:
                params = request.get("generation_parameters")
                if (
                    not isinstance(params, dict)
                    or set(params)
                    - {
                        "max_tokens",
                        "thinking",
                        "reasoning_effort",
                        "timeout_seconds",
                        "pilot_pricing",
                    }
                    or not isinstance(params.get("max_tokens"), int)
                    or isinstance(params.get("max_tokens"), bool)
                    or not 1 <= params["max_tokens"] <= 384000
                    or params.get("thinking") not in {"enabled", "disabled"}
                ):
                    raise ValueError(
                        "live benchmark requires frozen DeepSeek generation parameters"
                    )
                if self.generation and any(
                    self.generation.get(key) != value for key, value in params.items()
                ):
                    raise ValueError(
                        "benchmark DeepSeek generation differs from provider configuration"
                    )
                pricing_document = params.get("pilot_pricing")
                body["max_tokens"] = params["max_tokens"]
                body["thinking"] = {"type": params["thinking"]}
                if params["thinking"] == "enabled":
                    effort = params.get("reasoning_effort")
                    if effort not in {"low", "high", "max"}:
                        raise ValueError("thinking benchmark requires frozen reasoning effort")
                    body["reasoning_effort"] = effort
                else:
                    body.pop("reasoning_effort", None)
            if pricing_document is not None:
                pricing = DeepSeekPilotPricing.model_validate(pricing_document)
                if pricing.model != request["model"] or self.provider != "deepseek":
                    raise ValueError("pilot pricing model/provider mismatch")
                if pricing.reserve_usd_per_call < pricing.minimum_reserve(body["max_tokens"]):
                    raise ValueError("pilot pricing reserve is below the wire output bound")
        elif self.provider == "claude":
            headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}
            body = {
                "model": request["model"],
                "max_tokens": 8192,
                "system": system,
                "messages": [{"role": "user", "content": request["user_prompt"]}],
            }
        else:
            url += "/" + quote(request["model"], safe="") + ":generateContent"
            headers = {"x-goog-api-key": self.api_key}
            body = {
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": request["user_prompt"]}]}],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "maxOutputTokens": 8192,
                },
            }
        baseline = request.get("baseline_generation_parameters")
        if baseline is not None:
            binding = request.get("input", {}).get("ideation_task_binding", {})
            if (request.get("skill_id") != "generation"
                    or binding.get("schema_id") != "GroundedGenerationResultV1"
                    or not isinstance(baseline, dict)
                    or baseline.get("temperature") != 1.6
                    or baseline.get("generation_input_hash") != binding.get("generation_input_hash")
                    or baseline.get("input_hash") != binding.get("input_hash")
                    or any(baseline.get(k) != binding.get(k)
                           for k in ("provider", "model", "api", "thinking_mode", "capability_id"))):
                raise ValueError("invalid frozen baseline Generation wire identity")
            # Fake-wire evidence is never a live provider capability approval.
            if (not self.offline_capability_testing or binding.get("provider") != "fake"
                    or binding.get("thinking_mode") != "disabled"
                    or self.provider not in {"deepseek", "qwen"}):
                raise ValueError("CAPABILITY_UNVERIFIED: baseline temperature wire blocked")
            body["temperature"] = 1.6
            encoded_wire = json.dumps(body, ensure_ascii=False, sort_keys=True,
                                      separators=(",", ":")).encode("utf-8")
            if (baseline.get("input_token_ceiling") != 16384
                    or baseline.get("input_byte_ceiling") != 65536
                    or baseline.get("token_estimator") != "utf8-bytes-upper-bound-v1"
                    or len(encoded_wire) > 16384 or len(encoded_wire) > 65536):
                raise ValueError("GENERATION_INPUT_LIMIT_EXCEEDED: conservative wire bound")
        output_contract = request.get("output_contract")
        result_contract = request.get("provider_result")
        if result_contract is not None:
            expected_mode = {
                "deepseek": "json_object",
                "qwen": "json_object",
                "gemini": "json_object",
                "claude": "prompted_json",
            }.get(self.provider)
            if result_contract.get("mode") != expected_mode:
                raise ValueError("provider result mode is unsupported by this API interface")
            if result_contract.get("schema") != request.get("provider_output_schema"):
                raise ValueError("provider result schema differs from normalized output contract")
            if result_contract.get("mode") == "json_object" and self.provider in {
                "deepseek",
                "qwen",
            }:
                body["response_format"] = {"type": "json_object"}
            elif result_contract.get("mode") == "json_object" and self.provider == "gemini":
                body["generationConfig"]["responseMimeType"] = "application/json"
            if self.provider in {"deepseek", "qwen"}:
                body["messages"][0]["content"] = system + "\nReturn a JSON object, not a tool call."
        if output_contract is not None:
            if self.provider != "deepseek":
                raise ValueError("strict output requires DeepSeek")
            skill_id = request.get("skill_id")
            if skill_id == "ranking":
                expected = ranking_output_spec(request.get("input", {}))
            elif skill_id in {"claim_decomposition", "claim_search_plan"}:
                expected = claim_output_spec(skill_id, request.get("input", {}))
            elif request.get("baseline_output_protocol") == "deepseek-candidate-slots-v1":
                operation = request.get("operation")
                count = request.get("candidate_count")
                if not isinstance(operation, str) or type(count) is not int:
                    raise ValueError("strict baseline requires a frozen operation and count")
                expected = baseline_output_spec(operation, count)
            elif request.get("baseline_output_protocol") == BASELINE_NORMALIZED_VERSION:
                operation = request.get("operation")
                if not isinstance(operation, str):
                    raise ValueError("normalized baseline requires a frozen operation")
                expected = normalized_baseline_output_spec(operation)
            else:
                expected = None
            if output_contract != expected or expected is None:
                raise ValueError("invalid strict scientific wire contract")
            url = output_contract["endpoint"]
            body.pop("response_format", None)
            body["messages"][0]["content"] = (
                request["system_prompt"] + "\n" + output_contract["instructions"]
            )
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": output_contract["tool_name"],
                        "strict": True,
                        "description": (
                            "Return this task's scientific comparison; no external action."
                            if skill_id == "ranking"
                            else "Submit this task's structured scientific output; no external action."
                        ),
                        "parameters": output_contract["parameters"],
                    },
                }
            ]
            body["tool_choice"] = output_contract["tool_choice"]
        probe = request.get("generation_probe_permit")
        if probe is not None or self.generation.get("generation_probe_permit") is not None:
            self._bind_generation_probe(request, body, probe)
        execution = request.get("effective_execution")
        if execution is not None:
            from co_scientist.domain.execution_config import (
                ProviderCapability,
                RoleRuntime,
                validate_wire,
            )
            from co_scientist.domain.pilot_pricing import effective_task_pricing
            from co_scientist.runtime.bounded_transport import (
                BoundedTransport,
                read_bounded_response,
            )

            if (self.generation or probe is not None or output_contract is not None
                    or self.provider != "deepseek" or self.client.follow_redirects):
                raise ValueError("effective runtime forbids legacy/provider overlays")
            cap = ProviderCapability.model_validate(execution["capability"])
            role = RoleRuntime.model_validate(execution["runtime"])
            binding = request["input"]["ideation_task_binding"]
            if (cap.model != request["model"] or execution["schema_id"] != request["schema_name"]
                    or any(binding[k] != getattr(cap, v) for k, v in (("model", "model"),
                        ("provider", "provider"), ("thinking_mode", "thinking"), ("capability_id", "capability_id")))):
                raise ValueError("effective provider/task capability mismatch")
            transport = self.client._transport
            inner = transport.inner if isinstance(transport, BoundedTransport) else transport
            single = ((execution.get("single_root_mode") == "single-root-dev-live-v1"
                or execution.get("live_execution_mode") in {"ideation-performance-dev-live-v1", "ideation-performance-dev-g3-v1"})
                and isinstance(transport, BoundedTransport) and transport.single_root_gate is not None
                and cap.provider == "deepseek" and cap.status == "CAPABILITY_UNVERIFIED")
            if not single and (cap.status != "OFFLINE_FAKE_ONLY" or cap.provider != "fake" or not isinstance(inner, httpx.MockTransport)):
                raise ValueError("CAPABILITY_UNVERIFIED: effective runtime remains offline-only")
            body["max_tokens"] = role.max_output_tokens
            body["thinking"] = {"type": cap.thinking}
            body["stream"] = False
            if role.reasoning_effort is not None:
                body["reasoning_effort"] = role.reasoning_effort
            if execution["role"] == "generation":
                if execution["temperature"] != 1.6 or cap.thinking != "disabled" or "temperature" not in cap.supported_sampling:
                    raise ValueError("unsupported scientific sampling parameter")
                body["temperature"] = execution["temperature"]
            elif execution["temperature"] is not None:
                raise ValueError("temperature cannot leak to other roles")
            wire = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
            context_plan = None
            if execution.get("continuous_policy") is not None:
                from co_scientist.runtime.context_planning import (
                    canonical,
                    persist_plan,
                    plan_context,
                )

                attempt = request["input"].get("continuous_attempt", {})
                body, context_plan = plan_context(body, execution,
                    attempt=request["input"]["ideation_task_binding"]["attempt"],
                    length_failures=attempt.get("length_failures", 0),
                    correction=attempt.get("correction"))
                wire = canonical(body)
                persist_plan(transport, context_plan)
            validate_wire(execution, wire)
            pricing_document = effective_task_pricing(execution).model_dump(mode="json")
            async with self.client.stream("POST", cap.endpoint, headers={**headers, "Content-Type": "application/json"},
                    content=wire, timeout=role.http_timeout_seconds,
                    extensions={"effective_execution": execution, **(
                        {"context_plan": context_plan} if context_plan is not None else {})}) as streamed:
                raw = await read_bounded_response(streamed, role.max_response_bytes)
                response = httpx.Response(streamed.status_code, content=raw, headers=streamed.headers,
                                          request=streamed.request)
                controlled = capture_http_response(raw, response.status_code, dict(response.headers))
            return self._interpret_response(response, pricing_document, role.max_output_tokens,
                                            controlled=controlled, expected_model=cap.model)
        if pricing_document is not None:
            pricing = DeepSeekPilotPricing.model_validate(pricing_document)
            if pricing.input_token_limit is not None:
                from co_scientist.runtime.bounded_transport import require_bounded_client

                require_bounded_client(self.client, pricing, body["max_tokens"])
        response = await self.client.post(url, headers=headers, json=body)
        controlled = capture_http_response(response.content, response.status_code,
                                           dict(response.headers))
        return self._interpret_response(response, pricing_document, body.get("max_tokens", 8192),
                                        controlled=controlled, expected_model=request["model"])

    def _bind_generation_probe(self, request: dict[str, Any], body: dict[str, Any],
                               supplied: Any) -> None:
        """Additive diagnostic path; it never relaxes the baseline fake-only guard."""
        from co_scientist.runtime.bounded_transport import BoundedTransport

        permit = generation_probe_permit(supplied)
        envelope = generation_probe_envelope(
            self.generation.get("generation_probe_envelope"))
        is_v2 = isinstance(envelope, GenerationCapabilityProbeEnvelopeV2)
        if is_v2 != isinstance(permit, GenerationProbePermitV2):
            raise ValueError("Generation probe envelope/permit version mismatch")
        binding = request.get("input", {}).get("ideation_task_binding", {})
        frozen_request = {k: v for k, v in request.items() if k != "generation_probe_permit"}
        request_hash = "sha256:" + hashlib.sha256(json.dumps(frozen_request,
            ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        from co_scientist.domain.claim_verification import scientific_hash

        if (self.provider != "deepseek" or self.response_capture_version != 2
                or self.offline_capability_testing
                or permit.model_dump(mode="json") != self.generation.get("generation_probe_permit")
                or permit.request_hash != request_hash
                or permit.envelope_hash != scientific_hash(envelope.model_dump(mode="json"))
                or permit.fixture_hash != binding.get("generation_input_hash")
                or (permit.run_id, permit.task_id, permit.attempt)
                    != (binding.get("run_id"), binding.get("task_id"), binding.get("attempt"))
                or request.get("skill_id") != "generation"
                or request.get("skill_version") != "0.3.0"
                or request.get("output_schema") != "GroundedGenerationResultV1"
                or binding.get("schema_version") != 1
                or binding.get("capability_id") != envelope.capability_id
                or binding.get("provider") != "deepseek"
                or binding.get("api") != "chat-completions-json-v1"
                or binding.get("thinking_mode") != "disabled"
                or body.get("model") != envelope.model
                or body.get("thinking") != {"type": "disabled"}
                or body.get("max_tokens") != envelope.max_tokens
                or self.generation.get("pilot_pricing") != envelope.pricing.model_dump(mode="json")
                or request.get("baseline_generation_parameters") is not None
                or request.get("operation") is not None or request.get("allowed_tools")
                or "tools" in body or "reasoning_effort" in body
                or request.get("output_contract") is not None):
            raise ValueError("Generation probe identity/configuration mismatch")
        transport = self.client._transport
        if not isinstance(transport, BoundedTransport):
            raise TypeError("Generation probe requires bounded transport")
        if permit.execution_root_hash != scientific_hash({"root": str(transport.root.parent.resolve())}):
            raise ValueError("Generation probe permit cannot move to a fresh execution ledger")
        if permit.mode == "OFFLINE_MOCK" and not isinstance(transport.inner, httpx.MockTransport):
            raise ValueError("offline Generation probe requires MockTransport")
        body.update(temperature=envelope.temperature, stream=False)
        if body != generation_probe_wire_body(request):
            raise ValueError("Generation probe actual wire differs from frozen diagnostic request")
        wire = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
        if is_v2 and (request.get("generation_probe_version") != envelope.version
                or not isinstance(permit, GenerationProbePermitV2)
                or permit.wire_hash != "sha256:" + hashlib.sha256(wire).hexdigest()
                or permit.call_id != permit.run_id + ":generation:attempt-1"):
            raise ValueError("Generation V2 wire/call identity mismatch")
        if len(wire) > envelope.max_wire_bytes or len(wire) + 4096 > envelope.max_input_tokens:
            raise ValueError("Generation probe wire/token ceiling exceeded")

    def parse_captured_response(self, capture: CapturedHTTPResponseV2,
                                request: dict[str, Any]) -> RawExternalResponse:
        """Offline interpretation of the original immutable response only."""
        params = request.get("generation_parameters", self.generation)
        if "effective_execution" in request:
            from co_scientist.domain.pilot_pricing import effective_task_pricing

            execution = request["effective_execution"]
            params = {"max_tokens": execution["runtime"]["max_output_tokens"],
                      "pilot_pricing": effective_task_pricing(execution).model_dump(mode="json")}
        response = httpx.Response(capture.status, content=capture.body,
            headers=dict(capture.headers), request=httpx.Request("POST", ENDPOINTS[self.provider]))
        return self._interpret_response(response, params.get("pilot_pricing"),
            params.get("max_tokens", 8192), controlled=True, expected_model=request["model"])

    def _interpret_response(self, response: httpx.Response, pricing_document: Any,
                            max_tokens: int, *, controlled: bool,
                            expected_model: str) -> RawExternalResponse:
        response.raise_for_status()
        # Extract accounting metadata only; scientific text is validated by SkillExecutor.
        envelope = response.json()
        if controlled and not isinstance(envelope, dict):
            raise ValueError("provider response envelope must be an object")
        usage = envelope.get("usage", envelope.get("usageMetadata", {})) or {}
        if controlled and not isinstance(usage, dict):
            raise ValueError("malformed provider usage")
        accounting: dict[str, Any] = {}
        input_count = usage.get(
            "input_tokens", usage.get("prompt_tokens", usage.get("promptTokenCount"))
        )
        output_count = usage.get(
            "output_tokens", usage.get("completion_tokens", usage.get("candidatesTokenCount"))
        )
        if (
            self.provider == "gemini"
            and output_count is not None
            and usage.get("thoughtsTokenCount") is not None
        ):
            output_count += usage["thoughtsTokenCount"]
        if input_count is not None:
            accounting["input_tokens"] = input_count
        if output_count is not None:
            accounting["output_tokens"] = output_count
        cached = usage.get(
            "prompt_cache_hit_tokens",
            usage.get(
                "cachedContentTokenCount",
                usage.get(
                    "cache_read_input_tokens",
                    (usage.get("prompt_tokens_details") or {}).get("cached_tokens"),
                ),
            ),
        )
        if cached is not None:
            accounting["cached_tokens"] = cached
        reasoning = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
        if self.provider == "gemini":
            reasoning = usage.get("thoughtsTokenCount", reasoning)
        if reasoning is not None:
            accounting["reasoning_tokens"] = reasoning
        if isinstance(envelope.get("model"), str):
            accounting["response_model"] = envelope["model"]
        elif isinstance(envelope.get("modelVersion"), str):
            accounting["response_model"] = envelope["modelVersion"]
        if controlled:
            if accounting.get("response_model") != expected_model:
                raise ValueError("provider response model mismatch")
            if any(type(accounting.get(k)) is not int or accounting[k] < 0
                   for k in ("input_tokens", "output_tokens")):
                raise ValueError("missing or invalid provider token usage")
            if cached is not None and (type(cached) is not int
                                      or not 0 <= cached <= accounting["input_tokens"]):
                raise ValueError("invalid cached token usage")
            if reasoning is not None and (type(reasoning) is not int
                                         or not 0 <= reasoning <= accounting["output_tokens"]):
                raise ValueError("invalid reasoning token usage")
            if pricing_document is None:
                raise ValueError("frozen pricing required for captured accounting")
            if self.provider != "deepseek":
                raise ValueError("captured accounting requires applicable provider pricing")
        if pricing_document is not None:
            pricing = DeepSeekPilotPricing.model_validate(pricing_document)
            if controlled and (pricing.model != expected_model
                    or accounting["output_tokens"] > max_tokens
                    or accounting["input_tokens"] > (pricing.input_token_limit
                                                      or pricing.max_context_tokens)):
                raise ValueError("provider accounting violates frozen pricing bounds")
            accounting["cost_usd"] = str(
                pricing.conservative_cost(
                    input_tokens=accounting.get("input_tokens"),
                    output_tokens=accounting.get("output_tokens"),
                    max_output_tokens=max_tokens,
                )
            )
            accounting["pricing_version"] = f"estimated:{pricing.version}"
            if self.generation.get("generation_probe_permit") is not None:
                accounting["probe_accounting"] = {
                    "version": "generation-probe-accounting-v1",
                    "basis": "peak-cache-miss-upper-estimate-not-invoice",
                    "actual_applicable_price": "UNKNOWN",
                    "invoice_cost": None,
                }
        return RawExternalResponse(
            body=response.content,
            mime_type="application/json",
            provider_response_id=envelope.get("id", envelope.get("responseId")),
            usage=accounting,
        )
