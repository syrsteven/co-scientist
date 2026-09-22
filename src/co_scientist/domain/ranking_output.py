"""Opt-in, versioned Ranking wire encoding; never repairs a model response."""

import json
from collections.abc import Mapping
from typing import Any

from co_scientist.ports.external_provider import thaw_json

STRICT_RANKING_VERSION = "deepseek-strict-tool-v1"
FLAT_RANKING_VERSION = "deepseek-strict-tool-v2"
STRICT_RANKING_URL = "https://api.deepseek.com/beta/chat/completions"
IDENTITY_FIELDS = (
    "research_plan_version", "match_id", "epoch_id", "left_id", "left_content_hash",
    "right_id", "right_content_hash", "evaluation_rules_hash", "ranking_prompt_hash",
    "judge_profile_hash", "rating_policy_version", "admission_policy_version",
)


def strict_ranking_contract(version: str = STRICT_RANKING_VERSION) -> dict[str, Any]:
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
    return {**contract, "version": version, "tool_name": "submit_ranking_result_v2",
        "reason_fields": {key: f"reason_{key}" for key in (
            "goal_alignment", "causal_specificity", "evidence_grounding",
            "literature_novelty", "discriminating_tests", "robustness_and_safety",
        )},
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
    if not isinstance(contract, dict) or contract != strict_ranking_contract(contract.get("version", "")):
        raise ValueError("unsupported or altered Ranking output contract")
    rubric = inputs.get("evaluation_rubric")
    dimensions = rubric.get("dimensions") if isinstance(rubric, Mapping) else None
    if not isinstance(dimensions, Mapping) or not dimensions:
        raise ValueError("strict Ranking requires rubric dimensions")
    properties: dict[str, Any] = {"schema_version": {"type": "integer", "enum": [1]}}
    for field in IDENTITY_FIELDS:
        value = inputs.get(field)
        kind = "integer" if field == "research_plan_version" else "string"
        if (kind == "integer" and (type(value) is not int or value < 1)) or (
            kind == "string" and (not isinstance(value, str) or not value.strip())
        ):
            raise ValueError(f"strict Ranking requires binding {field}")
        properties[field] = {"type": kind, "enum": [value]}
    text = {"type": "string", "pattern": r"\S"}
    properties.update({
        "decision_status": {"type": "string", "enum": [
            "decisive", "inconclusive", "invalid", "needs_tiebreaker",
        ]},
        "winner_slot": {"type": "integer", "enum": [0, 1, 2]},
        "dimension_reasons": {
            "type": "object", "properties": {key: dict(text) for key in dimensions},
            "required": list(dimensions), "additionalProperties": False,
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "unresolved_disagreements": {"type": "array", "items": text},
    })
    if contract["version"] == FLAT_RANKING_VERSION:
        if set(dimensions) != set(contract["reason_fields"]):
            raise ValueError("flat Ranking requires the frozen six-dimension rubric")
        properties.pop("dimension_reasons")
        properties.update({field: dict(text) for field in contract["reason_fields"].values()})
    return {**contract, "parameters": {
        "type": "object", "properties": properties, "required": list(properties),
        "additionalProperties": False,
    }}


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
    if not isinstance(message, dict) or message.get("content") not in (None, ""):
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
    fields = spec["parameters"]["properties"]
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError("strict Ranking arguments have missing or extra fields")
    for field in ("schema_version", *IDENTITY_FIELDS):
        expected = fields[field]["enum"][0]
        if type(value[field]) is not type(expected) or value[field] != expected:
            raise ValueError(f"strict Ranking binding mismatch: {field}")
    if spec["version"] == FLAT_RANKING_VERSION:
        reasons = {key: value[field] for key, field in spec["reason_fields"].items()}
        expected_dimensions = spec["reason_fields"]
    else:
        reasons = value["dimension_reasons"]
        expected_dimensions = fields["dimension_reasons"]["properties"]
    if (not isinstance(reasons, dict) or set(reasons) != set(expected_dimensions)
            or any(not isinstance(v, str) or not v.strip() for v in reasons.values())):
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
    if spec["version"] == FLAT_RANKING_VERSION:
        value = {key: item for key, item in value.items() if key not in spec["reason_fields"].values()}
    return {**value, "dimension_reasons": reasons, "winner_slot": None if slot == 0 else slot}
