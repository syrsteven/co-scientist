"""Opt-in fixed-slot DeepSeek output transports for the DEV pilot.

These codecs bind transport shape, not scientific truth. They run only after the
vendor envelope has been durably persisted; canonical validators still decide
whether a scientific result may be applied.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

from co_scientist.adapters.llm.output_errors import (
    DomainValidationError,
    ScientificValidationFailure,
)
from co_scientist.agents.payloads import (
    ClaimDecompositionProviderOutputV2,
    ClaimDecompositionProviderOutputV3,
    ClaimVerificationProviderOutputV2,
)
from co_scientist.domain.claim_lineage import FrozenLineagePlanV2
from co_scientist.domain.claim_verification import (
    ClaimDecompositionOutputPolicy,
    ClaimVerificationPolicy,
)
from co_scientist.domain.source_units import (
    resolve_source_units_v2,
    source_units_for_content,
    source_units_v2_for_content,
)

URL = "https://api.deepseek.com/beta/chat/completions"
CLAIM_VERSION = "deepseek-claim-slots-v1"
CLAIM_SOURCE_VERSION = "deepseek-claim-source-units-v2"
CLAIM_MULTI_VERSION = "deepseek-claim-source-units-v3"
CLAIM_NORMALIZED_VERSION = "deepseek-claim-source-units-v4"
CLAIM_PROVIDER_JSON_VERSION = "claim-source-units-provider-json-v5"
CLAIM_PROVENANCE_V2 = "claim-provenance-v2"
CLAIM_VERIFICATION_V2 = "claim-verification-result-v2"
BASELINE_VERSION = "deepseek-candidate-slots-v1"
BASELINE_NORMALIZED_VERSION = "deepseek-candidate-array-v2"
BASELINE_PROVIDER_JSON_VERSION = "candidate-array-provider-json-v3"
INTENTS = ("support", "refute", "prior_work", "competing_mechanism")


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _text() -> dict[str, Any]:
    return {"type": "string", "pattern": r"\S"}


def _tool(name: str, parameters: dict[str, Any], instructions: str) -> dict[str, Any]:
    return {
        "version": CLAIM_VERSION if name.startswith("submit_claim") else BASELINE_VERSION,
        "endpoint": URL,
        "tool_name": name,
        "tool_choice": "auto",
        "parameters": parameters,
        "instructions": instructions,
    }


def baseline_output_spec(operation: str, count: int) -> dict[str, Any]:
    """Named candidate slots avoid unsupported DeepSeek array length constraints."""
    if operation not in {"generate", "revise"} or type(count) is not int or not 1 <= count <= 20:
        raise ValueError("unsupported fixed-slot baseline operation or count")
    candidate = _object(
        {
            "candidate_id": _text(),
            "title": _text(),
            "mechanism": _text(),
            "evidence_summary": _text(),
            "falsifier": _text(),
            "discriminating_experiment": _text(),
            "prior_art_status": {
                "type": "string",
                "enum": [
                    "direct_prior_art_found",
                    "partial_prior_art_found",
                    "components_known_bridge_not_found",
                    "no_related_work_retrieved_under_scope",
                    "indeterminate",
                ],
            },
        }
    )
    return _tool(
        "submit_benchmark_candidates_v1",
        _object({f"candidate_{i}": candidate for i in range(1, count + 1)}),
        f"Call this output function exactly once. Fill all {count} distinct candidate "
        "slots with substantive hypotheses; do not omit, merge or pad slots. "
        "The local codec maps slots to the canonical candidates array. "
        "Only function arguments are scientific output; never invent observed results.",
    )


def normalized_baseline_output_spec(
    operation: str, *, provider_native: bool = False
) -> dict[str, Any]:
    """Variable provider array; final candidate cardinality is checked locally."""
    if operation not in {"generate", "revise"}:
        raise ValueError("unsupported normalized baseline operation")
    candidate = _object(
        {
            "candidate_id": _text(),
            "title": _text(),
            "mechanism": _text(),
            "evidence_summary": _text(),
            "falsifier": _text(),
            "discriminating_experiment": _text(),
            "prior_art_status": {
                "type": "string",
                "enum": [
                    "direct_prior_art_found",
                    "partial_prior_art_found",
                    "components_known_bridge_not_found",
                    "no_related_work_retrieved_under_scope",
                    "indeterminate",
                ],
            },
        }
    )
    spec = _tool(
        "submit_benchmark_candidates_v3" if provider_native else "submit_benchmark_candidates_v2",
        _object(
            {
                "candidates": {"type": "array", "items": candidate},
            }
        ),
        "Call this tool once when possible. Return a JSON candidates array of the hypotheses "
        "you generated. Do not pad or truncate the array; the local benchmark enforces K. "
        "Do not invent observed results.",
    )
    if provider_native:
        spec.update(
            version=BASELINE_PROVIDER_JSON_VERSION,
            instructions="Return a JSON object containing a variable-length candidates "
            "array. Do not pad or truncate; the local validator enforces K. Do not "
            "invent observed results.",
        )
    return spec


def _normalized_claim_spec(skill_id: str, inputs: Mapping[str, Any]) -> dict[str, Any]:
    if skill_id == "claim_decomposition":
        fields = {
            "importance": {"type": "string", "enum": ["critical", "supporting"]},
            "claim_id": _text(),
            "text": _text(),
            "claim_type": {
                "type": "string",
                "enum": [
                    "established_premise",
                    "bridging_inference",
                    "novel_causal_claim",
                    "prediction",
                    "competing_explanation",
                ],
            },
            "subject": _text(),
            "relation": _text(),
            "object": _text(),
            "source_unit_ids": {"type": "array", "items": _text()},
            "source_relation": {
                "type": "string",
                "enum": ["direct", "paraphrase", "synthesized_from"],
            },
            "model_quote": {"type": "string"},
        }
        spec = _tool(
            "submit_claim_decomposition_v2",
            _object(
                {
                    "claims": {"type": "array", "items": _object(fields)},
                }
            ),
            "Return only included scientific claims in a claims array. Do not create placeholder "
            "entries for unused capacity. Each claim must have importance critical or supporting. "
            "Use only supplied source_unit_ids; direct/paraphrase uses one unit, synthesized_from "
            "uses at least two. Never author source_span. Local validation enforces the frozen "
            "maximum of eight total and three critical claims.",
        )
    elif skill_id == "claim_search_plan":
        inputs_claims = inputs.get("critical_claims")
        if not isinstance(inputs_claims, list) or not inputs_claims:
            raise ValueError("search plans require critical claims")
        query = _object(
            {
                "intent": {"type": "string", "enum": list(INTENTS)},
                "query": _text(),
                "rationale": _text(),
            }
        )
        plan = _object(
            {
                "claim_id": _text(),
                "claim_content_hash": _text(),
                "queries": {"type": "array", "items": query},
            }
        )
        spec = _tool(
            "submit_claim_search_plan_v1",
            _object(
                {
                    "plans": {"type": "array", "items": plan},
                }
            ),
            "Return one plan per supplied critical claim. Each plan must bind to its claim_id "
            "and content hash and contain exactly one query for support, refute, prior_work, and "
            "competing_mechanism. Do not copy the generation query for non-support intents.",
        )
    else:
        raise ValueError("normalized output supports claim decomposition and search planning")
    spec["version"] = inputs.get("claim_output_protocol", CLAIM_NORMALIZED_VERSION)
    return spec


def claim_output_spec(skill_id: str, inputs: Mapping[str, Any]) -> dict[str, Any]:
    protocol = inputs.get("claim_decomposition_contract_version") or inputs.get(
        "claim_output_protocol"
    )
    if protocol == CLAIM_PROVENANCE_V2:
        if skill_id != "claim_decomposition":
            raise ValueError("claim provenance v2 applies only to decomposition")
        _require_v2_task_binding(inputs)
        return {
            "version": CLAIM_PROVENANCE_V2,
            "schema_name": "ClaimDecompositionProviderOutputV2",
            "parameters": ClaimDecompositionProviderOutputV2.model_json_schema(),
            "instructions": (
                "Return included scientific claims in a claims array. Each claim cites only "
                "the supplied source_unit_ids. semantic_relation (direct, paraphrase, or "
                "synthesized) is descriptive metadata: source-unit count does not determine it. "
                "Do not return source spans or invent source-unit IDs; diagnostic_quote is not "
                "provenance. The local contract enforces claim and provenance limits."
            ),
        }
    if protocol not in {
        CLAIM_VERSION,
        CLAIM_SOURCE_VERSION,
        CLAIM_MULTI_VERSION,
        CLAIM_NORMALIZED_VERSION,
        CLAIM_PROVIDER_JSON_VERSION,
    }:
        raise ValueError("missing frozen claim output protocol")
    hypothesis_id = inputs.get("hypothesis_id")
    content_hash = inputs.get("content_hash")
    version = inputs.get("research_plan_version")
    if (
        not isinstance(hypothesis_id, str)
        or not hypothesis_id
        or not isinstance(content_hash, str)
        or not content_hash.startswith("sha256:")
        or type(version) is not int
        or version < 1
    ):
        raise ValueError("claim output requires frozen hypothesis and plan binding")
    if protocol in {CLAIM_NORMALIZED_VERSION, CLAIM_PROVIDER_JSON_VERSION}:
        return _normalized_claim_spec(skill_id, inputs)
    if skill_id == "claim_decomposition":
        source_units = (
            source_units_for_content(inputs)
            if protocol in {CLAIM_SOURCE_VERSION, CLAIM_MULTI_VERSION}
            else ()
        )
        policy = ClaimDecompositionOutputPolicy.model_validate(
            inputs.get("claim_decomposition_output")
        )
        verification = ClaimVerificationPolicy.model_validate(
            inputs.get("claim_verification_policy")
        )
        critical_max = verification.max_critical_claims_per_hypothesis
        if critical_max > policy.max_total_claims:
            raise ValueError("invalid frozen critical claim limit")
        fields = {
            "include": {"type": "boolean"},
            "claim_id": _text(),
            "text": _text(),
            "claim_type": {
                "type": "string",
                "enum": [
                    "established_premise",
                    "bridging_inference",
                    "novel_causal_claim",
                    "prediction",
                    "competing_explanation",
                ],
            },
            "subject": _text(),
            "relation": _text(),
            "object": _text(),
            **(
                {
                    "source_unit_ids": {"type": "array", "items": _text()},
                    "source_relation": {
                        "type": "string",
                        "enum": ["direct", "paraphrase", "synthesized_from"],
                    },
                    "model_quote": {"type": "string"},
                }
                if source_units
                else {"source_span": _text()}
            ),
        }
        claim = _object(fields)
        properties = {f"critical_{i}": claim for i in range(1, critical_max + 1)}
        properties.update(
            {f"supporting_{i}": claim for i in range(1, policy.max_total_claims - critical_max + 1)}
        )
        spec = _tool(
            "submit_claim_decomposition_v2" if source_units else "submit_claim_decomposition_v1",
            _object(properties),
            "Call this output function exactly once. Select the decisive causal "
            "links, with at least one included critical slot. Set include=false "
            "for unused slots and fill their other required fields with "
            "'not_applicable'. Do not relabel a critical causal link as supporting "
            "to fit the bound; if the mechanism needs more critical links, the "
            "scientific task cannot be valid under this frozen policy. "
            + (
                "For each included claim, cite exact source_unit_ids from the supplied "
                "SourceUnits. Use one unit for direct/paraphrase and at least two for "
                "synthesized_from. model_quote is diagnostic only. "
                if source_units
                else "Copy each included source_span verbatim from the hypothesis. "
            )
            + "The local codec binds claim IDs; only function "
            "arguments are scientific output.",
        )
        if source_units:
            spec["version"] = protocol
    elif skill_id == "claim_search_plan":
        claims = inputs.get("critical_claims")
        search_policy = ClaimVerificationPolicy.model_validate(
            inputs.get("claim_verification_policy")
        )
        if (
            not isinstance(claims, list)
            or not claims
            or search_policy.max_queries_per_claim < 4
            or len(claims) > search_policy.max_critical_claims_per_hypothesis
            or any(
                not isinstance(claim, Mapping)
                or claim.get("importance") != "critical"
                or claim.get("hypothesis_content_hash") != inputs["content_hash"]
                or not isinstance(claim.get("claim_id"), str)
                for claim in claims
            )
            or len({claim["claim_id"] for claim in claims}) != len(claims)
        ):
            raise ValueError("search slots require distinct frozen critical claims")
        query = _object({"query": _text(), "rationale": _text()})
        per_claim = _object({intent: query for intent in INTENTS})
        spec = _tool(
            "submit_claim_search_plan_v1",
            _object({f"claim_{index}": per_claim for index in range(1, len(claims) + 1)}),
            "Call this output function exactly once. Each numbered claim matches the "
            "corresponding critical claim in input order and contains exactly one query "
            "for support, refute, prior_work, and competing_mechanism. Do not copy the "
            "generation query for non-support intents.",
        )
        if protocol in {CLAIM_SOURCE_VERSION, CLAIM_MULTI_VERSION}:
            spec["version"] = protocol
    else:
        raise ValueError("strict claim slots are only for decomposition and search planning")
    return spec


def claim_verification_output_spec(inputs: Mapping[str, Any]) -> dict[str, Any]:
    if inputs.get("claim_verification_output_protocol") != CLAIM_VERIFICATION_V2:
        raise ValueError("missing frozen claim verification v2 protocol")
    _require_v2_task_binding(inputs)
    return {
        "version": CLAIM_VERIFICATION_V2,
        "schema_name": "ClaimVerificationProviderOutputV2",
        "parameters": ClaimVerificationProviderOutputV2.model_json_schema(),
        "instructions": (
            "Return EvidenceBinding proposals using only the supplied evidence_unit_ids. "
            "For each binding, separate relation_to_claim from prior_art_role. Do not return "
            "source spans as authority, derived evidence ID lists, or a PriorArtAssessment "
            "status. Local code resolves exact text and derives all evidence projections. "
            "Claim outcomes are proposals under the frozen policy; contract/binding failures "
            "are not scientific negatives."
        ),
    }


def _require_v2_task_binding(inputs: Mapping[str, Any]) -> None:
    if (
        not isinstance(inputs.get("hypothesis_id"), str)
        or not inputs.get("hypothesis_id")
        or not isinstance(inputs.get("content_hash"), str)
        or not inputs["content_hash"].startswith("sha256:")
        or type(inputs.get("research_plan_version")) is not int
        or inputs["research_plan_version"] < 1
    ):
        raise ValueError("v2 claim result requires frozen hypothesis and plan binding")


def normalize_claim_output_v2(
    normalized: Any, skill_id: str, inputs: Mapping[str, Any]
) -> dict[str, Any]:
    """Bind v2 provider claim proposals to local immutable SourceUnitV2 objects."""
    if skill_id != "claim_decomposition" or inputs.get(
        "claim_decomposition_contract_version"
    ) != CLAIM_PROVENANCE_V2:
        raise DomainValidationError("v2 claim provenance protocol/skill mismatch")
    _require_v2_task_binding(inputs)
    payload, _ = _normalized_payload(normalized)
    if not isinstance(payload, Mapping):
        raise DomainValidationError("claim provenance output must be an object")
    provider = ClaimDecompositionProviderOutputV2.model_validate(payload)
    source_units = source_units_v2_for_content(inputs)
    claims: list[dict[str, Any]] = []
    for item in provider.claims:
        units = resolve_source_units_v2(
            item.source_unit_ids,
            expected_hypothesis_id=str(inputs["hypothesis_id"]),
            expected_content_hash=str(inputs["content_hash"]),
            allowed_units=source_units,
        )
        claims.append({
            **item.model_dump(mode="json", exclude={"source_unit_refs"}),
            "source_unit_refs": [unit.model_dump(mode="json") for unit in units],
        })
    policy = ClaimDecompositionOutputPolicy.model_validate(
        inputs.get("claim_decomposition_output")
    )
    verification = ClaimVerificationPolicy.model_validate(inputs.get("claim_verification_policy"))
    if len(claims) > policy.max_total_claims:
        raise ScientificValidationFailure("claim count outside frozen total limit")
    if sum(claim["importance"] == "critical" for claim in claims) > (
        verification.max_critical_claims_per_hypothesis
    ):
        raise ScientificValidationFailure("critical claim count outside frozen limit")
    if not any(claim["importance"] == "critical" for claim in claims):
        raise ScientificValidationFailure("claim decomposition has no critical claim")
    if len({claim["claim_id"] for claim in claims}) != len(claims):
        raise ScientificValidationFailure("duplicate claim id")
    fingerprints = {
        json.dumps(
            {key: value for key, value in claim.items() if key not in {"claim_id", "diagnostic_quote"}},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ) for claim in claims
    }
    if len(fingerprints) != len(claims):
        raise ScientificValidationFailure("duplicate scientific claim content")
    return {
        "contract_version": CLAIM_PROVENANCE_V2,
        "schema_version": 2,
        "research_plan_version": inputs["research_plan_version"],
        "hypothesis_id": inputs["hypothesis_id"],
        "hypothesis_content_hash": inputs["content_hash"],
        "claims": claims,
    }


def normalize_claim_output_v3(
    normalized: Any, skill_id: str, inputs: Mapping[str, Any],
) -> dict[str, Any]:
    """Resolve provider-only V3 claims against the exact frozen child task context."""
    if (skill_id != "claim_decomposition" or inputs.get(
        "claim_decomposition_contract_version"
    ) != "claim-provenance-lineage-v3"):
        raise DomainValidationError("V3 claim provenance protocol/skill mismatch")
    _require_v2_task_binding(inputs)
    plan = FrozenLineagePlanV2.model_validate(inputs.get("frozen_lineage_plan"))
    if (plan.child_hypothesis_id != inputs["hypothesis_id"]
            or plan.child_hypothesis_content_hash != inputs["content_hash"]
            or inputs.get("lineage_targets") != [target.model_dump(mode="json")
                                                for target in plan.targets]
            or inputs.get("lineage_parent_scope") != [ref.model_dump(mode="json")
                                                     for ref in plan.lineage_parent_scope]
            or not isinstance(inputs.get("lineage_targets_frozen_event_id"), str)
            or not inputs["lineage_targets_frozen_event_id"]):
        raise DomainValidationError("V3 provider result differs from frozen lineage task")
    payload, _ = _normalized_payload(normalized)
    if not isinstance(payload, Mapping):
        raise DomainValidationError("V3 provider output must be an object")
    provider = ClaimDecompositionProviderOutputV3.model_validate(payload)
    allowed_targets = {target.lineage_target_id for target in plan.targets}
    source_units = source_units_v2_for_content(inputs)
    claims: list[dict[str, Any]] = []
    for item in provider.claims:
        if item.lineage_target_id is not None and item.lineage_target_id not in allowed_targets:
            raise DomainValidationError("unknown frozen lineage target in provider claim")
        units = resolve_source_units_v2(
            item.source_unit_ids,
            expected_hypothesis_id=str(inputs["hypothesis_id"]),
            expected_content_hash=str(inputs["content_hash"]),
            allowed_units=source_units,
        )
        claims.append({
            **item.model_dump(mode="json"),
            "source_unit_refs": [unit.model_dump(mode="json") for unit in units],
        })
    policy = ClaimDecompositionOutputPolicy.model_validate(
        inputs.get("claim_decomposition_output")
    )
    verification = ClaimVerificationPolicy.model_validate(
        inputs.get("claim_verification_policy")
    )
    if len(claims) > policy.max_total_claims:
        raise ScientificValidationFailure("claim count outside frozen total limit")
    if sum(claim["importance"] == "critical" for claim in claims) > (
        verification.max_critical_claims_per_hypothesis
    ):
        raise ScientificValidationFailure("critical claim count outside frozen limit")
    if not any(claim["importance"] == "critical" for claim in claims):
        raise ScientificValidationFailure("claim decomposition has no critical claim")
    if len({claim["claim_id"] for claim in claims}) != len(claims):
        raise ScientificValidationFailure("duplicate claim id")
    return {
        "contract_version": "claim-provenance-lineage-v3",
        "schema_version": 3,
        "research_plan_version": inputs["research_plan_version"],
        "hypothesis_id": inputs["hypothesis_id"],
        "hypothesis_content_hash": inputs["content_hash"],
        "claims": claims,
    }


def normalize_claim_verification_output_v2(
    normalized: Any, inputs: Mapping[str, Any]
) -> dict[str, Any]:
    """Bind provider evidence-unit proposals to the immutable task envelope."""
    if inputs.get("claim_verification_output_protocol") != CLAIM_VERIFICATION_V2:
        raise DomainValidationError("claim verification v2 protocol mismatch")
    _require_v2_task_binding(inputs)
    payload, _ = _normalized_payload(normalized)
    if not isinstance(payload, Mapping):
        raise DomainValidationError("claim verification output must be an object")
    provider = ClaimVerificationProviderOutputV2.model_validate(payload)
    critical_claims = inputs.get("critical_claims")
    if not isinstance(critical_claims, list) or not critical_claims:
        raise DomainValidationError("claim verification requires frozen critical claims")
    claims_by_id = {
        claim.get("claim_id"): claim for claim in critical_claims if isinstance(claim, Mapping)
    }
    if len(claims_by_id) != len(critical_claims) or None in claims_by_id:
        raise DomainValidationError("critical claim identities are invalid")
    for binding in provider.bindings:
        if binding.claim_id not in claims_by_id:
            raise ScientificValidationFailure("binding claim is outside frozen task inputs")
    assessment_ids = [assessment.claim_id for assessment in provider.claim_assessments]
    if len(assessment_ids) != len(set(assessment_ids)):
        raise ScientificValidationFailure("claim assessments must be unique")
    if set(assessment_ids) != set(claims_by_id):
        raise ScientificValidationFailure("claim assessments do not cover frozen critical claims")
    return {
        "contract_version": CLAIM_VERIFICATION_V2,
        "schema_version": 2,
        "research_plan_version": inputs["research_plan_version"],
        "hypothesis_id": inputs["hypothesis_id"],
        "hypothesis_content_hash": inputs["content_hash"],
        **provider.model_dump(mode="json"),
    }
def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("strict output contains duplicate JSON keys")
        value[key] = item
    return value


def _invalid_constant(value: str) -> None:
    raise ValueError(f"strict output contains invalid JSON constant: {value}")


def _arguments(raw: bytes, spec: Mapping[str, Any]) -> dict[str, Any]:
    envelope = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_invalid_constant)
    choices = envelope.get("choices") if isinstance(envelope, dict) else None
    if not isinstance(choices, list) or len(choices) != 1:
        raise ValueError("strict output requires exactly one response choice")
    choice = choices[0]
    if not isinstance(choice, dict) or choice.get("finish_reason") != "tool_calls":
        raise ValueError("strict output requires tool_calls finish; no text fallback")
    message = choice.get("message")
    if not isinstance(message, dict):
        raise TypeError("strict output requires a message object")
    content = message.get("content")
    # DeepSeek has emitted auxiliary content alongside an otherwise valid tool
    # call. Preserve it only in raw; never interpret it as a scientific result.
    if content is not None and (not isinstance(content, str) or len(content) > 8192):
        raise ValueError("strict output auxiliary text is invalid or oversized")
    calls = message.get("tool_calls")
    if not isinstance(calls, list) or len(calls) != 1:
        raise ValueError("strict output requires exactly one result tool")
    call = calls[0]
    function = (
        call.get("function") if isinstance(call, dict) and call.get("type") == "function" else None
    )
    if not isinstance(function, dict) or function.get("name") != spec["tool_name"]:
        raise ValueError("strict output result tool name mismatch")
    arguments = function.get("arguments")
    if not isinstance(arguments, str):
        raise TypeError("strict output tool arguments must be JSON text")
    value = json.loads(arguments, object_pairs_hook=_pairs, parse_constant=_invalid_constant)
    if not isinstance(value, dict) or set(value) != set(spec["parameters"]["properties"]):
        raise ValueError("strict output arguments have missing or extra fields")
    return value


def _canonical_payload_hash(value: dict[str, Any]) -> str:
    canonical = json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _subsumes(larger: Any, smaller: Any) -> bool:
    if isinstance(smaller, dict):
        return isinstance(larger, dict) and all(
            key in larger and _subsumes(larger[key], value) for key, value in smaller.items()
        )
    # Lists and scalars are atomic: extending source_unit_ids changes provenance.
    return type(larger) is type(smaller) and larger == smaller


def resolve_result_tool_calls(
    raw: bytes, spec: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve v3 calls only when a unique canonical payload subsumes every call."""
    if spec.get("version") != CLAIM_MULTI_VERSION:
        raise ValueError("multi-result-tool resolver requires the v3 contract")
    envelope = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_invalid_constant)
    choices = envelope.get("choices") if isinstance(envelope, dict) else None
    if not isinstance(choices, list) or len(choices) != 1:
        raise ValueError("strict output requires exactly one response choice")
    choice = choices[0]
    if not isinstance(choice, dict) or choice.get("finish_reason") != "tool_calls":
        raise ValueError("strict output requires tool_calls finish")
    message = choice.get("message")
    if not isinstance(message, dict):
        raise TypeError("strict output requires a message object")
    content = message.get("content")
    if content is not None and (not isinstance(content, str) or len(content) > 8192):
        raise ValueError("strict output auxiliary text is invalid or oversized")
    calls = message.get("tool_calls")
    if not isinstance(calls, list) or not 1 <= len(calls) <= 8:
        raise ValueError("ambiguous_multiple_result_tools")
    values: list[dict[str, Any]] = []
    repairs: list[dict[str, Any]] = []
    decoder = json.JSONDecoder(object_pairs_hook=_pairs, parse_constant=_invalid_constant)
    for index, call in enumerate(calls):
        function = (
            call.get("function")
            if isinstance(call, dict) and call.get("type") == "function"
            else None
        )
        if not isinstance(function, dict) or function.get("name") != spec["tool_name"]:
            raise ValueError("ambiguous_multiple_result_tools: wrong result tool name")
        argument_text = function.get("arguments")
        if not isinstance(argument_text, str):
            raise TypeError("ambiguous_multiple_result_tools: non-text arguments")
        repaired = False
        try:
            value = json.loads(
                argument_text, object_pairs_hook=_pairs, parse_constant=_invalid_constant
            )
        except json.JSONDecodeError as error:
            try:
                value, end = decoder.raw_decode(argument_text)
            except (ValueError, TypeError) as inner:
                raise ValueError("ambiguous_multiple_result_tools: malformed arguments") from inner
            if argument_text[end:] != "}" or not isinstance(value, dict):
                raise ValueError("ambiguous_multiple_result_tools: malformed arguments") from error
            repaired = True
        if not isinstance(value, dict) or not set(value).issubset(spec["parameters"]["properties"]):
            raise ValueError("ambiguous_multiple_result_tools: invalid payload fields")
        values.append(value)
        repairs.append(
            {
                "call_index": index,
                "raw_arguments_sha256": "sha256:"
                + hashlib.sha256(argument_text.encode("utf-8")).hexdigest(),
                "removed_exactly_one_trailing_right_brace": repaired,
            }
        )
    hashes = [_canonical_payload_hash(value) for value in values]
    maximal_hashes = {
        hashes[i]
        for i, value in enumerate(values)
        if all(_subsumes(value, other) for other in values)
    }
    if len(maximal_hashes) != 1:
        raise ValueError("ambiguous_multiple_result_tools: conflicting or incomparable payloads")
    selected_hash = next(iter(maximal_hashes))
    selected = next(value for value, digest in zip(values, hashes) if digest == selected_hash)
    if set(selected) != set(spec["parameters"]["properties"]):
        raise ValueError("strict output arguments have missing or extra fields")
    relationships = [
        {"subsumed_call_index": i, "by_call_index": j}
        for i, smaller in enumerate(values)
        for j, larger in enumerate(values)
        if i != j and _subsumes(larger, smaller)
    ]
    unique_hashes = set(hashes)
    reason = (
        "single_result_tool"
        if len(calls) == 1
        else "identical_result_tools"
        if len(unique_hashes) == 1
        else "unique_compatible_maximal_superset"
    )
    audit = {
        "result_tool_call_count": len(calls),
        "canonical_payload_hashes": hashes,
        "subsumption_relationships": relationships,
        "selected_maximal_payload_hash": selected_hash,
        "collapse_reason": reason,
        "syntax_repairs": repairs,
    }
    return selected, audit


def decode_baseline_output(raw: bytes, operation: str, count: int) -> dict[str, Any]:
    spec = baseline_output_spec(operation, count)
    value = _arguments(raw, spec)
    fields = (
        "candidate_id",
        "title",
        "mechanism",
        "evidence_summary",
        "falsifier",
        "discriminating_experiment",
        "prior_art_status",
    )
    candidates = []
    for index in range(1, count + 1):
        item = value[f"candidate_{index}"]
        if not isinstance(item, dict) or set(item) != set(fields):
            raise ValueError("strict candidate slot has missing or extra fields")
        candidates.append(item)
    return {"candidates": candidates}


def decode_claim_output(raw: bytes, skill_id: str, inputs: Mapping[str, Any]) -> dict[str, Any]:
    spec = claim_output_spec(skill_id, inputs)
    if spec["version"] == CLAIM_MULTI_VERSION:
        value, resolution = resolve_result_tool_calls(raw, spec)
    else:
        value, resolution = _arguments(raw, spec), None
    base = {
        "schema_version": 1,
        "research_plan_version": inputs["research_plan_version"],
        "hypothesis_id": inputs["hypothesis_id"],
        "hypothesis_content_hash": inputs["content_hash"],
    }
    if resolution is not None:
        base["result_tool_resolution"] = resolution
    if skill_id == "claim_decomposition":
        claims = []
        source_mode = inputs.get("claim_output_protocol") in {
            CLAIM_SOURCE_VERSION,
            CLAIM_MULTI_VERSION,
        }
        fields = {"include", "claim_id", "text", "claim_type", "subject", "relation", "object"} | (
            {"source_unit_ids", "source_relation", "model_quote"}
            if source_mode
            else {"source_span"}
        )
        source_by_id = (
            {u.source_unit_id: u for u in source_units_for_content(inputs)} if source_mode else {}
        )
        for slot, item in value.items():
            if (
                not isinstance(item, dict)
                or set(item) != fields
                or type(item["include"]) is not bool
            ):
                raise ValueError("strict claim slot has missing or extra fields")
            if item["include"]:
                importance, _ = slot.rsplit("_", 1)
                scientific = {key: val for key, val in item.items() if key != "include"}
                if source_mode:
                    ids = scientific.pop("source_unit_ids")
                    relation = scientific["source_relation"]
                    if (
                        not isinstance(ids, list)
                        or not ids
                        or len(ids) > len(source_by_id)
                        or any(not isinstance(i, str) or i not in source_by_id for i in ids)
                        or len(set(ids)) != len(ids)
                        or (relation in {"direct", "paraphrase"} and len(ids) != 1)
                        or (relation == "synthesized_from" and len(ids) < 2)
                    ):
                        raise ValueError("invalid or missing source unit binding")
                    units = [source_by_id[i] for i in ids]
                    scientific["source_span"] = "\n".join(u.exact_text for u in units)
                    scientific["source_unit_refs"] = [u.model_dump(mode="json") for u in units]
                claims.append(
                    {
                        **scientific,
                        "hypothesis_id": inputs["hypothesis_id"],
                        "hypothesis_content_hash": inputs["content_hash"],
                        "importance": importance,
                    }
                )
        return {**base, "claims": claims}
    proposals = []
    for index, claim in enumerate(inputs["critical_claims"], start=1):
        per_claim = value[f"claim_{index}"]
        if not isinstance(per_claim, dict) or set(per_claim) != set(INTENTS):
            raise ValueError("strict search slot has missing or extra intents")
        for intent in INTENTS:
            query = per_claim[intent]
            if not isinstance(query, dict) or set(query) != {"query", "rationale"}:
                raise ValueError("strict search query has missing or extra fields")
            proposals.append(
                {
                    "claim_id": claim["claim_id"],
                    "claim_content_hash": claim["hypothesis_content_hash"],
                    "intent": intent,
                    "provider": "pubmed",
                    "query": query["query"],
                    "rationale": query["rationale"],
                    "seen_source_ids": [],
                    "round": 1,
                    "fresh_retrieval": False,
                }
            )
    return {**base, "proposals": proposals}


_NON_SCIENTIFIC_METADATA = {
    "provider",
    "model",
    "round",
    "response_id",
    "request_id",
    "already_seen_source_ids",
    "seen_source_ids",
    "fresh_retrieval",
    "intent",
}


def _check_optional_binding(item: Mapping[str, Any], *, claim_id: str, content_hash: str) -> None:
    if item.get("claim_id", claim_id) != claim_id:
        raise ValueError("provider output claim_id does not match task input")
    for key in ("claim_content_hash", "hypothesis_content_hash"):
        if key in item and item[key] != content_hash:
            raise ValueError("provider output claim content hash does not match task input")


def _check_provider_metadata(item: Mapping[str, Any]) -> dict[str, Any]:
    unknown = set(item) - _NON_SCIENTIFIC_METADATA
    if unknown:
        raise ValueError(f"unknown scientific fields: {sorted(unknown)}")
    if "provider" in item and item["provider"] != "pubmed":
        raise ValueError("search provider metadata must be pubmed")
    if "round" in item and (type(item["round"]) is not int or item["round"] < 1):
        raise ValueError("search round metadata must be a positive integer")
    seen = item.get("already_seen_source_ids", item.get("seen_source_ids", []))
    if not isinstance(seen, list) or any(not isinstance(value, str) for value in seen):
        raise ValueError("seen source metadata must be a string list")
    fresh = item.get("fresh_retrieval", False)
    if type(fresh) is not bool:
        raise ValueError("fresh retrieval metadata must be boolean")
    intent = item.get("intent")
    if intent is not None and intent not in INTENTS:
        raise ValueError("intent metadata is not a recognized search intent")
    return {"round": item.get("round", 1), "seen_source_ids": seen, "fresh_retrieval": fresh}


def _normalized_payload(value: Any) -> tuple[Any, dict[str, Any]]:
    if isinstance(value, Mapping) and isinstance(value.get("payload"), (Mapping, list)):
        payload = value["payload"]
        audit = value.get("resolution_audit", {})
        return payload, dict(audit) if isinstance(audit, Mapping) else {}
    payload = getattr(value, "payload", value)
    audit_value = getattr(value, "resolution_audit", {})
    if not isinstance(payload, (Mapping, list)):
        raise TypeError("ProviderNormalizedResult payload must be an object or list")
    return payload, dict(audit_value) if isinstance(audit_value, Mapping) else {}


def _claim_entries(payload: Any) -> list[tuple[str | None, Mapping[str, Any]]]:
    if isinstance(payload, list):
        return [(None, item) if isinstance(item, Mapping) else (None, {}) for item in payload]
    if not isinstance(payload, Mapping):
        raise TypeError("claim decomposition output must be an object or list")
    if "claims" in payload:
        extras = set(payload) - {"claims", "provider", "model", "response_id", "request_id"}
        if extras:
            raise ValueError(f"unknown claim result fields: {sorted(extras)}")
        claims = payload["claims"]
        if not isinstance(claims, list):
            raise TypeError("claims must be a list")
        return [(None, item) if isinstance(item, Mapping) else (None, {}) for item in claims]
    entries = []
    for slot, item in payload.items():
        match = re.fullmatch(r"(critical|supporting)_(\d+)", str(slot))
        if match is None or not isinstance(item, Mapping):
            raise ValueError(f"unknown claim result slot: {slot}")
        entries.append((match.group(1), item))
    return entries


def normalize_claim_result(
    normalized: Any, skill_id: str, inputs: Mapping[str, Any]
) -> dict[str, Any]:
    """Map a provider-normalized object to locally bound claim/search domain fields."""
    protocol = inputs.get("claim_output_protocol")
    if protocol not in {
        CLAIM_SOURCE_VERSION,
        CLAIM_MULTI_VERSION,
        CLAIM_NORMALIZED_VERSION,
        CLAIM_PROVIDER_JSON_VERSION,
    }:
        raise DomainValidationError("normalized claims require a SourceUnit claim contract")
    payload, audit = _normalized_payload(normalized)
    base = {
        "schema_version": 1,
        "research_plan_version": inputs["research_plan_version"],
        "hypothesis_id": inputs["hypothesis_id"],
        "hypothesis_content_hash": inputs["content_hash"],
    }
    if protocol == CLAIM_MULTI_VERSION and audit:
        base["result_tool_resolution"] = audit
    if skill_id == "claim_decomposition":
        policy = ClaimDecompositionOutputPolicy.model_validate(
            inputs.get("claim_decomposition_output")
        )
        verification = ClaimVerificationPolicy.model_validate(
            inputs.get("claim_verification_policy")
        )
        source_by_id = {unit.source_unit_id: unit for unit in source_units_for_content(inputs)}
        entries = _claim_entries(payload)
        if not entries or len(entries) > policy.max_total_claims:
            raise ScientificValidationFailure("claim count outside frozen total limit")
        claims: list[dict[str, Any]] = []
        allowed = {
            "include",
            "importance",
            "claim_id",
            "text",
            "claim_type",
            "subject",
            "relation",
            "object",
            "source_unit_ids",
            "source_relation",
            "model_quote",
            "hypothesis_id",
            "hypothesis_content_hash",
        }
        for slot_importance, item in entries:
            if item.get("include", True) is False:
                if type(item.get("include", False)) is not bool:
                    raise DomainValidationError("claim include marker must be boolean")
                continue
            if "include" in item and type(item["include"]) is not bool:
                raise DomainValidationError("claim include marker must be boolean")
            unknown = set(item) - allowed - _NON_SCIENTIFIC_METADATA
            if unknown:
                raise DomainValidationError(f"unknown scientific fields: {sorted(unknown)}")
            importance = slot_importance or item.get("importance")
            if importance not in {"critical", "supporting"}:
                raise DomainValidationError(
                    "included claim requires critical/supporting importance"
                )
            if (
                slot_importance is not None
                and item.get("importance", slot_importance) != slot_importance
            ):
                raise DomainValidationError("claim importance conflicts with its provider slot")
            if item.get("hypothesis_id", inputs["hypothesis_id"]) != inputs["hypothesis_id"]:
                raise ScientificValidationFailure("claim hypothesis binding mismatch")
            if (
                item.get("hypothesis_content_hash", inputs["content_hash"])
                != inputs["content_hash"]
            ):
                raise ScientificValidationFailure("claim content hash binding mismatch")
            fields = {
                key: item[key]
                for key in (
                    "claim_id",
                    "text",
                    "claim_type",
                    "subject",
                    "relation",
                    "object",
                    "source_relation",
                )
                if key in item
            }
            ids = item.get("source_unit_ids")
            relation = item.get("source_relation")
            if (
                not isinstance(ids, list)
                or not ids
                or len(ids) > len(source_by_id)
                or any(
                    not isinstance(source_id, str) or source_id not in source_by_id
                    for source_id in ids
                )
                or len(set(ids)) != len(ids)
                or (relation in {"direct", "paraphrase"} and len(ids) != 1)
                or (relation == "synthesized_from" and len(ids) < 2)
            ):
                raise ScientificValidationFailure("invalid or missing source unit binding")
            units = [source_by_id[source_id] for source_id in ids]
            claim_id = item.get("claim_id")
            if not isinstance(claim_id, str) or not claim_id.strip():
                identity = {
                    key: item.get(key)
                    for key in (
                        "importance",
                        "text",
                        "claim_type",
                        "subject",
                        "relation",
                        "object",
                        "source_relation",
                        "source_unit_ids",
                    )
                }
                digest = hashlib.sha256(
                    json.dumps(
                        identity,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    ).encode()
                ).hexdigest()[:20]
                claim_id = f"claim-{digest}"
            claims.append(
                {
                    **fields,
                    "hypothesis_id": inputs["hypothesis_id"],
                    "claim_id": claim_id,
                    "hypothesis_content_hash": inputs["content_hash"],
                    "importance": importance,
                    "source_span": "\n".join(unit.exact_text for unit in units),
                    "source_unit_refs": [unit.model_dump(mode="json") for unit in units],
                    **({"model_quote": item["model_quote"]} if "model_quote" in item else {}),
                }
            )
        critical_count = sum(item["importance"] == "critical" for item in claims)
        if (
            not claims
            or len(claims) > policy.max_total_claims
            or critical_count > verification.max_critical_claims_per_hypothesis
        ):
            raise ScientificValidationFailure("claim count outside frozen total/critical limits")
        scientific_fingerprints = {
            json.dumps(
                {
                    key: claim[key]
                    for key in (
                        "importance",
                        "text",
                        "claim_type",
                        "subject",
                        "relation",
                        "object",
                        "source_relation",
                        "source_span",
                    )
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            for claim in claims
        }
        if len(scientific_fingerprints) != len(claims):
            raise ScientificValidationFailure("duplicate scientific claim content")
        if len({item["claim_id"] for item in claims}) != len(claims):
            raise ScientificValidationFailure("duplicate claim id")
        return {**base, "claims": claims}
    if skill_id != "claim_search_plan":
        raise DomainValidationError("normalized claim result supports decomposition/search only")
    critical_claims = inputs.get("critical_claims")
    if not isinstance(critical_claims, list) or not critical_claims:
        raise DomainValidationError("search plan requires critical claim inputs")
    by_id = {str(claim["claim_id"]): claim for claim in critical_claims}
    queries_by_claim: dict[str, dict[str, dict[str, Any]]] = {key: {} for key in by_id}
    metadata_by_claim: dict[str, dict[str, Any]] = {
        key: {"round": 1, "seen_source_ids": [], "fresh_retrieval": False} for key in by_id
    }

    def bind_plan(item: Mapping[str, Any], positional_id: str | None = None) -> str:
        claim_id = item.get("claim_id", positional_id)
        if not isinstance(claim_id, str) or claim_id not in by_id:
            raise ScientificValidationFailure("search plan claim binding is missing or invalid")
        target = by_id[claim_id]
        content_hash = target["hypothesis_content_hash"]
        _check_optional_binding(item, claim_id=claim_id, content_hash=content_hash)
        return claim_id

    def add_query(
        claim_id: str, intent: str, query_value: Any, plan_metadata: Mapping[str, Any]
    ) -> None:
        if intent not in INTENTS:
            raise ScientificValidationFailure("unknown search intent")
        if intent in queries_by_claim[claim_id]:
            raise ScientificValidationFailure(f"duplicate search intent: {intent}")
        if isinstance(query_value, str):
            query_text: Any = query_value
            rationale = None
        elif isinstance(query_value, Mapping):
            allowed = {
                "query",
                "rationale",
                "intent",
                "claim_id",
                "claim_content_hash",
                "hypothesis_content_hash",
                *_NON_SCIENTIFIC_METADATA,
            }
            unknown = set(query_value) - allowed
            if unknown:
                raise ValueError(f"unknown scientific fields: {sorted(unknown)}")
            if query_value.get("intent", intent) != intent:
                raise ScientificValidationFailure("nested search intent does not match its key")
            _check_optional_binding(
                query_value,
                claim_id=claim_id,
                content_hash=by_id[claim_id]["hypothesis_content_hash"],
            )
            query_text = query_value.get("query")
            rationale = query_value.get("rationale")
        else:
            raise TypeError("search query must be text or a structured query")
        if (
            not isinstance(query_text, str)
            or not query_text.strip()
            or not isinstance(rationale, str)
            or not rationale.strip()
        ):
            raise ValueError("search query and rationale are required")
        metadata = _check_provider_metadata(
            {key: value for key, value in plan_metadata.items() if key in _NON_SCIENTIFIC_METADATA}
        )
        metadata_by_claim[claim_id] = metadata
        queries_by_claim[claim_id][intent] = {"query": query_text, "rationale": rationale}

    def add_plan(item: Mapping[str, Any], positional_id: str | None = None) -> None:
        claim_id = bind_plan(item, positional_id)
        if "queries" in item:
            unknown = set(item) - {
                "claim_id",
                "claim_content_hash",
                "hypothesis_content_hash",
                "queries",
                *_NON_SCIENTIFIC_METADATA,
            }
            if unknown:
                raise DomainValidationError(f"unknown scientific fields: {sorted(unknown)}")
            queries = item["queries"]
            if not isinstance(queries, list):
                raise TypeError("plan queries must be a list")
            meta = {key: value for key, value in item.items() if key in _NON_SCIENTIFIC_METADATA}
            for query_item in queries:
                if not isinstance(query_item, Mapping) or not isinstance(
                    query_item.get("intent"), str
                ):
                    raise DomainValidationError("each search query requires an intent")
                add_query(claim_id, query_item["intent"], query_item, meta)
            return
        direct = {intent: item[intent] for intent in INTENTS if intent in item}
        binding_metadata = {"claim_id", "claim_content_hash", "hypothesis_content_hash"}
        metadata = {key: value for key, value in item.items() if key in _NON_SCIENTIFIC_METADATA}
        unknown = set(item) - set(direct) - set(metadata) - binding_metadata
        if unknown:
            raise DomainValidationError(f"unknown scientific fields: {sorted(unknown)}")
        for intent, query_item in direct.items():
            add_query(claim_id, intent, query_item, metadata)

    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, Mapping):
                raise TypeError("search plan entries must be objects")
            add_plan(item)
    elif isinstance(payload, Mapping) and "plans" in payload:
        extras = set(payload) - {"plans", "provider", "model", "response_id", "request_id"}
        if extras:
            raise ValueError(f"unknown search result fields: {sorted(extras)}")
        plans = payload["plans"]
        if not isinstance(plans, list):
            raise TypeError("plans must be a list")
        for item in plans:
            if not isinstance(item, Mapping):
                raise TypeError("search plan entries must be objects")
            add_plan(item)
    elif isinstance(payload, Mapping) and "queries" in payload:
        flat = payload["queries"]
        if not isinstance(flat, list):
            raise TypeError("queries must be a list")
        for item in flat:
            if not isinstance(item, Mapping):
                raise TypeError("search query entries must be objects")
            add_plan(
                {
                    "queries": [item],
                    **{
                        key: item[key]
                        for key in ("claim_id", "claim_content_hash", "hypothesis_content_hash")
                        if key in item
                    },
                }
            )
    elif isinstance(payload, Mapping):
        for slot, item in payload.items():
            match = re.fullmatch(r"claim_(\d+)", str(slot))
            if match is None or not isinstance(item, Mapping):
                raise ValueError(f"unknown search plan slot: {slot}")
            index = int(match.group(1)) - 1
            positional_id = (
                str(critical_claims[index]["claim_id"])
                if 0 <= index < len(critical_claims)
                else None
            )
            add_plan(item, positional_id)
    else:
        raise TypeError("search plan output must be an object or list")

    proposals = []
    for claim in critical_claims:
        claim_id = str(claim["claim_id"])
        intents = queries_by_claim[claim_id]
        if set(intents) != set(INTENTS):
            raise ScientificValidationFailure(
                f"required search intents missing for claim {claim_id}"
            )
        metadata = metadata_by_claim[claim_id]
        for intent in INTENTS:
            proposals.append(
                {
                    "claim_id": claim_id,
                    "claim_content_hash": claim["hypothesis_content_hash"],
                    "intent": intent,
                    "provider": "pubmed",
                    **intents[intent],
                    **metadata,
                }
            )
    return {**base, "proposals": proposals}
