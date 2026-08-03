"""Execute typed runtime skills through the durable external-call lifecycle."""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from co_scientist.agents.result import AgentExecutionContext, AgentResult
from co_scientist.ports.external_provider import ExternalProvider
from co_scientist.runtime.external_calls import ExternalCallRunner
from co_scientist.skills.loader import load_skill


def _reject_non_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def _decode_payload(raw: bytes) -> Mapping[str, Any]:
    value = json.loads(raw, parse_constant=_reject_non_json_constant)
    if not isinstance(value, Mapping):
        raise TypeError("skill response must be a JSON object")
    return dict(value)


class SkillExecutor:
    """Bind a skill manifest to one raw-first external call."""

    def __init__(self, runner: ExternalCallRunner, provider: ExternalProvider) -> None:
        self.runner = runner
        self.provider = provider

    async def execute(
        self,
        *,
        call_id: str,
        skill_directory: Path,
        inputs: dict[str, Any],
        context: AgentExecutionContext,
    ) -> AgentResult:
        manifest = load_skill(skill_directory)
        if context.skill_id != manifest.id:
            raise ValueError("execution context skill does not match manifest")
        if context.skill_version != manifest.version:
            raise ValueError("execution context skill version does not match manifest")
        if context.output_schema_version != 1:
            raise ValueError("Core Preview skill output schema version must be 1")
        request: dict[str, Any] = {
            "skill_id": manifest.id,
            "skill_version": manifest.version,
            "system_prompt": (skill_directory / manifest.prompt_path).read_text(encoding="utf-8"),
            "input_schema": manifest.input_schema,
            "output_schema": manifest.output_schema,
            "allowed_tools": list(manifest.allowed_tools),
            "input": inputs,
        }
        return await self.runner.execute(
            call_id=call_id,
            request=request,
            provider=self.provider,
            validator=_decode_payload,
            context=context,
        )
