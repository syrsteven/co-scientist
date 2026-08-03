"""Deterministic fingerprint-addressed LLM replay provider."""

from typing import Any

from co_scientist.ports.external_provider import RawExternalResponse
from co_scientist.runtime.external_calls import request_fingerprint


class ReplayMiss(KeyError):
    """Raised when no recorded response matches the canonical request."""


class ReplayLLMProvider:
    """Return recorded raw bytes selected by canonical request fingerprint."""

    def __init__(self, responses_by_fingerprint: dict[str, bytes]) -> None:
        self.responses = responses_by_fingerprint

    async def invoke(self, request: dict[str, Any]) -> RawExternalResponse:
        fingerprint = request_fingerprint(request)
        if fingerprint not in self.responses:
            raise ReplayMiss(fingerprint)
        return RawExternalResponse(
            body=self.responses[fingerprint],
            mime_type="application/json",
            provider_response_id=f"replay-{fingerprint[:12]}",
        )
