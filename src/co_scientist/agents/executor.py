"""Execute typed runtime skills through the durable external-call lifecycle."""

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import ValidationError

from co_scientist.adapters.literature.pubmed import parse_pubmed_abstracts, parse_pubmed_records
from co_scientist.adapters.llm.output_errors import (
    DomainValidationError,
    ScientificValidationFailure,
)
from co_scientist.adapters.llm.provider_output import DomainValidator, normalize_provider_output
from co_scientist.adapters.llm.provider_result_contract import provider_result_request
from co_scientist.agents.payloads import (
    ClaimDecompositionProviderOutputV3,
    ClaimDecompositionResultV2,
    ClaimVerificationResultV2,
    CoreScientificResultV1,
    MetaReviewResultV1,
    output_schema_version,
    resolve_output_schema,
)
from co_scientist.agents.result import AgentExecutionContext, AgentResult
from co_scientist.domain.claim_verification import (
    ClaimDecompositionOutputPolicy,
    ClaimVerificationPolicy,
)
from co_scientist.domain.ideation_prerequisites import RESULT_MODELS, validate_prerequisite_inputs
from co_scientist.domain.pilot_output import (
    CLAIM_NORMALIZED_VERSION,
    CLAIM_PROVENANCE_V2,
    CLAIM_PROVIDER_JSON_VERSION,
    CLAIM_VERIFICATION_V2,
    claim_output_spec,
    claim_verification_output_spec,
    decode_claim_output,
    normalize_claim_output_v2,
    normalize_claim_output_v3,
    normalize_claim_result,
    normalize_claim_verification_output_v2,
)
from co_scientist.domain.ranking_output import (
    JSON_RANKING_VERSION,
    decode_provider_ranking,
    decode_strict_ranking,
    ranking_output_spec,
)
from co_scientist.domain.source_units import source_units_for_content, source_units_v2_for_content
from co_scientist.domain.task import TaskLeaseFence
from co_scientist.ports.external_provider import ExternalProvider
from co_scientist.runtime.external_calls import ExternalCallRunner, prompt_hash
from co_scientist.runtime.task_payload import validate_result_task_binding
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
    skill_version: str | None = None,
) -> dict[str, Any]:
    """Build the one canonical request shared by Replay and OpenAI."""

    selected_version = skill_version or _requested_skill_version(inputs, skill_directory.name)
    binding = (validate_prerequisite_inputs(inputs)
               if "ideation_task_binding" in inputs else None)
    manifest = load_skill(skill_directory, skill_version=selected_version,
                          phase=binding.phase if binding else None)
    if binding is not None and manifest.output_schema not in RESULT_MODELS:
        raise ValueError("prerequisite binding cannot select a historical contract")
    if manifest.output_schema in RESULT_MODELS:
        if binding is None or (binding.skill_id, binding.skill_version, binding.schema_id,
                               binding.model) != (manifest.id, manifest.version,
                                                  manifest.output_schema, model):
            raise ValueError("prerequisite request binding does not match selected contract")
        system_prompt = (skill_directory / manifest.prompt_path).read_text(encoding="utf-8")
        if binding.prompt_hash != prompt_hash(system_prompt):
            raise ValueError("prerequisite prompt binding mismatch")
    lineage_claim = inputs.get("claim_decomposition_contract_version") == (
        "claim-provenance-lineage-v3"
    )
    if lineage_claim != (manifest.output_schema == "ClaimDecompositionResultV3"):
        raise ValueError("lineage claim contract requires exact V3 skill version")
    if lineage_claim and inputs.get("claim_output_protocol") is not None:
        raise ValueError("lineage claim contract cannot use an older output protocol")
    lineage_evolution = inputs.get("evolution_output_contract_version") == (
        "population-evolution-lineage-v2"
    )
    if lineage_evolution != (manifest.output_schema == "PopulationEvolutionResultV2"):
        raise ValueError("lineage Evolution contract requires exact V2 skill version")
    schema_version = output_schema_version(manifest.output_schema)
    output_schema = resolve_output_schema(manifest.output_schema, schema_version)
    system_prompt = (skill_directory / manifest.prompt_path).read_text(encoding="utf-8")
    user_document: dict[str, Any] = {
        "input_schema": manifest.input_schema,
        "allowed_tools": list(manifest.allowed_tools),
        "input": inputs,
    }
    if "effective_execution" in inputs:
        # Local execution authority is not model-authored scientific context.
        user_document["input"] = {k: v for k, v in inputs.items()
                                  if k not in {"effective_execution", "continuous_attempt"}}
        if inputs["effective_execution"].get("continuous_policy") is not None:
            # Model-visible science is unchanged; local binding, hashes and
            # authority remain in the durable task and full provider request.
            user_document["input"].pop("ideation_task_binding", None)
            if binding is not None and binding.schema_id in {"GroundedGenerationResultV1", "BaselineEvolutionResultV1"}:
                user_document["proposal_scope"] = {"slot_id": binding.slot_id,
                    "redesign_count": binding.redesign_count,
                    "instruction": "Propose fresh hypothesis/content identifiers unique to this slot and distinct from parent identifiers. Do not return binding or authority fields."}
    if (
        manifest.id == "claim_decomposition"
        and inputs.get("claim_decomposition_output") is not None
    ):
        output_policy = ClaimDecompositionOutputPolicy.model_validate(
            inputs["claim_decomposition_output"]
        )
        verification_policy = ClaimVerificationPolicy.model_validate(
            inputs["claim_verification_policy"]
        )
        user_document["output_requirements"] = {
            "max_total_claims": output_policy.max_total_claims,
            "max_critical_claims": verification_policy.max_critical_claims_per_hypothesis,
            "selection_rule": (
                "Select the most decisive causal links for verification, including novel "
                "bridges and falsifying predictions. Omit redundant restatements and "
                "less central premises; do not combine distinct causal claims merely "
                "to fit the limit. Count claims and critical labels before returning JSON. "
                "Keep each field concise."
            ),
        }
    if manifest.id == "claim_decomposition" and (
        inputs.get("claim_output_protocol") in {
            "deepseek-claim-source-units-v2",
            "deepseek-claim-source-units-v3",
            CLAIM_NORMALIZED_VERSION,
            CLAIM_PROVIDER_JSON_VERSION,
        }
        or inputs.get("claim_decomposition_contract_version") == CLAIM_PROVENANCE_V2
    ):
        user_document["source_units"] = [
            u.model_dump(mode="json") for u in (
                source_units_v2_for_content(inputs)
                if inputs.get("claim_decomposition_contract_version") == CLAIM_PROVENANCE_V2
                else source_units_for_content(inputs)
            )
        ]
        user_document["output_requirements"]["selection_rule"] = (
            "Select claims within the frozen limits. Use only the supplied source_unit_ids. "
            "semantic_relation is descriptive metadata and does not change provenance validity; "
            "do not return source_span."
            if inputs.get("claim_decomposition_contract_version") == CLAIM_PROVENANCE_V2
            else
            "Select at most the frozen total/critical limits. Cite only supplied "
            "source_unit_ids; do not author source_span. Direct/paraphrase uses one unit, "
            "synthesized_from uses at least two. model_quote is diagnostic only."
            if inputs.get("claim_output_protocol")
            not in {CLAIM_NORMALIZED_VERSION, CLAIM_PROVIDER_JSON_VERSION}
            else "Return only included claims in a variable-length claims array. Each included "
            "claim carries critical/supporting importance and supplied source_unit_ids; do "
            "not fill unused slots or invent source spans. Local validation enforces limits."
        )
    if manifest.output_schema == "ClaimDecompositionResultV3":
        user_document["source_units"] = [
            unit.model_dump(mode="json") for unit in source_units_v2_for_content(inputs)
        ]
        request_source = user_document.setdefault("output_requirements", {})
        request_source["lineage_mapping"] = (
            "Each claim references one supplied lineage_target_id or is explicitly "
            "marked as an unplanned new claim. SourceUnit IDs are provenance only."
        )
    request: dict[str, Any] = {
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
    ranking_contract = inputs.get("ranking_output_contract")
    if ranking_contract is not None:
        if manifest.id != "ranking":
            raise ValueError("strict Ranking output contract used by a different skill")
        ranking_spec = ranking_output_spec(inputs)
        if ranking_spec is None:
            raise ValueError("strict Ranking output contract is missing its specification")
        if ranking_contract.get("version") == JSON_RANKING_VERSION:
            request["provider_output_schema"] = ranking_spec["parameters"]
        else:
            request["output_contract"] = ranking_spec
    if (inputs.get("claim_output_protocol") is not None
            or inputs.get("claim_decomposition_contract_version") == CLAIM_PROVENANCE_V2):
        if manifest.id not in {"claim_decomposition", "claim_search_plan"}:
            raise ValueError("strict claim output protocol used by a different skill")
        claim_spec = claim_output_spec(manifest.id, inputs)
        if inputs.get("claim_output_protocol") == CLAIM_PROVIDER_JSON_VERSION or (
            inputs.get("claim_decomposition_contract_version") == CLAIM_PROVENANCE_V2
        ):
            request["provider_output_schema"] = claim_spec["parameters"]
        else:
            request["output_contract"] = claim_spec
    if inputs.get("claim_verification_output_protocol") is not None:
        if manifest.id != "claim_verification":
            raise ValueError("claim verification output protocol used by another skill")
        result_spec = claim_verification_output_spec(inputs)
        request["provider_output_schema"] = result_spec["parameters"]
    if manifest.output_schema == "ClaimDecompositionResultV3":
        request["provider_output_schema"] = (
            ClaimDecompositionProviderOutputV3.model_json_schema()
        )
    if manifest.output_schema == "PopulationEvolutionResultV2":
        request["provider_output_schema"] = output_schema.model_json_schema()
    if binding is not None:
        provider_schema = output_schema.model_json_schema()
        for name in ("binding", "schema_version", "research_plan_version"):
            provider_schema["properties"].pop(name, None)
        provider_schema["required"] = [name for name in provider_schema.get("required", [])
                                      if name not in {"binding", "schema_version", "research_plan_version"}]
        request["provider_output_schema"] = provider_schema
        if "evolution_output_contract" in inputs:
            contract = inputs["evolution_output_contract"]  # validated with the frozen task binding above
            operator = inputs["model_input"]["operator"]
            count = 1 if operator == "mutation" else 2
            provider_schema["properties"]["operator"] = {"type": "string", "const": operator}
            provider_schema["properties"]["parent_contributions"].update(
                minItems=count, maxItems=count, description=contract["instruction"])
            # Keep the historical system-skill identity; the versioned user
            # addendum is frozen in task inputs and the complete request/wire.
            visible = json.loads(request["user_prompt"])
            visible["input"].pop("evolution_output_contract", None)
            visible.setdefault("output_requirements", {})["evolution_per_parent"] = {
                **contract, "operator": operator, "expected_count": count,
                "frozen_scientific_parent_ids": list(binding.scientific_parent_ids)}
            request["user_prompt"] = json.dumps(visible, ensure_ascii=False, sort_keys=True,
                                                 separators=(",", ":"))
            request["provider_output_contract"] = contract
        if "effective_execution" in inputs:
            request["effective_execution"] = inputs["effective_execution"]
            if inputs["effective_execution"]["version"] == "generation-performance-v1":
                from co_scientist.domain.generation_integration import performance_schema

                if binding.skill_version != "0.4.0" or manifest.output_schema != "GroundedGenerationResultV1":
                    raise ValueError("performance skill requires exact Generation contract")
                request["provider_output_schema"] = performance_schema()
                # The exact scientific input remains task/source-bound locally.
                # Local execution identities are not model-authored authority.
                request["user_prompt"] = json.dumps(inputs["model_input"], ensure_ascii=False,
                                                     sort_keys=True, separators=(",", ":"))
        elif manifest.output_schema == "GroundedGenerationResultV1":
            request["baseline_generation_parameters"] = {
                "version": "baseline-generation-params-v1", "temperature": 1.6,
                "provider": binding.provider, "model": binding.model,
                "api": binding.api, "thinking_mode": binding.thinking_mode,
                "capability_id": binding.capability_id,
                "input_hash": binding.input_hash,
                "generation_input_hash": binding.generation_input_hash,
                "input_token_ceiling": 16384, "input_byte_ceiling": 65536,
                "token_estimator": "utf8-bytes-upper-bound-v1",
            }
    return request


def _requested_skill_version(inputs: Mapping[str, Any], skill_id: str) -> str | None:
    if (skill_id == "claim_decomposition"
        and inputs.get("claim_decomposition_contract_version") == CLAIM_PROVENANCE_V2) or (
        inputs.get("claim_verification_output_protocol") == CLAIM_VERIFICATION_V2
    ):
        return "0.2.0"
    return None


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
        prerequisite = context.output_schema_id in RESULT_MODELS
        if prerequisite and "ideation_task_binding" not in inputs:
            raise ValueError("B2-A contracts-only: production execution disabled")
        if prerequisite:
            from co_scientist.domain.ideation_core_boundary import batch2_execution_enabled

            if not batch2_execution_enabled(self.runner.uow.run_manifest(context.run_id)):
                raise ValueError("B2-A contracts-only: production execution disabled")
            binding = validate_prerequisite_inputs(inputs)
        else:
            binding = None
        if "ideation_task_binding" in inputs and not prerequisite:
            raise ValueError("prerequisite binding cannot execute a historical contract")
        manifest = load_skill(skill_directory, skill_version=context.skill_version,
                              phase=binding.phase if binding else None)
        resolve_core_skill_contract(
            skill_id=context.skill_id,
            skill_version=context.skill_version,
            output_schema_id=context.output_schema_id,
            phase=binding.phase if binding else None,
        )
        if context.skill_id != manifest.id:
            raise ValueError("execution context skill does not match manifest")
        if context.skill_version != manifest.version:
            raise ValueError("execution context skill version does not match manifest")
        if context.output_schema_id != manifest.output_schema:
            raise ValueError("execution context output schema does not match manifest")
        output_schema = resolve_output_schema(manifest.output_schema, context.output_schema_version)
        system_prompt = (skill_directory / manifest.prompt_path).read_text(encoding="utf-8")
        bound_prompt_hash = prompt_hash(system_prompt)
        if context.prompt_hash not in {None, bound_prompt_hash}:
            raise ValueError("execution context prompt hash does not match skill prompt")
        context = context.model_copy(update={"prompt_hash": bound_prompt_hash})
        request = build_skill_request(
            skill_directory=skill_directory,
            inputs=inputs,
            model=context.model_or_tool,
            skill_version=context.skill_version,
        )
        # Do not alter historical replay/fake request fingerprints. Live provider
        # adapters opt into the provider-result channel; replay consumes the exact
        # recorded request identity and validates the same raw artifact locally.
        if "effective_execution" in request:
            result_schema = request.get("provider_output_schema", request["json_schema"])
            request["provider_output_schema"] = result_schema
            request["provider_result"] = provider_result_request(
                "openai" if request["effective_execution"]["version"] == "generation-performance-v1"
                else "deepseek", result_schema, schema_name=request["schema_name"])
        elif request.get("output_contract") is None and context.provider in {
            "openai",
            "deepseek",
            "qwen",
            "gemini",
            "claude",
        }:
            result_schema = request.get("provider_output_schema", request["json_schema"])
            request["provider_output_schema"] = result_schema
            request["provider_result"] = provider_result_request(
                context.provider, result_schema, schema_name=request["schema_name"]
            )

        def validate_payload(raw: bytes) -> Mapping[str, Any]:
            validation_body = raw
            decoded: Mapping[str, Any]
            strict_output = inputs.get("ranking_output_contract") is not None
            strict_claim_output = (
                inputs.get("claim_output_protocol") is not None
                or inputs.get("claim_decomposition_contract_version") == CLAIM_PROVENANCE_V2
            )
            strict_claim_verification = inputs.get("claim_verification_output_protocol") is not None
            provider_native_ranking = (
                strict_output
                and inputs["ranking_output_contract"].get("version") == JSON_RANKING_VERSION
            )
            provider_native_claim = (
                inputs.get("claim_output_protocol") == CLAIM_PROVIDER_JSON_VERSION
                or inputs.get("claim_decomposition_contract_version") == CLAIM_PROVENANCE_V2
            )
            provider_native_claim_verification = (
                inputs.get("claim_verification_output_protocol") == CLAIM_VERIFICATION_V2
            )
            lineage_claim_v3 = (
                manifest.output_schema == "ClaimDecompositionResultV3"
                and inputs.get("claim_decomposition_contract_version")
                == "claim-provenance-lineage-v3"
            )
            if strict_output and context.provider != "deepseek" and not provider_native_ranking:
                raise ValueError("strict Ranking requires the DeepSeek provider")
            if lineage_claim_v3:
                normalized = normalize_provider_output(
                    raw, provider=context.provider, operation=manifest.id,
                )
                decoded = DomainValidator(
                    lambda result: normalize_claim_output_v3(result, manifest.id, inputs)
                ).validate(normalized)
            elif strict_output:
                if provider_native_ranking:
                    normalized = normalize_provider_output(
                        raw, provider=context.provider, operation=manifest.id
                    )
                    decoded = DomainValidator(
                        lambda result: decode_provider_ranking(result, inputs)
                    ).validate(normalized)
                else:
                    decoded = decode_strict_ranking(raw, inputs)
            elif strict_claim_output or strict_claim_verification:
                if (
                    context.provider != "deepseek"
                    and not provider_native_claim
                    and not provider_native_claim_verification
                ):
                    raise ValueError("strict claim output requires a compatible provider")
                if (
                    provider_native_claim
                    or provider_native_claim_verification
                    or inputs.get("claim_output_protocol") == CLAIM_NORMALIZED_VERSION
                ):
                    contract = (
                        claim_output_spec(manifest.id, inputs)
                        if strict_claim_output
                        else claim_verification_output_spec(inputs)
                    )
                    normalized = normalize_provider_output(
                        raw,
                        provider=context.provider,
                        operation=manifest.id,
                        result_tool_name=(
                            None
                            if provider_native_claim or provider_native_claim_verification
                            else contract["tool_name"]
                        ),
                    )
                    decoded = DomainValidator(
                        lambda result: (
                            normalize_claim_output_v2(result, manifest.id, inputs)
                            if inputs.get("claim_decomposition_contract_version") == CLAIM_PROVENANCE_V2
                            else normalize_claim_verification_output_v2(result, inputs)
                            if provider_native_claim_verification
                            else normalize_claim_result(result, manifest.id, inputs)
                        )
                    ).validate(normalized)
                else:
                    decoded = decode_claim_output(raw, manifest.id, inputs)
            elif "effective_execution" in request:
                from co_scientist.adapters.llm.multi_provider import output_text

                # Explicit new native-json API, not shape-inferred fake/legacy fallback.
                if request["effective_execution"]["version"] == "generation-performance-v1":
                    from co_scientist.adapters.llm.performance_responses import response_text

                    validation_body = response_text(dict(_decode_payload(raw))).encode("utf-8")
                else:
                    if (request["effective_execution"].get("single_root_mode") == "single-root-dev-live-v1"
                            or request["effective_execution"].get("live_execution_mode") in {"ideation-performance-dev-live-v1", "ideation-performance-dev-g3-v1"}):
                        single_envelope = dict(_decode_payload(raw))
                        choices = single_envelope.get("choices", [])
                        if len(choices) != 1 or choices[0].get("finish_reason") != "stop":
                            raise ValueError("single-root prerequisite response not complete")
                    validation_body = output_text("deepseek", dict(_decode_payload(raw))).encode("utf-8")
            elif context.provider == "openai":
                envelope = _decode_payload(raw)
                validation_body = _openai_output_text(envelope).encode("utf-8")
            elif context.provider in {"deepseek", "qwen", "gemini", "claude"}:
                from co_scientist.adapters.llm.multi_provider import output_text

                validation_body = output_text(context.provider, dict(_decode_payload(raw))).encode(
                    "utf-8"
                )
            if (not lineage_claim_v3 and not strict_output and not strict_claim_output
                    and not strict_claim_verification):
                decoded = _decode_payload(validation_body)
            if prerequisite:
                assert binding is not None
                forbidden = {"binding", "schema_version", "research_plan_version"}.intersection(decoded)
                if forbidden:
                    raise DomainValidationError("provider authored local prerequisite authority: "
                                                + ",".join(sorted(forbidden)))
                decoded = {**decoded, "binding": binding.model_dump(mode="json"),
                           "schema_version": context.output_schema_version,
                           "research_plan_version": context.research_plan_version}
            try:
                validated = output_schema.model_validate(decoded)
            except ValidationError as error:
                raise DomainValidationError(str(error)) from error
            if getattr(validated, "research_plan_version", None) != context.research_plan_version:
                raise ValueError("payload research plan version does not match execution context")
            try:
                validate_result_task_binding(
                    task_inputs=inputs,
                    task_research_plan_version=context.research_plan_version,
                    provider_id=context.provider,
                    result=cast(
                        CoreScientificResultV1 | ClaimDecompositionResultV2 | ClaimVerificationResultV2,
                        validated,
                    ),
                )
            except ValueError as error:
                raise ScientificValidationFailure(str(error)) from error
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


class RootPubMedProvider:
    """Compose existing PubMed operations into an auditable bounded root return.

    Only received/parse failures become scoped omissions. Unknown delivery,
    budget and endpoint errors propagate and never become empty retrieval.
    """

    def __init__(self, search: ExternalProvider, summary: ExternalProvider) -> None:
        self.search, self.summary = search, summary

    async def invoke(self, request: dict[str, Any]):
        from datetime import UTC, datetime

        import httpx

        from co_scientist.adapters.literature.pubmed import LiteratureAccessIssue
        from co_scientist.ports.external_provider import RawExternalResponse
        from co_scientist.runtime.bounded_transport import SlotRetrievalHTTPError

        queries = request["queries"]
        if (not isinstance(queries, list) or not 1 <= len(queries) <= 3
                or len({" ".join(q.split()) for q in queries}) != len(queries)
                or request.get("limit") != 20 or request.get("max_selected_sources") != 30
                or request.get("timeout_seconds") != 30):
            raise ValueError("invalid frozen root retrieval request")
        sections: list[dict[str, Any]] = []
        selected: list[str] = []
        for query in queries:
            section: dict[str, Any] = {"query": query, "search_raw": None, "fetch_raw": None,
                                       "returned_pmids": [], "selected_pmids": [], "failure": None}
            try:
                raw = await self.search.invoke({"query": query, "limit": 20, "timeout_seconds": 30})
                try:
                    section["search_raw"] = raw.body.decode("utf-8")
                    ids = _decode_payload(raw.body)["esearchresult"]["idlist"]
                    if (not isinstance(ids, list) or len(ids) > 20
                            or any(not isinstance(p, str) or not p.isdigit() for p in ids)):
                        raise ValueError("invalid bounded PMID result")
                except (ValueError, KeyError, UnicodeError):
                    section["failure"] = "RETRIEVAL_PARSE_FAILED"
                    sections.append(section)
                    continue
                section["returned_pmids"] = ids
                for pmid in ids:
                    if pmid not in selected and len(selected) < 30:
                        selected.append(pmid)
                        section["selected_pmids"].append(pmid)
                if section["selected_pmids"]:
                    fetched = await self.summary.invoke({"query": query,
                        "pmids": section["selected_pmids"], "content_mode": "abstracts", "timeout_seconds": 30})
                    try:
                        section["fetch_raw"] = fetched.body.decode("utf-8")
                    except UnicodeError:
                        section["failure"] = "RETRIEVAL_PARSE_FAILED"
            except SlotRetrievalHTTPError as error:
                section["failure"] = f"HTTP_RESPONSE_{error.status}"
            except httpx.HTTPStatusError as error:
                section["failure"] = f"HTTP_RESPONSE_{error.response.status_code}"
            except LiteratureAccessIssue as error:
                section["failure"] = f"HTTP_RESPONSE_{error.status_code}"
            sections.append(section)
        body = json.dumps({"version": "bounded-root-pubmed-v2", "sections": sections,
            "completed_at": datetime.now(UTC).isoformat()}, ensure_ascii=False,
            sort_keys=True, separators=(",", ":")).encode()
        return RawExternalResponse(body=body, mime_type="application/json", usage={})


class RootRetrievalExecutor:
    """Derive completed facts only after the aggregate domain raw is durable."""

    def __init__(self, runner: ExternalCallRunner, provider: ExternalProvider) -> None:
        self.runner, self.provider = runner, provider

    async def execute(self, *, call_id: str, inputs: dict[str, Any], context: AgentExecutionContext,
        reservation_id: str, fence: TaskLeaseFence, write_guard=None) -> AgentResult:
        from co_scientist.domain.ideation_prerequisites import (
            GroundingOutcomeV1,
            RetrievalRequestBindingV2,
            RootRetrievalResultV2,
            SourceRecordV1,
            canonical_request_key,
            source_set_hash,
            text_hash,
        )
        from co_scientist.domain.research_protocol import protocol_hash

        b = validate_prerequisite_inputs(inputs)
        if not isinstance(b, RetrievalRequestBindingV2):
            raise TypeError("root retrieval requires explicit V2 request binding")
        request = dict(inputs["model_input"])

        def validate(raw: bytes) -> Mapping[str, Any]:
            returned: list[str] = []
            sources: list[SourceRecordV1] = []
            omissions: list[str] = []
            aggregate = _decode_payload(raw)
            if aggregate.get("version") != "bounded-root-pubmed-v2":
                raise ValueError("wrong root retrieval raw version")
            sections = aggregate["sections"]
            if [s["query"] for s in sections] != request["queries"]:
                raise ValueError("root retrieval request identity mismatch")
            manifest = self.runner.artifacts.discover_raw(call_id)
            if manifest is None:
                raise ValueError("root retrieval domain raw not persisted")
            ref = manifest.artifact_ref
            completed = 0
            for section in sections:
                returned.extend("pubmed:" + p for p in section["returned_pmids"])
                if section["failure"]:
                    omissions.append(section["failure"])
                else:
                    completed += 1
                if section["fetch_raw"] is None:
                    continue
                try:
                    documents = parse_pubmed_abstracts(section["fetch_raw"].encode(),
                        query=section["query"], raw_artifact_ref=ref.path)
                    visible = {d.canonical_id.removeprefix("PMID:"): d for d in documents}
                    if set(visible) - set(section["selected_pmids"]):
                        raise ValueError("fetch supplied unrequested PMID")
                    for pmid in section["selected_pmids"]:
                        if pmid not in visible:
                            omissions.append(f"missing source pubmed:{pmid}")
                            continue
                        d = visible[pmid]
                        text = d.abstract or d.title
                        sources.append(SourceRecordV1(source_id=d.source_id,
                            snapshot_id=protocol_hash({"source": d.source_id, "text": text}),
                            title=d.title, exact_text=text, content_hash=text_hash(text),
                            raw_artifact_id=ref.path, raw_hash=ref.sha256,
                            content_level="ABSTRACT" if d.abstract else "METADATA_ONLY"))
                except (ValueError, KeyError, UnicodeError):
                    omissions.append("SOURCE_PARSE_FAILED")
            state = ("PARTIAL" if omissions and sources else "GROUNDING_UNAVAILABLE" if omissions
                     else "SUCCESS_NONEMPTY" if sources else "SEARCHED_EMPTY" if not returned
                     else "GROUNDING_UNAVAILABLE")
            if returned and not sources and not omissions:
                omissions.append("NO_USABLE_SOURCE")
            outcome = GroundingOutcomeV1.model_validate({"state": state,
                "prescribed_queries": len(sections), "completed_queries": completed,
                "total_returned": len(returned), "usable_source_ids": tuple(s.source_id for s in sources),
                "omissions": tuple(omissions)})
            data = {"schema_version": 2, "research_plan_version": b.directive_version,
                "binding": b.model_dump(mode="json"), "origin": "RETRIEVER_RESPONSE",
                "request_key": protocol_hash([canonical_request_key(query=q, content_mode="abstracts")
                                                for q in request["queries"]]),
                "external_call_id": call_id, "raw_artifact_id": ref.path, "raw_hash": ref.sha256,
                "completed_at": aggregate["completed_at"], "returned_source_ids": returned,
                "sources": [s.model_dump(mode="json") for s in sources],
                "source_set_hash": source_set_hash(sources), "outcome": outcome.model_dump(mode="json")}
            data["completed_result_id"] = protocol_hash({k: v for k, v in data.items() if k != "binding"})
            result = RootRetrievalResultV2.model_validate(data)
            validate_result_task_binding(task_inputs=inputs, task_research_plan_version=b.directive_version,
                                        provider_id=b.provider, result=result)
            return result.model_dump(mode="json")

        return await self.runner.execute(call_id=call_id, request=request, provider=self.provider,
            validator=validate, context=context, reservation_id=reservation_id, fence=fence,
            write_guard=write_guard)


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
        if inputs.get("timeout_seconds") is not None:
            timeout = inputs["timeout_seconds"]
            if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= 120:
                raise ValueError("literature timeout must be a frozen 1-120 second integer")
            request["timeout_seconds"] = timeout
        if operation == "search":
            request["limit"] = int(inputs.get("limit", 10))
            if inputs.get("sort") is not None:
                request["sort"] = inputs["sort"]
        else:
            pmids = inputs.get("pmids")
            if not isinstance(pmids, list) or not pmids:
                raise ValueError("literature summary task requires PMIDs")
            request["pmids"] = [str(pmid) for pmid in pmids]
            if inputs.get("content_mode") == "abstracts":
                if context.model_or_tool != "efetch":
                    raise ValueError("abstract retrieval requires efetch task identity")
                request["content_mode"] = "abstracts"

        def validate_payload(raw: bytes) -> Mapping[str, Any]:
            if operation == "search":
                document = _decode_payload(raw)
                result = document.get("esearchresult")
                if not isinstance(result, Mapping):
                    raise ValueError("PubMed search response is malformed")
                pmids = result.get("idlist")
                if not isinstance(pmids, list) or any(
                    not isinstance(pmid, str) or not pmid for pmid in pmids
                ):
                    raise ValueError("PubMed search response is malformed")
                overview = {"operation": "search", "query": query, "pmids": pmids}
                feedback = "PubMed search raw response persisted before PMID parsing."
            else:
                parser = (
                    parse_pubmed_abstracts
                    if request.get("content_mode") == "abstracts"
                    else parse_pubmed_records
                )
                documents = parser(
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
                feedback = "PubMed source raw response persisted before source parsing."
            payload = {
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
            validated = MetaReviewResultV1.model_validate(payload)
            validate_result_task_binding(
                task_inputs=inputs,
                task_research_plan_version=context.research_plan_version,
                provider_id=context.provider,
                result=validated,
                literature_operation=operation,
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
