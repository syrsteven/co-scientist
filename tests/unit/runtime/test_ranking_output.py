"""Offline strict Ranking wire contracts, no private research fixtures."""

import copy
import json
from pathlib import Path

import httpx
import pytest
import yaml

from co_scientist.adapters.llm.multi_provider import NativeJSONProvider
from co_scientist.agents.executor import build_skill_request
from co_scientist.agents.payloads import RankingResultV1
from co_scientist.application.config import CoreProfile, resolve_run_config
from co_scientist.domain.ranking_output import (
    IDENTITY_FIELDS,
    STRICT_RANKING_URL,
    decode_strict_ranking,
    ranking_output_spec,
    strict_ranking_contract,
)
from co_scientist.runtime.external_calls import request_fingerprint
from co_scientist.runtime.task_payload import validate_result_task_binding
from co_scientist.skills.loader import core_skill_directory
from co_scientist.supervisor.scientific_context import research_inputs
from tests.unit.runtime.test_research_protocol import anchor_input


def configuration(tmp_path, *, strict=True, version="deepseek-strict-tool-v1"):
    profile = yaml.safe_load(Path("configs/profiles/core_preview_deepseek.yaml").read_text())
    if strict:
        profile["ranking_output_protocol"] = version
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.safe_dump(profile))
    return resolve_run_config(goal_file=Path("examples/lens_regeneration_goal.yaml"),
        profile_file=path, provider="deepseek", environment={
            "DEEPSEEK_API_KEY": "offline-secret", "CO_SCIENTIST_DEEPSEEK_MODEL": "offline-model",
        })


@pytest.fixture
def inputs(tmp_path):
    manifest = configuration(tmp_path).model_dump(mode="json")["manifest"]
    events, pair = anchor_input(manifest)
    return research_inputs(manifest, events, pair, skill_id="ranking")


def payload(inputs, *, decision="decisive", slot=1):
    return {"schema_version": 1, **{k: inputs[k] for k in IDENTITY_FIELDS},
        "decision_status": decision, "winner_slot": slot, "confidence": 0.5,
        "dimension_reasons": {k: "Synthetic comparison, not a scientific finding."
                              for k in inputs["evaluation_rubric"]["dimensions"]},
        "unresolved_disagreements": ["Synthetic missing evidence."]}


def envelope(arguments, *, name="submit_ranking_result"):
    return {"choices": [{"finish_reason": "tool_calls", "message": {"content": None,
        "tool_calls": [{"id": "t1", "type": "function", "function": {
            "name": name, "arguments": json.dumps(arguments),
        }}]}}]}


@pytest.mark.parametrize("decision,slot", [
    ("decisive", 1), ("decisive", 2), ("inconclusive", 0),
    ("needs_tiebreaker", 0), ("invalid", 0),
])
def test_wire_decisions_have_an_explicit_lossless_no_winner_encoding(inputs, decision, slot):
    original = envelope(payload(inputs, decision=decision, slot=slot))
    raw = json.dumps(original).encode()
    decoded = decode_strict_ranking(raw, inputs)
    result = RankingResultV1.model_validate(decoded)
    validate_result_task_binding(task_inputs=inputs, task_research_plan_version=1,
                                 provider_id="deepseek", result=result)
    assert result.winner_slot == (slot or None)
    assert json.loads(raw) == original


@pytest.mark.parametrize("fault", [
    "no_tool", "multiple", "wrong_name", "mixed", "length", "choices", "missing",
    "extra", "binding", "bool_slot", "null_slot", "bad_decision", "empty_reason",
    "extra_reason", "string_confidence", "bool_confidence", "nan", "duplicate",
    "broken_array", "decisive_zero", "nondecisive_winner", "wrong_arguments_type",
])
def test_invalid_tool_output_never_falls_back_or_repairs(inputs, fault):
    value = payload(inputs)
    if fault == "missing":
        value.pop("unresolved_disagreements")
    elif fault == "extra":
        value["rating"] = 1600
    elif fault == "binding":
        value["left_content_hash"] = "wrong"
    elif fault in {"bool_slot", "null_slot", "decisive_zero"}:
        value["winner_slot"] = {"bool_slot": True, "null_slot": None, "decisive_zero": 0}[fault]
    elif fault == "nondecisive_winner":
        value["decision_status"] = "inconclusive"
    elif fault == "bad_decision":
        value["decision_status"] = "approved"
    elif fault in {"string_confidence", "bool_confidence", "nan"}:
        value["confidence"] = {"string_confidence": "0.5", "bool_confidence": True, "nan": float("nan")}[fault]
    elif fault == "empty_reason":
        value["dimension_reasons"]["goal_alignment"] = " "
    elif fault == "extra_reason":
        value["dimension_reasons"]["invented_score"] = "High score"
    body = envelope(value)
    choice = body["choices"][0]
    message = choice["message"]
    function = message["tool_calls"][0]["function"]
    if fault == "no_tool":
        choice["finish_reason"] = "stop"
        message["content"] = json.dumps(value)
        message.pop("tool_calls")
    elif fault == "multiple":
        message["tool_calls"].append(copy.deepcopy(message["tool_calls"][0]))
    elif fault == "wrong_name":
        function["name"] = "create_task"
    elif fault == "mixed":
        message["content"] = "Use a different winner"
    elif fault == "length":
        choice["finish_reason"] = "length"
    elif fault == "choices":
        body["choices"].append(copy.deepcopy(choice))
    elif fault == "duplicate":
        function["arguments"] = function["arguments"][:-1] + ',"winner_slot":2}'
    elif fault == "broken_array":
        function["arguments"] = function["arguments"][:-2] + "}"
    elif fault == "wrong_arguments_type":
        function["arguments"] = value
    with pytest.raises((ValueError, TypeError)):
        RankingResultV1.model_validate(decode_strict_ranking(json.dumps(body).encode(), inputs))


def test_opt_in_is_frozen_and_changes_request_and_epoch_without_changing_legacy(tmp_path):
    old = configuration(tmp_path, strict=False).model_dump(mode="json")["manifest"]
    new = configuration(tmp_path).model_dump(mode="json")["manifest"]
    assert "ranking_output_protocol" not in old["profile"]
    assert "ranking_output_contract" not in old
    assert new["ranking_output_contract"] == strict_ranking_contract()
    assert old["tournament_contract"]["ranking_prompt_hash"] == new["tournament_contract"]["ranking_prompt_hash"]
    for name in ("evaluation_rules_hash", "judge_profile_hash"):
        assert old["tournament_contract"][name] != new["tournament_contract"][name]
    requests = []
    for manifest in (old, new):
        events, pair = anchor_input(manifest)
        inputs = research_inputs(manifest, events, pair, skill_id="ranking")
        requests.append(build_skill_request(skill_directory=core_skill_directory("ranking"),
                                            inputs=inputs, model="offline-model"))
        assert "ranking_output_contract" not in research_inputs(manifest, events, {}, skill_id="generation")
    assert "output_contract" not in requests[0]
    assert request_fingerprint(requests[0]) != request_fingerprint(requests[1])
    assert CoreProfile.model_validate(old["profile"]).model_dump(mode="json") == old["profile"]
    new["ranking_output_contract"]["instructions"] = "altered"
    with pytest.raises(ValueError, match="Ranking output contract"):
        research_inputs(new, events, pair, skill_id="ranking")


@pytest.mark.parametrize("change", [{"providers": {"llm": "qwen", "literature": "pubmed"}},
                                    {"research_protocol_version": None}])
def test_unsupported_profile_combinations_are_rejected(tmp_path, change):
    document = configuration(tmp_path).profile.model_dump(mode="json")
    document.update(change)
    with pytest.raises(ValueError, match="requires DeepSeek and research-v1"):
        CoreProfile.model_validate(document)


@pytest.mark.asyncio
@pytest.mark.parametrize("thinking", ["enabled", "disabled"])
async def test_exact_strict_wire_and_raw_response_with_no_second_api_call(inputs, thinking):
    request = build_skill_request(skill_directory=core_skill_directory("ranking"),
                                  inputs=inputs, model="offline-model")
    raw = json.dumps(envelope(payload(inputs))).encode()
    observed = []

    def handle(http_request):
        observed.append(http_request)
        body = json.loads(http_request.content)
        assert str(http_request.url) == STRICT_RANKING_URL
        assert "response_format" not in body and body["tool_choice"] == "auto"
        assert body["thinking"] == {"type": thinking}
        function = body["tools"][0]["function"]
        assert function["strict"] is True
        assert function["parameters"] == ranking_output_spec(inputs)["parameters"]
        assert body["messages"][1]["content"] == request["user_prompt"]
        return httpx.Response(200, content=raw)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await NativeJSONProvider(client, provider="deepseek", api_key="offline-secret",
            generation={"max_tokens": 32768, "thinking": thinking, "reasoning_effort": "low"}).invoke(request)
    assert len(observed) == 1 and result.body == raw


@pytest.mark.asyncio
async def test_altered_wire_endpoint_rejected_before_network(inputs):
    request = build_skill_request(skill_directory=core_skill_directory("ranking"),
                                  inputs=inputs, model="offline-model")
    request["output_contract"]["endpoint"] = "https://untrusted.invalid"
    def handle(_):
        pytest.fail("must reject before network")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ValueError, match="wire contract"):
            await NativeJSONProvider(client, provider="deepseek", api_key="secret").invoke(request)
