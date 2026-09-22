"""Flattening is a versioned codec, not permission to repair invalid scientific output."""

import copy
import json

import httpx
import pytest

from co_scientist.adapters.llm.multi_provider import NativeJSONProvider
from co_scientist.agents.executor import build_skill_request
from co_scientist.agents.payloads import RankingResultV1
from co_scientist.application.output_diagnostics import json_syntax_diagnostic
from co_scientist.domain.ranking_output import (
    FLAT_RANKING_VERSION,
    decode_strict_ranking,
    ranking_output_spec,
)
from co_scientist.runtime.external_calls import request_fingerprint
from co_scientist.runtime.task_payload import validate_result_task_binding
from co_scientist.skills.loader import core_skill_directory
from co_scientist.supervisor.scientific_context import research_inputs
from tests.unit.runtime.test_ranking_output import configuration, envelope, payload
from tests.unit.runtime.test_research_protocol import anchor_input


@pytest.fixture
def inputs(tmp_path):
    manifest = configuration(tmp_path, version=FLAT_RANKING_VERSION).model_dump(mode="json")["manifest"]
    events, pair = anchor_input(manifest)
    return research_inputs(manifest, events, pair, skill_id="ranking")


def flat_payload(inputs, *, decision="decisive", slot=1):
    value = payload(inputs, decision=decision, slot=slot)
    reasons = value.pop("dimension_reasons")
    return {**value, **{f"reason_{key}": text for key, text in reasons.items()}}


@pytest.mark.parametrize("decision,slot", [
    ("decisive", 1), ("decisive", 2), ("inconclusive", 0),
    ("invalid", 0), ("needs_tiebreaker", 0),
])
def test_flat_codec_preserves_all_scientific_fields(inputs, decision, slot):
    value = flat_payload(inputs, decision=decision, slot=slot)
    text = 'A full reason with "quotes", colon: braces {}, Unicode 中文, and\na new line.'
    value["reason_causal_specificity"] = text
    raw = json.dumps(envelope(value, name="submit_ranking_result_v2")).encode()
    result = RankingResultV1.model_validate(decode_strict_ranking(raw, inputs))
    validate_result_task_binding(task_inputs=inputs, task_research_plan_version=1,
                                 provider_id="deepseek", result=result)
    assert result.dimension_reasons["causal_specificity"] == text
    assert result.winner_slot == (slot or None)
    assert result.unresolved_disagreements == tuple(value["unresolved_disagreements"])
    assert set(result.dimension_reasons) == set(inputs["evaluation_rubric"]["dimensions"])


@pytest.mark.parametrize("fault", ["missing", "nested", "empty", "wrong_type", "binding",
                                   "extra", "bad_slot", "bad_confidence", "mixed_version"])
def test_flat_fields_are_exact_and_do_not_relax_validation(inputs, fault):
    value = flat_payload(inputs)
    name = "submit_ranking_result_v2"
    if fault == "missing":
        value.pop("reason_goal_alignment")
    elif fault == "nested":
        value["dimension_reasons"] = payload(inputs)["dimension_reasons"]
    elif fault == "empty":
        value["reason_goal_alignment"] = " "
    elif fault == "wrong_type":
        value["reason_goal_alignment"] = ["not a string"]
    elif fault == "binding":
        value["match_id"] = "another-match"
    elif fault == "extra":
        value["reason_fake"] = "unregistered"
    elif fault == "bad_slot":
        value["winner_slot"] = 0
    elif fault == "bad_confidence":
        value["confidence"] = True
    else:
        name = "submit_ranking_result"
    with pytest.raises((TypeError, ValueError)):
        RankingResultV1.model_validate(decode_strict_ranking(json.dumps(envelope(value, name=name)).encode(), inputs))


@pytest.mark.parametrize("version", ["deepseek-strict-tool-v1", FLAT_RANKING_VERSION])
def test_run010_spurious_colon_shape_stays_invalid_without_touching_raw(tmp_path, version):
    manifest = configuration(tmp_path, version=version).model_dump(mode="json")["manifest"]
    events, pair = anchor_input(manifest)
    inputs = research_inputs(manifest, events, pair, skill_id="ranking")
    value = flat_payload(inputs) if version == FLAT_RANKING_VERSION else payload(inputs)
    body = envelope(value, name=inputs["ranking_output_contract"]["tool_name"])
    function = body["choices"][0]["message"]["tool_calls"][0]["function"]
    function["arguments"] = function["arguments"].replace(
        '"Synthetic comparison, not a scientific finding."',
        '"Synthetic comparison, not a scientific finding.": ""', 1,
    )
    raw = json.dumps(body).encode()
    before = bytes(raw)
    with pytest.raises(json.JSONDecodeError):
        decode_strict_ranking(raw, inputs)
    diagnostic = json_syntax_diagnostic(raw, "deepseek")
    assert diagnostic["code"] == "invalid_json"
    assert diagnostic["channel"] == "tool.arguments"
    assert 0 < diagnostic["position"] < len(function["arguments"]) - 1
    assert raw == before


@pytest.mark.asyncio
async def test_new_identity_and_actual_flat_http_schema_without_altering_v1(tmp_path, inputs):
    spec = ranking_output_spec(inputs)
    fields = spec["parameters"]["properties"]
    assert "dimension_reasons" not in fields
    assert all(value["type"] != "object" for value in fields.values())
    assert set(spec["parameters"]["required"]) == set(fields)
    old = configuration(tmp_path).model_dump(mode="json")["manifest"]
    events, pair = anchor_input(old)
    old_inputs = research_inputs(old, events, pair, skill_id="ranking")
    assert old_inputs["evaluation_rules_hash"] != inputs["evaluation_rules_hash"]
    assert old_inputs["judge_profile_hash"] != inputs["judge_profile_hash"]
    assert old_inputs["ranking_prompt_hash"] == inputs["ranking_prompt_hash"]
    assert "dimension_reasons" in ranking_output_spec(old_inputs)["parameters"]["properties"]
    request = build_skill_request(skill_directory=core_skill_directory("ranking"), inputs=inputs, model="offline-model")
    old_request = build_skill_request(skill_directory=core_skill_directory("ranking"), inputs=old_inputs, model="offline-model")
    assert request_fingerprint(request) != request_fingerprint(old_request)
    raw = json.dumps(envelope(flat_payload(inputs), name=spec["tool_name"])).encode()
    seen = []

    def handle(http_request):
        body = json.loads(http_request.content)
        seen.append(body)
        assert body["tools"][0]["function"]["parameters"] == spec["parameters"]
        assert body["tools"][0]["function"]["strict"] is True
        assert body["tool_choice"] == "auto"
        return httpx.Response(200, content=raw)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        response = await NativeJSONProvider(client, provider="deepseek", api_key="offline-secret").invoke(request)
    assert response.body == raw and len(seen) == 1
    altered = copy.deepcopy(inputs)
    altered["ranking_output_contract"]["reason_fields"]["goal_alignment"] = "altered"
    with pytest.raises(ValueError, match="altered Ranking"):
        ranking_output_spec(altered)
