"""Deterministic FIFO LLM provider for tests and local scenarios."""

from collections import deque
from typing import Any

from co_scientist.ports.external_provider import RawExternalResponse


class FakeLLMProvider:
    """Return queued bytes without interpreting or persisting them."""

    def __init__(self, responses: list[bytes]) -> None:
        self.responses = deque(responses)
        self.call_count = 0

    async def invoke(self, request: dict[str, Any]) -> RawExternalResponse:
        self.call_count += 1
        return RawExternalResponse(
            body=self.responses.popleft(),
            mime_type="application/json",
            provider_response_id=f"fake-{self.call_count}",
        )
