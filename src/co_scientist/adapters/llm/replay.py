"""Deterministic fingerprint-addressed LLM replay provider."""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from co_scientist.agents.executor import build_skill_request
from co_scientist.agents.payloads import resolve_output_schema
from co_scientist.ports.external_provider import RawExternalResponse
from co_scientist.runtime.external_calls import request_fingerprint
from co_scientist.skills.loader import core_skill_directory, load_skill


class ReplayMiss(KeyError):
    """Raised when no recorded response matches the canonical request."""


class ReplayResponseRecord(BaseModel):
    """One typed request/response record in a production replay resource."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    skill_id: str
    inputs: dict[str, Any]
    response: dict[str, Any]


class ReplayResponseResource(BaseModel):
    """Versioned, immutable replay-resource envelope."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    replay_version: int
    model: str
    responses: tuple[ReplayResponseRecord, ...]


class ReplayLLMProvider:
    """Return recorded raw bytes selected by canonical request fingerprint."""

    def __init__(
        self,
        responses_by_fingerprint: Mapping[str, bytes | RawExternalResponse],
    ) -> None:
        self.responses = dict(responses_by_fingerprint)

    @classmethod
    def from_file(cls, path: Path) -> "ReplayLLMProvider":
        resource = ReplayResponseResource.model_validate_json(path.read_text(encoding="utf-8"))
        if resource.replay_version != 1:
            raise ValueError("unsupported replay response version")
        if not resource.model or not resource.responses:
            raise TypeError("replay response resource is malformed")
        responses: dict[str, RawExternalResponse] = {}
        for index, record in enumerate(resource.responses):
            skill_directory = core_skill_directory(record.skill_id)
            manifest = load_skill(skill_directory)
            schema = resolve_output_schema(manifest.output_schema, 1)
            try:
                schema.model_validate(record.response)
            except ValidationError as error:
                raise ValueError(
                    f"typed replay response is invalid for {record.skill_id}"
                ) from error
            request = build_skill_request(
                skill_directory=skill_directory,
                inputs=record.inputs,
                model=resource.model,
            )
            fingerprint = request_fingerprint(request)
            if fingerprint in responses:
                raise ValueError("replay response fingerprints must be unique")
            responses[fingerprint] = RawExternalResponse(
                body=json.dumps(
                    record.response,
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
