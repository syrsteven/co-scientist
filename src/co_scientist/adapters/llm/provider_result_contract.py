"""Provider capabilities for pure structured results, separate from action tools."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ProviderResultMode(StrEnum):
    JSON_SCHEMA = "json_schema"
    JSON_OBJECT = "json_object"
    PROMPTED_JSON = "prompted_json"


@dataclass(frozen=True)
class ProviderCapability:
    provider: str
    interface: str
    result_mode: ProviderResultMode
    schema_constrained: bool
    action_tool_calling: bool
    implemented: bool


_CAPABILITIES = {
    ("deepseek", "chat_completions"): ProviderCapability(
        "deepseek", "chat_completions", ProviderResultMode.JSON_OBJECT, False, True, True
    ),
    ("deepseek", "responses"): ProviderCapability(
        "deepseek", "responses", ProviderResultMode.JSON_SCHEMA, True, True, False
    ),
    ("openai", "responses"): ProviderCapability(
        "openai", "responses", ProviderResultMode.JSON_SCHEMA, True, True, True
    ),
    ("qwen", "chat_completions"): ProviderCapability(
        "qwen", "chat_completions", ProviderResultMode.JSON_OBJECT, False, True, True
    ),
    ("gemini", "generate_content"): ProviderCapability(
        "gemini", "generate_content", ProviderResultMode.JSON_OBJECT, False, True, True
    ),
    ("claude", "messages"): ProviderCapability(
        "claude", "messages", ProviderResultMode.PROMPTED_JSON, False, True, True
    ),
    ("replay", "fixture"): ProviderCapability(
        "replay", "fixture", ProviderResultMode.PROMPTED_JSON, False, False, True
    ),
}


def capability_for(provider: str, *, interface: str | None = None) -> ProviderCapability:
    """Return the explicit output mode for one provider API interface.

    A JSON-object result mode guarantees JSON syntax only. It does not claim the
    provider constrains output to the supplied schema; local validation remains
    authoritative. Action tool capability is independent of result mode.
    """

    defaults = {
        "deepseek": "chat_completions",
        "openai": "responses",
        "qwen": "chat_completions",
        "gemini": "generate_content",
        "claude": "messages",
        "replay": "fixture",
    }
    selected = interface or defaults.get(provider)
    if selected is None:
        raise ValueError(f"unsupported provider result interface: {provider}/{selected}")
    capability = _CAPABILITIES.get((provider, selected))
    if capability is None:
        raise ValueError(f"unsupported provider result interface: {provider}/{selected}")
    return capability


def provider_result_request(
    provider: str,
    schema: dict[str, Any],
    *,
    interface: str | None = None,
    schema_name: str = "agent_result",
) -> dict[str, Any]:
    """Build provider-facing result config without making it a domain schema."""

    capability = capability_for(provider, interface=interface)
    if not capability.implemented:
        raise ValueError(
            f"provider result interface is documented but not implemented: "
            f"{provider}/{capability.interface}"
        )
    return {
        "mode": capability.result_mode.value,
        "schema_constrained": capability.schema_constrained,
        "schema_name": schema_name,
        "schema": schema,
    }
