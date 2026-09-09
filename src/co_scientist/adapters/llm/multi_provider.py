"""Native HTTP adapters; domain output is decoded only after raw persistence."""

import json
from typing import Any
from urllib.parse import quote

import httpx

from co_scientist.ports.external_provider import RawExternalResponse

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
    def __init__(self, client: httpx.AsyncClient, *, provider: str, api_key: str) -> None:
        self.client, self.provider, self.api_key = client, provider, api_key

    async def invoke(self, request: dict[str, Any]) -> RawExternalResponse:
        system = (
            request["system_prompt"]
            + "\nReturn only JSON matching this schema:\n"
            + json.dumps(request["json_schema"])
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
        response = await self.client.post(url, headers=headers, json=body)
        response.raise_for_status()
        # Extract accounting metadata only; scientific text is validated by SkillExecutor.
        envelope = response.json()
        usage = envelope.get("usage", envelope.get("usageMetadata", {}))
        return RawExternalResponse(
            body=response.content,
            mime_type="application/json",
            provider_response_id=envelope.get("id", envelope.get("responseId")),
            usage={
                "input_tokens": usage.get(
                    "input_tokens", usage.get("prompt_tokens", usage.get("promptTokenCount", 0))
                ),
                "output_tokens": usage.get(
                    "output_tokens",
                    usage.get("completion_tokens", usage.get("candidatesTokenCount", 0)),
                )
                + (usage.get("thoughtsTokenCount", 0) if self.provider == "gemini" else 0),
            },
        )
