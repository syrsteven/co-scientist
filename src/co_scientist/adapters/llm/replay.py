"""Deterministic fingerprint-addressed LLM replay provider."""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from co_scientist.agents.executor import build_skill_request
from co_scientist.ports.external_provider import RawExternalResponse
from co_scientist.runtime.external_calls import request_fingerprint


class ReplayMiss(KeyError):
    """Raised when no recorded response matches the canonical request."""


class ReplayLLMProvider:
    """Return recorded raw bytes selected by canonical request fingerprint."""

    def __init__(
        self,
        responses_by_fingerprint: Mapping[str, bytes | RawExternalResponse],
    ) -> None:
        self.responses = dict(responses_by_fingerprint)

    @classmethod
    def from_file(cls, path: Path) -> "ReplayLLMProvider":
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("replay_version") != 1:
            raise ValueError("unsupported replay response version")
        model = document.get("model")
        records = document.get("responses")
        if not isinstance(model, str) or not isinstance(records, list):
            raise TypeError("replay response resource is malformed")
        responses: dict[str, RawExternalResponse] = {}
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                raise TypeError("replay response record is malformed")
            skill_id = record.get("skill_id")
            inputs = record.get("inputs")
            response = record.get("response")
            if (
                not isinstance(skill_id, str)
                or not isinstance(inputs, dict)
                or not isinstance(response, dict)
            ):
                raise TypeError("replay response record is malformed")
            request = build_skill_request(
                skill_directory=Path("skills") / skill_id,
                inputs=inputs,
                model=model,
            )
            fingerprint = request_fingerprint(request)
            if fingerprint in responses:
                raise ValueError("replay response fingerprints must be unique")
            responses[fingerprint] = RawExternalResponse(
                body=json.dumps(
                    response,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8"),
                mime_type="application/json",
                provider_response_id=f"replay-record-{index + 1}",
                usage={
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "cost_usd": "0",
                    "pricing_version": "replay-v1",
                },
            )
        return cls(responses)

    async def invoke(self, request: dict[str, Any]) -> RawExternalResponse:
        fingerprint = request_fingerprint(request)
        response = self.responses.get(fingerprint)
        if response is None:
            raise ReplayMiss(fingerprint)
        if isinstance(response, RawExternalResponse):
            return response
        return RawExternalResponse(
            body=response,
            mime_type="application/json",
            provider_response_id=f"replay-{fingerprint[:12]}",
        )
