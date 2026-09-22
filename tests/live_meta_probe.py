"""One independent Meta-review v2 call over a frozen export, never applied to a Run."""

import argparse
import asyncio
import copy
import json
import os
from pathlib import Path

import httpx

from co_scientist.adapters.artifacts.filesystem import FilesystemArtifactStore
from co_scientist.adapters.llm.multi_provider import ENDPOINTS, NativeJSONProvider, output_text
from co_scientist.agents.executor import _decode_payload, build_skill_request
from co_scientist.agents.payloads import MetaReviewResultV1
from co_scientist.domain.research_feedback import feedback_contract
from co_scientist.domain.research_protocol import protocol_hash
from co_scientist.events.models import NewEvent
from co_scientist.runtime.external_calls import request_fingerprint
from co_scientist.runtime.task_payload import validate_result_task_binding
from co_scientist.skills.loader import core_skill_directory
from co_scientist.supervisor.scientific_context import research_inputs
from tests.live_ranking_probe import write_new


def prepare(source: Path) -> tuple[dict, dict, dict]:
    manifest = json.loads((source / "manifest.json").read_text())
    tasks = json.loads((source / "tasks.json").read_text())
    metas = [t for t in tasks if t["intent_type"] == "run_meta_review"]
    if len(metas) != 1:
        raise ValueError("probe requires exactly one source scientific Meta-review")
    task = metas[0]
    original = task["payload"]["inputs"]
    events = []
    for line in (source / "events.jsonl").read_text().splitlines():
        event = json.loads(line)
        if event["event_type"] == "TaskEnqueued" and event["payload"]["task_id"] == task["task_id"]:
            break
        events.append(NewEvent(event_type=event["event_type"], schema_version=event["schema_version"],
                               payload=event["payload"]))
    else:
        raise ValueError("source task enqueue event not found")
    derived = copy.deepcopy(manifest)
    derived["feedback_contract"] = feedback_contract("meta-review-loop-v2")
    derived["feedback_contract_hash"] = protocol_hash(derived["feedback_contract"])
    rules = {"evaluation_rules_id": derived["profile"]["tournament"]["evaluation_rules_id"],
             "match_mode": derived["profile"]["tournament"]["match_mode"],
             "research_protocol_hash": derived["research_protocol_hash"],
             "feedback_contract_hash": derived["feedback_contract_hash"]}
    if derived.get("ranking_output_contract_hash"):
        rules["ranking_output_contract_hash"] = derived["ranking_output_contract_hash"]
    # Synthetic probe identity only: source comparisons remain historical evidence.
    derived["tournament_contract"]["evaluation_rules_hash"] = protocol_hash(rules)
    derived["profile"]["meta_review"]["contract_version"] = "meta-review-loop-v2"
    inputs = research_inputs(derived, events,
        {**original, "task_goal": derived["feedback_contract"]["meta_review_instruction"]},
        skill_id="meta_review")
    for key in original:
        if key != "task_goal" and inputs[key] != original[key]:
            raise ValueError(f"unexpected source input change: {key}")
    request = build_skill_request(skill_directory=core_skill_directory("meta_review"), inputs=inputs,
                                  model=manifest["provider_configuration"]["model"])
    provenance = {"kind": "counterfactual_meta_review_probe", "scientific_run": False,
        "source_run_id": manifest["run_id"], "source_task_id": task["task_id"],
        "source_manifest_hash": manifest["manifest_hash"],
        "source_input_hash": protocol_hash(original), "source_epoch": manifest["tournament_contract"],
        "feedback_contract": derived["feedback_contract"],
        "changed_input_fields": ["task_goal", "supervisor_review_context"],
        "max_http_requests": 1, "request_fingerprint": request_fingerprint(request)}
    return manifest, request, provenance


async def run_probe(source: Path, output: Path, *, confirmed: bool, transport=None) -> dict:
    if not confirmed:
        raise ValueError("requires explicit paid-call confirmation")
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise ValueError("DEEPSEEK_API_KEY is required")
    manifest, request, provenance = prepare(source)
    output.mkdir(parents=True, exist_ok=False)
    write_new(output / "provenance.json", provenance)
    write_new(output / "request.json", request)
    store = FilesystemArtifactStore(output / "artifacts")
    report = {"state": "planned", "http_requests": 0, "usage": None, "cost_usd": None,
              "pricing_status": "unpriced", "raw_artifact_ref": None}

    def journal(state, **fields):
        report.update(state=state, **fields)
        with (output / "events.jsonl").open("a") as stream:
            stream.write(json.dumps(report) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        print(state, flush=True)

    async def before(http_request):
        if report["http_requests"] or str(http_request.url) != ENDPOINTS["deepseek"]:
            raise ValueError("only one request to the DeepSeek endpoint is allowed")
        write_new(output / "wire-request.json", json.loads(http_request.content))
        journal("started", http_requests=1)

    async def persist(response):
        raw = await response.aread()
        ref = store.persist_raw("meta-probe-1", raw, "application/json",
            request_fingerprint=provenance["request_fingerprint"], run_id=output.name,
            task_id="compatibility-only", execution_context_fingerprint=provenance["request_fingerprint"])
        journal("raw_response_persisted", http_status=response.status_code,
                raw_artifact_ref=ref.model_dump(mode="json"))

    generation = manifest["provider_configuration"].get("generation", {})
    timeout = generation.get("timeout_seconds", 300)
    journal("planned")
    try:
        async with httpx.AsyncClient(transport=transport, timeout=timeout, follow_redirects=False,
                event_hooks={"request": [before], "response": [persist]}) as client:
            async with asyncio.timeout(timeout + 30):
                response = await NativeJSONProvider(client, provider="deepseek", api_key=key,
                                                     generation=generation).invoke(request)
        journal("usage_recorded", usage=dict(response.usage))
        result = MetaReviewResultV1.model_validate(
            _decode_payload(output_text("deepseek", dict(_decode_payload(response.body))).encode()))
        validate_result_task_binding(task_inputs=request["input"], task_research_plan_version=1,
                                     provider_id="deepseek", result=result)
        write_new(output / "result.json", result.model_dump(mode="json"))
        journal("validated", safety_direction_check=result.safety_direction_check)
    except (httpx.HTTPError, ValueError, TypeError, KeyError, TimeoutError) as error:
        journal("failed", error_type=type(error).__name__)
    write_new(output / "report.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--confirm-paid-call", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(run_probe(args.source, args.output, confirmed=args.confirm_paid_call))
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["state"] == "validated" else 1)
