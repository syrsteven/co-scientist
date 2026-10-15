"""Opt-in, versioned Ranking wire encoding; never repairs a model response."""

import json
from collections.abc import Mapping
from typing import Any

from co_scientist.adapters.llm.output_errors import DomainValidationError
from co_scientist.ports.external_provider import thaw_json

STRICT_RANKING_VERSION = "deepseek-strict-tool-v1"
FLAT_RANKING_VERSION = "deepseek-strict-tool-v2"
EVIDENCE_RANKING_VERSION = "deepseek-strict-tool-v3"
BOUND_RANKING_VERSION = "deepseek-strict-tool-v4"
JSON_RANKING_VERSION = "deepseek-result-json-v5"
STRICT_RANKING_URL = "https://api.deepseek.com/beta/chat/completions"
IDENTITY_FIELDS = (
    "research_plan_version",
    "match_id",
    "epoch_id",
    "left_id",
    "left_content_hash",
    "right_id",
    "right_content_hash",
    "evaluation_rules_hash",
    "ranking_prompt_hash",
    "judge_profile_hash",
    "rating_policy_version",
    "admission_policy_version",
)


def strict_ranking_contract(version: str = STRICT_RANKING_VERSION) -> dict[str, Any]:
    if version == JSON_RANKING_VERSION:
        base = strict_ranking_contract(BOUND_RANKING_VERSION)
        return {
            **base,
            "version": version,
            "tool_name": None,
            "instructions": "Return one JSON object with the declared ranking fields. "
            "This is a pure result, not an action or tool call. Preserve every task "
            "identity, scientific rubric, decision, confidence, and unresolved "
            "disagreement. Local validation is authoritative; do not update ratings.",
        }
    if version == BOUND_RANKING_VERSION:
        base = strict_ranking_contract(EVIDENCE_RANKING_VERSION)
        return {
            **base,
            "version": version,
            "tool_name": "submit_ranking_result_v4",
            "instructions": base["instructions"].replace(
                "submit_ranking_result_v3", "submit_ranking_result_v4"
            )
            + " The function arguments MUST NOT contain schema_version. The local "
            "codec supplies canonical result schema_version=1 after validating "
            "every tool argument. The v4 function name is the transport version, "
            "not the scientific result schema version. Call only this function; "
            "leave message.content empty. Only function arguments are used as "
            "the scientific result.",
        }
    if version == EVIDENCE_RANKING_VERSION:
        base = strict_ranking_contract(FLAT_RANKING_VERSION)
        return {
            **base,
            "version": version,
            "tool_name": "submit_ranking_result_v3",
            "instructions": base["instructions"].replace(
                "submit_ranking_result_v2", "submit_ranking_result_v3"
            )
            + " Copy the frozen evidence_context_hash exactly; it binds this comparison "
            "to the current reviewed evidence snapshot.",
        }
    contract = {
        "version": STRICT_RANKING_VERSION,
        "provider": "deepseek",
        "endpoint": STRICT_RANKING_URL,
        "tool_name": "submit_ranking_result",
        "tool_choice": "auto",
        "winner_encoding": "zero-is-null-v1",
        "instructions": (
            "For this Ranking task the final output transport is the single "
            "submit_ranking_result function, not message.content. Call it exactly once. "
            "Its arguments encode RankingResultV1 with one explicit wire difference: "
            "winner_slot=0 means no winner (canonical null); use 1 or 2 only for decisive. "
            "This transport rule overrides the plain-text JSON output instruction, not "
            "the scientific rubric or task bindings. Give all six dimension reasons and "
            "an unresolved_disagreements array (empty if none); close all arrays/objects. "
            "Do not output commentary or call other tools. The function is an output "
            "channel only: it cannot create tasks, execute experiments or update ratings."
        ),
    }
    if version == STRICT_RANKING_VERSION:
        return contract
    if version != FLAT_RANKING_VERSION:
        raise ValueError("unsupported Ranking output version")
    return {
        **contract,
        "version": version,
        "tool_name": "submit_ranking_result_v2",
        "reason_fields": {
            key: f"reason_{key}"
            for key in (
                "goal_alignment",
                "causal_specificity",
                "evidence_grounding",
                "literature_novelty",
                "discriminating_tests",
                "robustness_and_safety",
            )
        },
        "instructions": (
            "For this Ranking task call submit_ranking_result_v2 exactly once. This is a "
            "flat output transport, not plain message.content JSON. Preserve every task "
            "identity, scientific rubric, decision, confidence and unresolved disagreement. "
            "Use the six top-level reason_<dimension> string fields declared in the tool "
            "schema; each contains the full scientific reason for that dimension. Do not "
            "emit a nested dimension_reasons object or use prose as a JSON key. The local "
            "codec maps these six named fields losslessly to canonical dimension_reasons. "
            "winner_slot=0 encodes canonical null for a non-decisive result; 1 or 2 is "
            "allowed only for decisive. unresolved_disagreements is an array, empty if none. "
            "This versioned transport overrides instructions to output canonical JSON text, "
            "not scientific requirements. Do not shorten or omit evidence to satisfy the "
            "format. No commentary or other tools. This output channel cannot create tasks, "
            "execute experiments, change budgets or update ratings."
        ),
    }


def ranking_output_spec(inputs: Mapping[str, Any]) -> dict[str, Any] | None:
    contract = thaw_json(inputs.get("ranking_output_contract"))
    if contract is None:
        return None
    if not isinstance(contract, dict) or contract != strict_ranking_contract(
        contract.get("version", "")
    ):
        raise ValueError("unsupported or altered Ranking output contract")
    rubric = inputs.get("evaluation_rubric")
    dimensions = rubric.get("dimensions") if isinstance(rubric, Mapping) else None
    if not isinstance(dimensions, Mapping) or not dimensions:
        raise ValueError("strict Ranking requires rubric dimensions")
    properties: dict[str, Any] = (
        {}
        if contract["version"] == BOUND_RANKING_VERSION
        else {"schema_version": {"type": "integer", "enum": [1]}}
    )
    identity_fields = (
        (*IDENTITY_FIELDS, "evidence_context_hash")
        if (
            contract["version"]
            in {EVIDENCE_RANKING_VERSION, BOUND_RANKING_VERSION, JSON_RANKING_VERSION}
        )
        else IDENTITY_FIELDS
    )
    for field in identity_fields:
        value = inputs.get(field)
        kind = "integer" if field == "research_plan_version" else "string"
        if (kind == "integer" and (type(value) is not int or value < 1)) or (
            kind == "string" and (not isinstance(value, str) or not value.strip())
        ):
            raise ValueError(f"strict Ranking requires binding {field}")
        properties[field] = {"type": kind, "enum": [value]}
    text = {"type": "string", "pattern": r"\S"}
    properties.update(
        {
            "decision_status": {
                "type": "string",
                "enum": [
                    "decisive",
                    "inconclusive",
                    "invalid",
                    "needs_tiebreaker",
                ],
            },
            "winner_slot": {"type": "integer", "enum": [0, 1, 2]},
            "dimension_reasons": {
                "type": "object",
                "properties": {key: dict(text) for key in dimensions},
                "required": list(dimensions),
                "additionalProperties": False,
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "unresolved_disagreements": {"type": "array", "items": text},
        }
    )
    if contract["version"] in {
        FLAT_RANKING_VERSION,
        EVIDENCE_RANKING_VERSION,
        BOUND_RANKING_VERSION,
        JSON_RANKING_VERSION,
    }:
        if set(dimensions) != set(contract["reason_fields"]):
            raise ValueError("flat Ranking requires the frozen six-dimension rubric")
        properties.pop("dimension_reasons")
        properties.update({field: dict(text) for field in contract["reason_fields"].values()})
    return {
        **contract,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
    }


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("strict Ranking JSON contains duplicate keys")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise ValueError("strict Ranking JSON contains a non-finite constant")


def decode_strict_ranking(raw: bytes, inputs: Mapping[str, Any]) -> dict[str, Any]:
    """Called only after raw persistence; explicit 0→null codec, no JSON repair."""
    spec = ranking_output_spec(inputs)
    if spec is None:
        raise ValueError("missing strict Ranking output contract")
    envelope = json.loads(raw, object_pairs_hook=_object, parse_constant=_constant)
    choices = envelope.get("choices") if isinstance(envelope, dict) else None
    if not isinstance(choices, list) or len(choices) != 1:
        raise ValueError("strict Ranking requires exactly one response choice")
    choice = choices[0]
    if not isinstance(choice, dict) or choice.get("finish_reason") != "tool_calls":
        raise ValueError("strict Ranking requires tool_calls finish; no text fallback")
    message = choice.get("message", {})
    if not isinstance(message, dict):
        raise TypeError("strict Ranking requires a message object")
    content = message.get("content")
    if spec["version"] == BOUND_RANKING_VERSION:
        # Persisted as raw, but never read into the scientific result.
        if content is not None and (not isinstance(content, str) or len(content) > 8192):
            raise ValueError("strict Ranking auxiliary text is invalid or oversized")
    elif content not in (None, ""):
        raise ValueError("strict Ranking rejects mixed text and tool output")
    calls = message.get("tool_calls")
    if not isinstance(calls, list) or len(calls) != 1:
        raise ValueError("strict Ranking requires exactly one result tool")
    call = calls[0]
    if not isinstance(call, dict) or call.get("type") != "function":
        raise ValueError("strict Ranking requires a function result")
    function = call.get("function", {})
    if not isinstance(function, dict) or function.get("name") != spec["tool_name"]:
        raise ValueError("strict Ranking result tool name mismatch")
    arguments = function.get("arguments")
    if not isinstance(arguments, str):
        raise TypeError("strict Ranking tool arguments must be a JSON string")
    value = json.loads(arguments, object_pairs_hook=_object, parse_constant=_constant)
    return _validate_ranking_value(value, spec)


def decode_provider_ranking(normalized: Any, inputs: Mapping[str, Any]) -> dict[str, Any]:
    """Validate provider-normalized pure JSON without converting it to a fake tool call."""
    spec = ranking_output_spec(inputs)
    if spec is None or spec["version"] != JSON_RANKING_VERSION:
        raise ValueError("provider JSON Ranking requires its frozen v5 contract")
    value = getattr(normalized, "payload", None)
    if not isinstance(value, Mapping):
        raise DomainValidationError("Ranking provider result must be a JSON object")
    return _validate_ranking_value(dict(value), spec)


def _validate_ranking_value(value: Any, spec: Mapping[str, Any]) -> dict[str, Any]:
    fields = spec["parameters"]["properties"]
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError("Ranking result has missing or extra fields")
    binding_fields = list(IDENTITY_FIELDS)
    if spec["version"] != BOUND_RANKING_VERSION:
        binding_fields.insert(0, "schema_version")
    if spec["version"] in {EVIDENCE_RANKING_VERSION, BOUND_RANKING_VERSION, JSON_RANKING_VERSION}:
        binding_fields.append("evidence_context_hash")
    for field in binding_fields:
        expected = fields[field]["enum"][0]
        if type(value[field]) is not type(expected) or value[field] != expected:
            raise ValueError(f"strict Ranking binding mismatch: {field}")
    if spec["version"] in {
        FLAT_RANKING_VERSION,
        EVIDENCE_RANKING_VERSION,
        BOUND_RANKING_VERSION,
        JSON_RANKING_VERSION,
    }:
        reasons = {key: value[field] for key, field in spec["reason_fields"].items()}
        expected_dimensions = spec["reason_fields"]
    else:
        reasons = value["dimension_reasons"]
        expected_dimensions = fields["dimension_reasons"]["properties"]
    if (
        not isinstance(reasons, dict)
        or set(reasons) != set(expected_dimensions)
        or any(not isinstance(v, str) or not v.strip() for v in reasons.values())
    ):
        raise ValueError("strict Ranking requires exactly the rubric dimension reasons")
    slot = value["winner_slot"]
    if type(slot) is not int or slot not in (0, 1, 2):
        raise ValueError("strict Ranking winner_slot must be 0, 1 or 2")
    confidence = value["confidence"]
    if type(confidence) not in (int, float) or not 0 <= confidence <= 1:
        raise ValueError("strict Ranking confidence must be a number from 0 to 1")
    disagreements = value["unresolved_disagreements"]
    if not isinstance(disagreements, list) or any(
        not isinstance(v, str) or not v.strip() for v in disagreements
    ):
        raise ValueError("strict Ranking disagreements must be an array of nonblank strings")
    # The registered canonical schema still validates decisions and winner consistency.
    if spec["version"] in {
        FLAT_RANKING_VERSION,
        EVIDENCE_RANKING_VERSION,
        BOUND_RANKING_VERSION,
        JSON_RANKING_VERSION,
    }:
        value = {
            key: item for key, item in value.items() if key not in spec["reason_fields"].values()
        }
    return {
        **value,
        **({"schema_version": 1} if spec["version"] == BOUND_RANKING_VERSION else {}),
        "dimension_reasons": reasons,
        "winner_slot": None if slot == 0 else slot,
    }
