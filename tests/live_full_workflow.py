"""Explicit six-agent integration exercise; not the default research scheduler.

Run from the repository with ``python -m tests.live_full_workflow --help``.
Evolution and Meta-review are injected through Supervisor as labelled test tasks.
Scientific results, review gates, budgets and lifecycle handling stay unchanged.
"""

import argparse
import asyncio
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

from co_scientist.application.config import resolve_run_config
from co_scientist.export.run_export import (
    SqliteRunReadModel,
    export_run,
    verify_core_release_invariants,
)
from co_scientist.ports.external_provider import thaw_json
from co_scientist.runtime.core_runner import CoreRunner


def emit(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False), flush=True)


def schedule_exercise(runner: CoreRunner, run_id: str, kind: str) -> None:
    supervisor = runner.supervisor
    events = runner.uow.load(run_id)
    manifest = runner.uow.run_manifest(run_id)
    anchors = {member["anchor_id"] for group in manifest["anchor_sets"] for member in group["members"]}
    contents = {e.payload["hypothesis_id"]: e.payload for e in events
                if e.event_type == "HypothesisContentCreated"}
    unsafe = {e.payload["hypothesis_id"] for e in events
              if e.event_type == "ReviewCompleted" and e.payload.get("safety_status") == "blocked"}
    candidates = {key: value for key, value in contents.items() if key not in anchors | unsafe}
    feedback = [{"event_type": e.event_type, "sequence": e.sequence,
                 "assessment": thaw_json(e.payload)} for e in events
                if e.event_type in {"ReviewCompleted", "NoveltyAssessmentRecorded"}
                and e.payload.get("hypothesis_id") in candidates]
    inputs = {
        "research_plan_version": supervisor._active_epoch(run_id).research_plan_version,
        "test_intervention": "Explicit six-agent coverage exercise; do not infer prior approval or change scientific gates.",
        "review_feedback": feedback,
        "literature_evidence": supervisor._persisted_review_evidence(run_id),
    }
    children = 0
    if kind == "evolution":
        if not candidates:
            raise ValueError("no safety-eligible parents for Evolution exercise")
        children = min(2, manifest["budget"]["max_hypotheses"] - len(candidates) - 1)
        if children < 1:
            raise ValueError("no remaining child budget")
        inputs.update({
            "task_goal": "Generate up to two substantively revised, mechanistically distinct children using the feedback. New children still require full independent review.",
            "evolution_round": 1,
            "max_children": children,
            "source_content_ids": [value["content_id"] for value in candidates.values()],
            "existing_hypothesis_ids": sorted(contents),
            "existing_content_ids": sorted(value["content_id"] for value in contents.values()),
        })
    else:
        inputs.update({
            "source_content_hashes": {key: value["content_hash"] for key, value in candidates.items()},
            "matches": [thaw_json(e.payload) for e in events if e.event_type == "MatchEvaluated"],
            "task_goal": "Summarize cross-review patterns, competing causal explanations, distinguishing experiments and remaining evidence gaps. Copy source_content_hashes and research_plan_version exactly. Do not invent validation or alter ratings.",
        })
    provider, model = supervisor._manifest_provider(manifest)
    task = supervisor._worker_task(
        run_id=run_id, task_id=f"{run_id}:full-test:{kind}",
        intent_type=f"run_{kind}", skill_id=kind, inputs=inputs,
        provider_id=provider, model_or_tool=model, hypotheses=children,
    )
    supervisor.enqueue_task(task=task, expected_sequence=events[-1].sequence)
    emit({"test_scheduled": kind, "run_id": run_id})


def summarize(runner: CoreRunner, run_id: str) -> dict[str, Any]:
    model = SqliteRunReadModel(runner.uow)
    events = runner.uow.load(run_id)
    calls = model.external_calls(run_id)
    children = {e.payload["hypothesis_id"] for e in events
                if e.event_type == "HypothesisContentCreated" and e.payload.get("parent_content_ids")}
    admitted = {e.payload["hypothesis_id"] for e in events if e.event_type == "TournamentEntryCreated"}
    stages = {(e.payload["hypothesis_id"], e.payload["stage"]) for e in events
              if e.event_type == "ReviewCompleted"}
    skills = Counter(call["execution_context"]["skill_id"] for call in calls
                     if call["state"] == "domain_result_applied" and call["provider"] == "deepseek")
    report = verify_core_release_invariants(run_id, model)
    return {
        **runner._result(run_id).model_dump(mode="json"),
        "test_protocol": "Supervisor-injected Evolution before admission and Meta-review after the initial tournament batch",
        "applied_llm_roles": dict(skills),
        "children": sorted(children), "admitted_children": sorted(children & admitted),
        "all_children_re_reviewed": bool(children) and all(
            (key, stage) in stages for key in children for stage in ("initial_review", "full_review")),
        "all_calls_applied": all(call["state"] == "domain_result_applied" for call in calls),
        "input_tokens": sum(int(call.get("usage", {}).get("input_tokens", 0)) for call in calls),
        "output_tokens": sum(int(call.get("usage", {}).get("output_tokens", 0)) for call in calls),
        "invariants": report.model_dump(mode="json"),
    }


async def run(args: argparse.Namespace) -> None:
    runner = CoreRunner(data_dir=args.data_dir, environment=os.environ)
    try:
        if args.resume:
            manifest = runner.uow.run_manifest(args.run_id)
            runner._compose(manifest)
        else:
            config = resolve_run_config(goal_file=args.goal, profile_file=args.profile,
                                        provider="deepseek", environment=os.environ)
            manifest = config.model_dump(mode="json")["manifest"]
            manifest["manifest_hash"] = config.manifest_hash
            runner._compose(manifest)
            runner.supervisor.bootstrap_run(run_id=args.run_id, manifest=manifest)
        for _ in range(1000):
            if runner.supervisor.pause_on_invalid_output(run_id=args.run_id) is not None:
                break
            if runner.uow.run_state(args.run_id) not in {"running", "stopping"}:
                break
            assert runner.worker is not None
            try:
                step = await runner.worker.run_once(args.run_id)
            except Exception:
                if runner.supervisor.pause_on_invalid_output(run_id=args.run_id) is not None:
                    break
                raise
            if step.status in {"completed", "requeued"}:
                emit({"task": step.task_id, "status": step.status})
                continue
            if step.status != "idle":
                break
            events = runner.uow.load(args.run_id)
            task_ids = {e.payload["task_id"] for e in events if e.event_type == "TaskEnqueued"}
            if f"{args.run_id}:full-test:evolution" not in task_ids:
                schedule_exercise(runner, args.run_id, "evolution")
                continue
            match_count = sum(e.event_type == "MatchEvaluated" for e in events)
            if match_count >= manifest["profile"]["stop"]["minimum_matches"] and (
                f"{args.run_id}:full-test:meta_review" not in task_ids
            ):
                schedule_exercise(runner, args.run_id, "meta_review")
                continue
            outcome = runner.supervisor.advance(run_id=args.run_id, expected_sequence=events[-1].sequence)
            if outcome.action not in {"scheduled", "admitted", "checkpointed"}:
                break
        else:
            raise RuntimeError("test driver safety bound exceeded")
        report = summarize(runner, args.run_id)
        if not args.output.exists():
            export_run(args.run_id, args.output, SqliteRunReadModel(runner.uow), runner.artifacts)
        # Runtime test artifacts, not edits to source or previous exports.
        report_path = args.output / "full_workflow_check.json"
        if report_path.exists():
            raise FileExistsError(report_path)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        emit(report)
    finally:
        await runner.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--data-dir", type=Path, default=Path(".co-scientist-deepseek"))
    parser.add_argument("--goal", type=Path, default=Path("examples/lens_regeneration_goal.yaml"))
    parser.add_argument("--profile", type=Path, default=Path("configs/profiles/core_preview_deepseek_full_test.yaml"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    asyncio.run(run(parser.parse_args()))
