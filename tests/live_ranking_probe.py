"""One paid strict-Ranking compatibility probe, not a scientific Run or benchmark."""

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml

from co_scientist.adapters.artifacts.filesystem import FilesystemArtifactStore
from co_scientist.adapters.llm.multi_provider import NativeJSONProvider
from co_scientist.agents.executor import build_skill_request
from co_scientist.agents.payloads import RankingResultV1
from co_scientist.application.config import resolve_run_config
from co_scientist.domain.ranking_output import (
    FLAT_RANKING_VERSION,
    STRICT_RANKING_URL,
    STRICT_RANKING_VERSION,
    decode_strict_ranking,
    strict_ranking_contract,
)
from co_scientist.events.models import NewEvent
from co_scientist.runtime.external_calls import request_fingerprint
from co_scientist.runtime.task_payload import validate_result_task_binding
from co_scientist.skills.loader import core_skill_directory
from co_scientist.supervisor.scientific_context import research_inputs

ROOT = Path(__file__).resolve().parents[1]


def write_new(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())


def prepare(
    output: Path, environment: dict[str, str], protocol: str = STRICT_RANKING_VERSION,
) -> tuple[dict, dict]:
    strict_ranking_contract(protocol)  # Reject unknown versions before writing or calling a provider.
    if not environment.get("DEEPSEEK_API_KEY") or not environment.get("CO_SCIENTIST_DEEPSEEK_MODEL"):
        raise ValueError("requires DEEPSEEK_API_KEY and CO_SCIENTIST_DEEPSEEK_MODEL")
    # Exclusive creation prevents replaying an uncertain request or overwriting evidence.
    output.mkdir(parents=True, exist_ok=False)
    profile = yaml.safe_load((ROOT / "configs/profiles/core_preview_deepseek.yaml").read_text())
    profile["ranking_output_protocol"] = protocol
    # JSON is also valid YAML; this freezes the exact profile without editing a template.
    write_new(output / "profile.yaml", profile)
    config = resolve_run_config(
        goal_file=ROOT / "examples/lens_regeneration_goal.yaml",
        profile_file=output / "profile.yaml", provider="deepseek", environment=environment,
    )
    manifest = config.model_dump(mode="json")["manifest"]
    members = manifest["anchor_sets"][0]["members"]
    events = []
    for member in members:
        events.append(NewEvent(event_type="HypothesisContentCreated", payload={
            **member["content"], "hypothesis_id": member["anchor_id"], "research_plan_version": 1,
        }))
        events.extend(NewEvent(event_type="ReviewCompleted", payload=review)
                      for review in member["evidence"]["reviews"])
        events.append(NewEvent(event_type="NoveltyAssessmentRecorded",
                               payload=member["evidence"]["novelty_assessment"]))
    pair = {**manifest["tournament_contract"], "match_id": output.name,
            "left_id": members[0]["anchor_id"], "left_content_hash": members[0]["content_hash"],
            "right_id": members[1]["anchor_id"], "right_content_hash": members[1]["content_hash"]}
    inputs = research_inputs(manifest, events, pair, skill_id="ranking")
    request = build_skill_request(skill_directory=core_skill_directory("ranking"), inputs=inputs,
                                  model=manifest["provider_configuration"]["model"])
    write_new(output / "manifest.json", {"kind": "compatibility_probe", "max_http_requests": 1,
        "scientific_run": False, "source": "repository fixed lens anchors",
        "resolved_configuration": manifest, "request_fingerprint": request_fingerprint(request)})
    write_new(output / "request.json", request)
    return manifest, request


async def run_probe(
    output: Path, environment: dict[str, str], *, confirmed: bool,
    transport: httpx.AsyncBaseTransport | None = None,
    protocol: str = STRICT_RANKING_VERSION,
) -> dict[str, Any]:
    if not confirmed:
        raise ValueError("one potentially paid call requires explicit confirmation")
    manifest, request = prepare(output, environment, protocol)
    fingerprint = request_fingerprint(request)
    store = FilesystemArtifactStore(output / "artifacts")
    report: dict[str, Any] = {"probe_id": output.name, "model": request["model"], "protocol": protocol,
        "scientific_run": False, "request_fingerprint": fingerprint,
        "http_requests": 0, "state": "planned", "usage": None, "cost_usd": None,
        "pricing_status": "unpriced", "raw_artifact_ref": None}

    def journal(state: str, **fields: Any) -> None:
        report.update(state=state, **fields)
        with (output / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"at": datetime.now(UTC).isoformat(), "state": state,
                                     **fields}, ensure_ascii=False, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        print(json.dumps({"probe_id": output.name, "state": state}, ensure_ascii=False), flush=True)

    async def before_request(http_request: httpx.Request) -> None:
        if report["http_requests"] or str(http_request.url) != STRICT_RANKING_URL:
            raise ValueError("probe allows exactly one request to the frozen strict endpoint")
        write_new(output / "wire-request.json", json.loads(http_request.content))
        journal("started", http_requests=1)

    async def persist_response(response: httpx.Response) -> None:
        body = await response.aread()
        ref = store.persist_raw("probe-1", body, "application/json",
            request_fingerprint=fingerprint, run_id=output.name, task_id="compatibility-only",
            execution_context_fingerprint=fingerprint)
        journal("raw_response_persisted", http_status=response.status_code,
                raw_artifact_ref=ref.model_dump(mode="json"))

    journal("planned")
    generation = manifest["provider_configuration"].get("generation", {})
    timeout = generation.get("timeout_seconds", 300)
    try:
        async with httpx.AsyncClient(transport=transport, timeout=timeout, follow_redirects=False,
            event_hooks={"request": [before_request], "response": [persist_response]}) as client:
            async with asyncio.timeout(timeout + 30):
                response = await NativeJSONProvider(client, provider="deepseek",
                    api_key=environment["DEEPSEEK_API_KEY"], generation=generation).invoke(request)
        journal("usage_recorded", usage=dict(response.usage))
        result = RankingResultV1.model_validate(decode_strict_ranking(response.body, request["input"]))
        validate_result_task_binding(task_inputs=request["input"], task_research_plan_version=1,
                                     provider_id="deepseek", result=result)
        write_new(output / "result.json", result.model_dump(mode="json"))
        journal("validated", decision_status=result.decision_status, winner_slot=result.winner_slot)
    except (httpx.HTTPError, ValueError, TypeError, KeyError, TimeoutError) as error:
        # No automatic retry and no exception/request headers that could disclose credentials.
        journal("failed", error_type=type(error).__name__)
    write_new(output / "report.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="new evidence directory; cannot exist")
    parser.add_argument("--confirm-paid-call", action="store_true")
    parser.add_argument("--protocol", choices=[STRICT_RANKING_VERSION, FLAT_RANKING_VERSION],
                        default=STRICT_RANKING_VERSION, help="explicit wire version; default stays v1")
    args = parser.parse_args()
    if not args.confirm_paid_call:
        parser.error("pass --confirm-paid-call to authorize exactly one potentially paid request")
    result = asyncio.run(run_probe(args.output, dict(os.environ), confirmed=True, protocol=args.protocol))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["state"] != "validated":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
