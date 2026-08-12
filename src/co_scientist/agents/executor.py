"""Execute typed runtime skills through the durable external-call lifecycle."""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from co_scientist.agents.payloads import resolve_output_schema
from co_scientist.agents.result import AgentExecutionContext, AgentResult
from co_scientist.ports.external_provider import ExternalProvider
from co_scientist.runtime.external_calls import ExternalCallRunner, prompt_hash
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
        if context.output_schema_id != manifest.output_schema:
            raise ValueError("execution context output schema does not match manifest")
        output_schema = resolve_output_schema(
            manifest.output_schema, context.output_schema_version
        )
        system_prompt = (skill_directory / manifest.prompt_path).read_text(encoding="utf-8")
        bound_prompt_hash = prompt_hash(system_prompt)
        if context.prompt_hash not in {None, bound_prompt_hash}:
            raise ValueError("execution context prompt hash does not match skill prompt")
        context = context.model_copy(update={"prompt_hash": bound_prompt_hash})
        request: dict[str, Any] = {
            "skill_id": manifest.id,
            "skill_version": manifest.version,
            "system_prompt": system_prompt,
            "input_schema": manifest.input_schema,
            "output_schema": manifest.output_schema,
            "allowed_tools": list(manifest.allowed_tools),
            "input": inputs,
        }

        def validate_payload(raw: bytes) -> Mapping[str, Any]:
            decoded = _decode_payload(raw)
            validated = output_schema.model_validate(decoded)
            if (
                getattr(validated, "research_plan_version", None)
                != context.research_plan_version
            ):
                raise ValueError(
                    "payload research plan version does not match execution context"
                )
            return validated.model_dump(mode="json")

        return await self.runner.execute(
            call_id=call_id,
            request=request,
            provider=self.provider,
            validator=validate_payload,
            context=context,
        )
