"""Read-only Ideation views over existing durable events, calls and artifacts.

No scientific decisions, inferred parentage, new events or database writes.
"""

import hashlib
import json
from collections import Counter
from pathlib import Path

from sqlalchemy import select

from co_scientist.adapters.persistence.sqlite import (
    CostEntryRow,
    ExternalCallFailureDiagnosticRow,
    ExternalCallMilestoneRow,
    ExternalCallRow,
)
from co_scientist.domain.bayesian_ranking import TrueSkillConfig, replay_bayesian_rating
from co_scientist.ports.artifact_store import RawArtifactManifest
from co_scientist.ports.external_provider import thaw_json


def trace_documents(uow, artifacts, run_id, *, transport_artifacts=None):
    from co_scientist.runtime.trace_snapshot import trace_snapshot

    with trace_snapshot(uow, artifacts, transport_artifacts) as (view, ledger):
        documents = _trace_documents(view, artifacts, run_id,
                                     transport_artifacts=transport_artifacts, ledger=ledger)
    return documents


def _trace_documents(uow, artifacts, run_id, *, transport_artifacts=None, ledger=None):
    events = uow.load(run_id)
    manifest = uow.run_manifest(run_id)
    epoch = manifest["tournament_contract"]["epoch_id"]
    rows = [e.model_dump(mode="json") for e in events]
    tasks = {e.payload["task_id"]: uow.task_definition(e.payload["task_id"]).model_dump(mode="json")
             for e in events if e.event_type == "TaskEnqueued"}
    with uow.session_factory() as session:
        call_ids = session.scalars(select(ExternalCallRow.external_call_id).where(
            ExternalCallRow.run_id == run_id).order_by(ExternalCallRow.external_call_id)).all()
        costs = [{c.name: getattr(row, c.name) for c in CostEntryRow.__table__.columns}
                 for row in session.scalars(select(CostEntryRow).where(CostEntryRow.run_id == run_id))]
        milestones = [{c.name: getattr(row, c.name) for c in ExternalCallMilestoneRow.__table__.columns}
            for row in session.scalars(select(ExternalCallMilestoneRow).where(
                ExternalCallMilestoneRow.run_id == run_id).order_by(ExternalCallMilestoneRow.observation_id))]
        diagnostics = [{c.name: getattr(row, c.name) for c in ExternalCallFailureDiagnosticRow.__table__.columns}
            for row in session.scalars(select(ExternalCallFailureDiagnosticRow).where(
                ExternalCallFailureDiagnosticRow.run_id == run_id).order_by(ExternalCallFailureDiagnosticRow.diagnostic_id))]
    calls = [uow.get_external_call(key).model_dump(mode="json") for key in call_ids]
    if any(c["external_call_id"] not in call_ids for c in costs):
        raise ValueError("trace cost entry references an unknown call")
    for call in calls:
        call["actual_model_observed"] = None
        call["response_terminal_observed"] = None
        capture = artifacts.discover_raw(call["external_call_id"] + ":http-v2")
        recorded = call["usage"].get("http_capture_v2")
        if recorded is not None and (capture is None or
                recorded["artifact_ref"] != capture.artifact_ref.model_dump(mode="json")):
            raise ValueError("trace durable HTTP capture/reference mismatch")
        if call["raw_artifact_ref"] is not None:
            from co_scientist.ports.artifact_store import ArtifactRef

            artifacts.read(ArtifactRef.model_validate(call["raw_artifact_ref"]))
        call["http_status_observed"] = capture.usage.get("status") if capture else None
        call["http_capture_ref"] = capture.artifact_ref.model_dump(mode="json") if capture else None
        if capture and (capture.run_id != run_id or capture.task_id != call["task_id"]
                        or capture.request_fingerprint != call["request_fingerprint"]):
            raise ValueError("trace HTTP capture/call identity mismatch")
        observations = [m for m in milestones if m["external_call_id"] == call["external_call_id"]]
        starts = [m["recorded_at"] for m in observations if m["milestone"] == "inner_transport_entered"]
        ends = [m["recorded_at"] for m in observations if m["milestone"] == "response_body_complete"]
        call["response_transport_seconds_observed"] = (
            (min(ends) - min(starts)).total_seconds()
            if starts and ends and call["provider"] in {"openai", "deepseek"} else None)
        if (capture or call["raw_artifact_ref"] is not None) and call["provider"] in {"openai", "deepseek"}:
            from co_scientist.ports.artifact_store import ArtifactRef

            body = artifacts.read(capture.artifact_ref if capture else ArtifactRef.model_validate(call["raw_artifact_ref"]))
            try:
                envelope = json.loads(body)
            except (ValueError, UnicodeDecodeError):
                envelope = None
            if isinstance(envelope, dict):
                call["actual_model_observed"] = envelope.get("model")
                choices = envelope.get("choices")
                call["response_terminal_observed"] = (choices[0].get("finish_reason")
                    if isinstance(choices, list) and choices and isinstance(choices[0], dict)
                    else envelope.get("status"))
    inventory, requests = [], []
    for store in [artifacts, *([transport_artifacts] if transport_artifacts is not None else [])]:
        for path in sorted(store.root.glob("raw/**/*.manifest.json")):
            metadata = RawArtifactManifest.model_validate_json(path.read_bytes())
            if store is artifacts and metadata.run_id != run_id:
                continue
            body = store.read(metadata.artifact_ref)  # hash/size-verified by the existing store
            inventory.append({"artifact_root": str(store.root), **metadata.model_dump(mode="json")})
            if store is artifacts and metadata.call_id.startswith("single-root-permit:") and not metadata.call_id.endswith(":wire"):
                permit = json.loads(body)
                wire = store.discover_raw(metadata.call_id + ":wire")
                if wire is None:
                    raise ValueError("durable permit has no frozen wire artifact")
                data = store.read(wire.artifact_ref)
                if hashlib.sha256(data).hexdigest() != permit["wire_hash"]:
                    raise ValueError("export request/wire identity mismatch")
                requests.append({"permit": permit, "wire_ref": wire.artifact_ref.model_dump(mode="json"),
                    "actual_wire": json.loads(data) if data else None})
    focal, participations = Counter(), Counter()
    for e in events:
        if e.event_type == "MatchPairReserved":
            focal[e.payload["focal_id"]] += 1
            participations.update([e.payload["left_id"], e.payload["right_id"]])
    ratings = replay_bayesian_rating(events, epoch_id=epoch, policy=TrueSkillConfig())
    # Root content events omit generation_index. Resolve from the authoritative
    # Generation fact that produced this exact content, not an ID/text guess.
    root_results = {e.payload["source_result_id"]: e.sequence for e in events
                    if e.event_type == "GroundedGenerationRecordedV1"
                    and e.payload["binding"].get("root_slot_id") is not None}
    candidates = []
    for e in events:
        if e.event_type != "HypothesisContentCreated":
            continue
        key = e.payload["hypothesis_id"]
        generation = e.payload.get("generation_index")
        root_fact = root_results.get(e.payload.get("source_result_id"))
        if generation is None and root_fact is not None:
            generation = 0
        candidates.append({**thaw_json(e.payload), "generation_index": generation,
            "generation_source_sequence": root_fact if root_fact is not None else e.sequence,
            "created_sequence": e.sequence,
            "created_at": e.occurred_at.isoformat(),
            "ethics": [r for r in rows if r["event_type"] == "CandidateEthicsRecordedV1"
                       and r["payload"]["binding"]["hypothesis_id"] == key],
            "reflection": [r for r in rows if r["event_type"] == "BaselineReflectionRecordedV1"
                           and r["payload"]["binding"]["hypothesis_id"] == key],
            "rating": ratings[key].model_dump(mode="json") if key in ratings else None,
            "focal_logical_attempts": focal[key], "comparison_participations": participations[key]})
    state, before, after = {}, {}, {}
    outcomes = {}
    for e in events:
        p = thaw_json(e.payload)
        if e.event_type == "InitialRatingAssigned":
            state[p["hypothesis_id"]] = {k: p[k] for k in ("mu", "sigma")}
        elif e.event_type == "MatchEvaluated":
            outcomes[p["match_id"]] = p
            before[p["match_id"]] = {k: dict(state[k]) for k in (p["left_id"], p["right_id"])}
        elif e.event_type == "BayesianRatingProjected":
            state[p["hypothesis_id"]] = {k: p[k] for k in ("mu", "sigma")}
            after.setdefault(p["match_id"], {})[p["hypothesis_id"]] = dict(state[p["hypothesis_id"]])
    ranking = []
    for e in events:
        if e.event_type != "MatchPairReserved":
            continue
        p = thaw_json(e.payload)
        result = outcomes.get(p["match_id"])
        facts = [r for r in rows if r["event_type"] == "BaselineRankingRecordedV1"
                 and r["payload"]["binding"]["task_id"] == p["task_id"]]
        associated = [c for c in calls if c["task_id"] == p["task_id"]]
        verdict = facts[0]["payload"]["result"]["decision"] if facts else None
        status = ("VALID_DECISIVE" if verdict == "decisive" else verdict.upper() if verdict else
                  "INVALID_RESULT" if any(c["state"] == "validation_failed" for c in associated)
                  else "TECHNICAL_OR_PENDING_NO_SCIENTIFIC_VERDICT")
        ranking.append({**p, "reserved_sequence": e.sequence, "reserved_at": e.occurred_at.isoformat(),
            "task": tasks[p["task_id"]], "task_state": uow.task_state(p["task_id"]),
            "result": result, "original_validated_decision": verdict, "status": status,
            "before": before.get(p["match_id"]),
            "after": after.get(p["match_id"], before.get(p["match_id"]) if result else None),
            "calls": associated})
    evolution = []
    for e in events:
        if e.event_type != "BaselineReproductionPlannedV1":
            continue
        p = thaw_json(e.payload)
        prior = replay_bayesian_rating([r for r in events if r.sequence <= p["comparison_boundary"]],
            epoch_id=epoch, policy=TrueSkillConfig())
        pool = {k: {**v.model_dump(mode="json"), "ucb": v.mu + v.sigma}
                for k, v in prior.items() if v.decisive_matches >= 2}
        if sorted(pool) != sorted(p["decision"]["eligible_parent_ids"]):
            raise ValueError("export parent pool differs from durable comparison boundary")
        evolution.append({**p, "sequence": e.sequence, "occurred_at": e.occurred_at.isoformat(),
            "eligible_pool_at_selection": pool,
            "result_events": [r for r in rows if r["event_type"] == "BaselineEvolutionRecordedV1"
                              and r["payload"]["binding"]["task_id"] == p.get("task_id")],
            "children": [c["hypothesis_id"] for c in candidates if c["slot_id"] == p["slot_id"]]})
    finals = [r for r in rows if r["event_type"] == "IdeationFinalSelectionV1"]
    final = finals[-1]["payload"] if finals else None
    from co_scientist.domain.population_evolution import baseline_final_choice

    interim = baseline_final_choice(ratings, epoch_id=epoch, complete=False)[2] if final is None else None
    selected_id = (final["winner_id"] or final["best_so_far_id"]) if final else interim
    selected = next((c for c in candidates if c["hypothesis_id"] == selected_id), None)
    generations = [r for r in rows if r["event_type"] == "BaselineGenerationCompletedV1"]
    kinds = {r["permit"]["mode"] for r in requests}
    evidence_kind = "MOCK_ONLY" if kinds == {"MOCK_ONLY"} else "LIVE_SINGLE_DISPATCH" if kinds == {"LIVE_SINGLE_DISPATCH"} else "UNKNOWN_OR_NO_DISPATCH"
    timeline = {"version": "ideation-readonly-trace-v1", "run_id": run_id,
        "evidence_kind": evidence_kind,
        "event_span_seconds": (events[-1].occurred_at - events[0].occurred_at).total_seconds() if events else None,
        "execution_state": uow.run_state(run_id), "manifest": thaw_json(manifest), "events": rows,
        "tasks": tasks, "calls": calls, "cost_entries": costs,
        "transport_milestones": milestones, "failure_diagnostics": diagnostics, "dispatch_ledger": ledger,
        "budget": uow.load_budget_snapshot(run_id).model_dump(mode="json"),
        "requests": requests, "raw_artifacts": inventory, "final_selection": final,
        "unfinalized_best_so_far_analysis_id": interim}
    tree = {"run_id": run_id, "generations": generations, "reproduction": evolution,
        "edges": [{"parent_id": parent, "child_id": c["hypothesis_id"]}
                  for c in candidates for parent in c.get("scientific_parent_ids", [])],
        "final_selection": final}
    table = ["| Candidate | G | Scientific parents | mu | sigma | Valid decisive | Focal attempts |",
             "|---|---:|---|---:|---:|---:|---:|"]
    for c in candidates:
        r = c["rating"] or {}
        table.append(f"| {c['hypothesis_id']} | {c.get('generation_index')} | {', '.join(c.get('scientific_parent_ids', [])) or 'root'} | "
                     f"{r.get('mu', 'not admitted')} | {r.get('sigma', 'not admitted')} | {r.get('decisive_matches', 0)} | {c['focal_logical_attempts']} |")
    operator_lines = [f"- {p['slot_id']}: {p['decision']['operator']}; parents {p['decision']['parent_ids']}; "
                      f"state {p['decision']['state']}." for p in evolution]
    content = {k: selected[k] for k in ("hypothesis_id", "title", "claim", "mechanism_chain", "assumptions",
               "predictions", "falsifiers", "scientific_parent_ids", "content_hash") if k in selected} if selected else None
    report = (f"# Ideation Run {run_id}\n\nEvidence: {evidence_kind}. Execution: {uow.run_state(run_id)}\n\n"
              f"Created content records: {len(candidates)}; rating-ready candidates: {len(ratings)}.\n"
              f"Evaluated generations: {[r['payload']['generation'] for r in generations]}.\n"
              f"Ordinary reproduction slots: {sum(not p.get('redesign_of') for p in evolution)}; "
              f"all reproduction/redesign plans: {len(evolution)}; pair opportunities: {len(ranking)}.\n\n"
              "No forced operator coverage. Missing/nondecisive outcomes are not fabricated wins or losses.\n\n"
              "## Candidates and committed ratings\n\n" + "\n".join(table) + "\n\n"
              "## Reproduction\n\n" + "\n".join(operator_lines) + "\n\n"
              "Full P, contestant draws, UCB scores and exact ordered parent critiques are in evolution-tree.json. "
              "Ranking changes both mu and sigma; parent tournaments use mu+sigma, final selection uses mu only.\n\n"
              "## Final selection / explicitly interim best-so-far\n\n```json\n"
              + json.dumps({"native_final_selection": final, "unfinalized_analysis_id": interim}, ensure_ascii=False, indent=2) + "\n```\n\n"
              "## Selected scientific content\n\n```json\n"
              + json.dumps(content, ensure_ascii=False, indent=2) + "\n```\n\n"
              "Final winner exists only when the native result is COMPLETE/FINAL_WINNER. "
              "Raw/usage/cost/reservation and actual prompts are trace references, not scientific validation.\n")
    return {"run-timeline.json": timeline, "candidates.json": candidates,
            "ranking-history.json": ranking, "evolution-tree.json": tree, "ideation-report.md": report}


def export_trace(uow, artifacts, run_id, destination: Path, *, transport_artifacts=None):
    """Write derived views only; never touch the source DB, ledger or raw."""
    from co_scientist.adapters.artifacts.filesystem import FilesystemArtifactStore

    documents = trace_documents(uow, artifacts, run_id, transport_artifacts=transport_artifacts)
    destination.mkdir(parents=True, exist_ok=True)
    for name, value in documents.items():
        data = (value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2, default=str)) + "\n"
        path = destination / name
        if path.exists() and path.read_bytes() != data.encode():
            raise ValueError("refuse to overwrite a different frozen trace export")
        if not path.exists():
            FilesystemArtifactStore._atomic_write(path, data.encode())
    return documents
