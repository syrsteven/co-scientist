"""Execute typed runtime skills through the durable external-call lifecycle."""

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Literal

from co_scientist.adapters.literature.pubmed import parse_pubmed_records
from co_scientist.agents.payloads import resolve_output_schema
from co_scientist.agents.result import AgentExecutionContext, AgentResult
from co_scientist.domain.task import TaskLeaseFence
from co_scientist.ports.external_provider import ExternalProvider
from co_scientist.runtime.external_calls import ExternalCallRunner, prompt_hash
from co_scientist.skills.loader import load_skill, resolve_core_skill_contract


def _reject_non_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def _decode_payload(raw: bytes) -> Mapping[str, Any]:
    value = json.loads(raw, parse_constant=_reject_non_json_constant)
    if not isinstance(value, Mapping):
        raise TypeError("skill response must be a JSON object")
    return dict(value)


def _openai_output_text(envelope: Mapping[str, Any]) -> str:
    direct = envelope.get("output_text")
    if isinstance(direct, str):
        return direct
    output = envelope.get("output")
    if not isinstance(output, list):
        raise ValueError(  # noqa: TRY004 - malformed provider value, not caller type
            "OpenAI response has no structured output_text"
        )
    fragments: list[str] = []
    for item in output:
        if not isinstance(item, Mapping):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        fragments.extend(
            str(part["text"])
            for part in content
            if isinstance(part, Mapping)
            and part.get("type") == "output_text"
            and isinstance(part.get("text"), str)
        )
    if not fragments:
        raise ValueError("OpenAI response has no structured output_text")
    return "".join(fragments)


def build_skill_request(
    *,
    skill_directory: Path,
    inputs: dict[str, Any],
    model: str,
) -> dict[str, Any]:
    """Build the one canonical request shared by Replay and OpenAI."""

    manifest = load_skill(skill_directory)
    output_schema = resolve_output_schema(manifest.output_schema, 1)
    system_prompt = (skill_directory / manifest.prompt_path).read_text(encoding="utf-8")
    user_document = {
        "input_schema": manifest.input_schema,
        "allowed_tools": list(manifest.allowed_tools),
        "input": inputs,
    }
    return {
        "model": model,
        "system_prompt": system_prompt,
        "user_prompt": json.dumps(
            user_document,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
        "json_schema": output_schema.model_json_schema(),
        "schema_name": manifest.output_schema,
        "skill_id": manifest.id,
        "skill_version": manifest.version,
        "input_schema": manifest.input_schema,
        "output_schema": manifest.output_schema,
        "allowed_tools": list(manifest.allowed_tools),
        "input": inputs,
    }


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
        reservation_id: str,
        fence: TaskLeaseFence,
        write_guard: Callable[[], None] | None = None,
    ) -> AgentResult:
        manifest = load_skill(skill_directory)
        resolve_core_skill_contract(
            skill_id=context.skill_id,
            skill_version=context.skill_version,
            output_schema_id=context.output_schema_id,
        )
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
        request = build_skill_request(
            skill_directory=skill_directory,
            inputs=inputs,
            model=context.model_or_tool,
        )

        def validate_payload(raw: bytes) -> Mapping[str, Any]:
            validation_body = raw
            if context.provider == "openai":
                envelope = _decode_payload(raw)
                validation_body = _openai_output_text(envelope).encode("utf-8")
            decoded = _decode_payload(validation_body)
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
            reservation_id=reservation_id,
            fence=fence,
            write_guard=write_guard,
        )


class LiteratureToolExecutor:
    """Execute one configured PubMed operation through the raw-first call fence."""

    def __init__(self, runner: ExternalCallRunner, provider: ExternalProvider) -> None:
        self.runner = runner
        self.provider = provider

    async def execute(
        self,
        *,
        call_id: str,
        operation: Literal["search", "summary"],
        inputs: dict[str, Any],
        context: AgentExecutionContext,
        reservation_id: str,
        fence: TaskLeaseFence,
        write_guard: Callable[[], None] | None = None,
    ) -> AgentResult:
        query = inputs.get("query")
        if not isinstance(query, str) or not query:
            raise ValueError("literature task requires a retrieval query")
        request: dict[str, Any] = {"query": query}
        if operation == "search":
            request["limit"] = int(inputs.get("limit", 10))
        else:
            pmids = inputs.get("pmids")
            if not isinstance(pmids, list) or not pmids:
                raise ValueError("literature summary task requires PMIDs")
            request["pmids"] = [str(pmid) for pmid in pmids]

        def validate_payload(raw: bytes) -> Mapping[str, Any]:
            if operation == "search":
                document = _decode_payload(raw)
                result = document.get("esearchresult")
                if not isinstance(result, Mapping):
                    raise ValueError("PubMed search response is malformed")
                pmids = result.get("idlist")
                if (
                    not isinstance(pmids, list)
                    or any(not isinstance(pmid, str) or not pmid for pmid in pmids)
                ):
                    raise ValueError("PubMed search response is malformed")
                overview = {"operation": "search", "query": query, "pmids": pmids}
                feedback = "PubMed search raw response persisted before PMID parsing."
            else:
                documents = parse_pubmed_records(
                    raw,
                    query=query,
                    raw_artifact_ref=f"external-call:{call_id}",
                )
                overview = {
                    "operation": "summary",
                    "query": query,
                    "source_documents": [
                        document.model_dump(mode="json") for document in documents
                    ],
                }
                feedback = "PubMed summary raw response persisted before source parsing."
            return {
                "schema_version": 1,
                "research_plan_version": context.research_plan_version,
                "source_content_hashes": {},
                "system_feedback": [feedback],
                "overview": json.dumps(
                    overview,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                "coverage_gaps": [],
                "safety_direction_check": "insufficient_evidence",
            }

        return await self.runner.execute(
            call_id=call_id,
            request=request,
            provider=self.provider,
            validator=validate_payload,
            context=context,
            reservation_id=reservation_id,
            fence=fence,
            write_guard=write_guard,
        )
