"""Deterministic provider syntax normalization, before scientific validation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from co_scientist.adapters.llm.output_errors import ProviderSchemaError, ProviderSyntaxError

DomainObjectT = TypeVar("DomainObjectT")


class ProviderNormalizedResult(BaseModel):
    """Provider-shaped content normalized without assigning scientific meaning."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str
    operation: str
    source_format: Literal["json_text", "result_tool"]
    payload: Any
    result_tool_name: str | None = None
    result_tool_call_count: int = 0
    resolution_audit: dict[str, Any] = Field(default_factory=dict)

    @property
    def audit(self) -> dict[str, Any]:
        """Short read-only alias used by adapters and diagnostic tooling."""
        return self.resolution_audit


@dataclass(frozen=True)
class DomainValidator(Generic[DomainObjectT]):
    """Explicit deterministic boundary from normalized provider value to domain value."""

    validate_value: Callable[[ProviderNormalizedResult], DomainObjectT]

    def validate(self, result: ProviderNormalizedResult) -> DomainObjectT:
        return self.validate_value(result)


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("provider output has duplicate JSON keys")
        value[key] = item
    return value


def _hash(value: Any) -> str:
    canonical = json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _subsumes(larger: Any, smaller: Any) -> bool:
    if isinstance(smaller, dict):
        return isinstance(larger, dict) and all(
            key in larger and _subsumes(larger[key], value) for key, value in smaller.items()
        )
    # Lists and scalar values are atomic. Never merge scientific arrays.
    return type(larger) is type(smaller) and larger == smaller


def _tool_arguments(text: str) -> tuple[dict[str, Any], bool]:
    try:
        value = json.loads(text, object_pairs_hook=_pairs, parse_constant=_bad_constant)
    except (json.JSONDecodeError, ValueError) as error:
        try:
            value, end = json.JSONDecoder(
                object_pairs_hook=_pairs, parse_constant=_bad_constant
            ).raw_decode(text)
        except (ValueError, TypeError) as inner:
            raise ProviderSyntaxError("malformed result tool arguments") from inner
        if text[end:] != "}" or not isinstance(value, dict):
            raise ProviderSyntaxError("malformed result tool arguments") from error
        return value, True
    if not isinstance(value, dict):
        raise ProviderSchemaError("result tool arguments must be a JSON object")
    return value, False


def _bad_constant(value: str) -> None:
    raise ValueError(f"provider JSON has invalid numeric constant: {value}")


def _resolve_calls(
    calls: list[Any], result_tool_name: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not 1 <= len(calls) <= 8:
        raise ProviderSchemaError("ambiguous_multiple_result_tools")
    payloads: list[dict[str, Any]] = []
    repairs = []
    for index, call in enumerate(calls):
        function = (
            call.get("function")
            if isinstance(call, dict) and call.get("type") == "function"
            else None
        )
        if not isinstance(function, dict) or function.get("name") != result_tool_name:
            raise ProviderSchemaError("ambiguous_multiple_result_tools: wrong result tool")
        text = function.get("arguments")
        if not isinstance(text, str):
            raise ProviderSchemaError("result tool arguments must be JSON text")
        payload, repaired = _tool_arguments(text)
        payloads.append(payload)
        repairs.append(
            {
                "call_index": index,
                "raw_arguments_sha256": "sha256:"
                + hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "removed_exactly_one_trailing_right_brace": repaired,
            }
        )
    hashes = [_hash(payload) for payload in payloads]
    maximal = {
        hashes[i]
        for i, payload in enumerate(payloads)
        if all(_subsumes(payload, other) for other in payloads)
    }
    if len(maximal) != 1:
        raise ProviderSchemaError(
            "ambiguous_multiple_result_tools: conflicting or incomparable payloads"
        )
    selected_hash = next(iter(maximal))
    # Identical maximal payloads are canonical duplicates; their values are equivalent.
    selected = next(
        payload for payload, digest in zip(payloads, hashes, strict=True) if digest == selected_hash
    )
    relationships = [
        {"subsumed_call_index": i, "by_call_index": j}
        for i, smaller in enumerate(payloads)
        for j, larger in enumerate(payloads)
        if i != j and _subsumes(larger, smaller)
    ]
    audit = {
        "result_tool_call_count": len(calls),
        "canonical_payload_hashes": hashes,
        "subsumption_relationships": relationships,
        "selected_maximal_payload_hash": selected_hash,
        "collapse_reason": (
            "single_result_tool"
            if len(calls) == 1
            else "identical_result_tools"
            if len(set(hashes)) == 1
            else "unique_compatible_maximal_superset"
        ),
        "syntax_repairs": repairs,
    }
    return selected, audit


def _parse_json_text(content: str) -> Any:
    try:
        return json.loads(content, object_pairs_hook=_pairs, parse_constant=_bad_constant)
    except (json.JSONDecodeError, ValueError) as error:
        raise ProviderSyntaxError("provider result content is not valid JSON") from error


def _responses_text(envelope: dict[str, Any]) -> str:
    direct = envelope.get("output_text")
    if isinstance(direct, str):
        return direct
    output = envelope.get("output")
    if not isinstance(output, list):
        raise ProviderSchemaError("Responses API envelope has no output text")
    fragments: list[str] = []
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        fragments.extend(
            part["text"]
            for part in content
            if isinstance(part, dict)
            and part.get("type") == "output_text"
            and isinstance(part.get("text"), str)
        )
    if not fragments:
        raise ProviderSchemaError("Responses API envelope has no output text")
    return "".join(fragments)


def _provider_text(provider: str, envelope: dict[str, Any]) -> str:
    if provider == "openai":
        return _responses_text(envelope)
    if provider in {"deepseek", "qwen"}:
        choices = envelope.get("choices")
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            raise ProviderSchemaError("provider response requires exactly one choice")
        choice = choices[0]
        if choice.get("finish_reason") != "stop":
            raise ProviderSchemaError("provider result did not finish normally")
        message = choice.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise ProviderSchemaError("provider response has no text result")
        return content
    if provider == "claude":
        if envelope.get("stop_reason") != "end_turn":
            raise ProviderSchemaError("Claude result did not finish normally")
        content = envelope.get("content")
        if not isinstance(content, list):
            raise ProviderSchemaError("Claude result has no content array")
        return "".join(
            item["text"]
            for item in content
            if isinstance(item, dict)
            and item.get("type") == "text"
            and isinstance(item.get("text"), str)
        )
    if provider == "gemini":
        candidates = envelope.get("candidates")
        if not isinstance(candidates, list) or len(candidates) != 1:
            raise ProviderSchemaError("Gemini result requires exactly one candidate")
        candidate = candidates[0]
        if not isinstance(candidate, dict) or candidate.get("finishReason") != "STOP":
            raise ProviderSchemaError("Gemini result did not finish normally")
        content = candidate.get("content")
        parts = content.get("parts") if isinstance(content, dict) else None
        if not isinstance(parts, list):
            raise ProviderSchemaError("Gemini result has no content parts")
        return "".join(
            part.get("text", "")
            for part in parts
            if isinstance(part, dict)
            and not part.get("thought")
            and isinstance(part.get("text", ""), str)
        )
    raise ProviderSchemaError(f"unsupported provider result envelope: {provider}")


def normalize_provider_output(
    raw: bytes, *, provider: str, operation: str, result_tool_name: str | None = None
) -> ProviderNormalizedResult:
    """Parse JSON text or resolve same-name tool calls without domain assumptions."""

    try:
        envelope = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_bad_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ProviderSyntaxError("provider response envelope is not valid JSON") from error
    if not isinstance(envelope, dict):
        raise ProviderSchemaError("provider response envelope must be an object")
    choices = envelope.get("choices")
    if choices is None:
        content = _provider_text(provider, envelope)
        if not content.strip():
            raise ProviderSchemaError("provider returned empty result content")
        payload = _parse_json_text(content)
        if not isinstance(payload, dict | list):
            raise ProviderSchemaError("provider JSON result must be an object or array")
        return ProviderNormalizedResult(
            provider=provider,
            operation=operation,
            source_format="json_text",
            payload=payload,
            resolution_audit={
                "collapse_reason": "json_text",
                "provider_result_mode": "provider_native",
            },
        )
    if not isinstance(choices, list) or len(choices) != 1:
        raise ProviderSchemaError("provider response requires exactly one choice")
    choice = choices[0]
    if not isinstance(choice, dict):
        raise ProviderSchemaError("provider response choice must be an object")
    message = choice.get("message")
    if not isinstance(message, dict):
        raise ProviderSchemaError("provider response message must be an object")
    message_content: Any = message.get("content")
    calls = message.get("tool_calls")
    if calls is not None and not isinstance(calls, list):
        raise ProviderSchemaError("provider tool_calls must be an array")
    calls = calls or []
    if calls:
        if choice.get("finish_reason") != "tool_calls":
            raise ProviderSchemaError("result tool calls require tool_calls finish")
        if result_tool_name is None:
            raise ProviderSchemaError("pure result contract rejects action/tool-call output")
        payload, audit = _resolve_calls(calls, result_tool_name)
        return ProviderNormalizedResult(
            provider=provider,
            operation=operation,
            source_format="result_tool",
            payload=payload,
            result_tool_name=result_tool_name,
            result_tool_call_count=len(calls),
            resolution_audit=audit,
        )
    if choice.get("finish_reason") != "stop":
        raise ProviderSchemaError("JSON text output requires normal stop finish")
    if not isinstance(message_content, str) or not message_content.strip():
        raise ProviderSchemaError("provider returned no JSON text")
    payload = _parse_json_text(message_content)
    if not isinstance(payload, dict | list):
        raise ProviderSchemaError("provider JSON text must contain an object or array")
    return ProviderNormalizedResult(
        provider=provider,
        operation=operation,
        source_format="json_text",
        payload=payload,
        result_tool_name=None,
        result_tool_call_count=0,
        resolution_audit={"collapse_reason": "json_text"},
    )
