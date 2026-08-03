"""Deterministic export of one durable Core Preview run."""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from co_scientist.adapters.persistence.sqlite import (
    CostEntryRow,
    ExternalCallRow,
    RunRow,
    SqliteUnitOfWork,
    TaskRow,
)
from co_scientist.domain.hypothesis import HypothesisContent
from co_scientist.domain.proximity import ProximityEdge
from co_scientist.domain.review import NoveltyAssessment, Review
from co_scientist.domain.tournament import (
    MatchResult,
    TournamentEpoch,
    apply_match,
    validate_match_contract,
)
from co_scientist.events.models import DomainEvent
from co_scientist.events.reducers import replay_hypothesis
from co_scientist.ports.artifact_store import ArtifactRef, ArtifactStore


class RunReadModel(Protocol):
    """Read-only durable data needed by export and release verification."""

    def run_manifest(self, run_id: str) -> dict[str, Any]: ...

    def events(self, run_id: str) -> list[dict[str, Any]]: ...

    def hypotheses(self, run_id: str) -> list[dict[str, Any]]: ...

    def reviews(self, run_id: str) -> list[dict[str, Any]]: ...

    def novelty_assessments(self, run_id: str) -> list[dict[str, Any]]: ...

    def proximity(self, run_id: str) -> list[dict[str, Any]]: ...

    def epochs(self, run_id: str) -> list[dict[str, Any]]: ...

    def matches(self, run_id: str) -> list[dict[str, Any]]: ...

    def ratings(self, run_id: str) -> dict[str, dict[str, float]]: ...

    def tasks(self, run_id: str) -> list[dict[str, Any]]: ...

    def external_calls(self, run_id: str) -> list[dict[str, Any]]: ...

    def costs(self, run_id: str) -> list[dict[str, Any]]: ...

    def literature(self, run_id: str) -> dict[str, Any]: ...


_RUN_EVENT_STATES = {
    "RunStarted": "running",
    "RunPausing": "pausing",
    "RunPaused": "paused",
    "RunResumed": "running",
    "RunStopping": "stopping",
    "RunCompleted": "completed",
    "RunCompletedPartial": "completed_partial",
    "RunCancelled": "cancelled",
}


def _loads(value: str | None) -> Any:
    return json.loads(value) if value is not None else None


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _deduplicate(items: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for item in items:
        identifier = item.get(key)
        if not isinstance(identifier, str) or not identifier:
            raise ValueError(f"exported {key} must be a non-empty string")
        previous = unique.get(identifier)
        if previous is not None and previous != item:
            raise ValueError(f"conflicting durable values for {key}={identifier}")
        unique[identifier] = item
    return [unique[identifier] for identifier in sorted(unique)]


class SqliteRunReadModel:
    """Build deterministic projections from one SQLite unit of work."""

    def __init__(self, uow: SqliteUnitOfWork) -> None:
        self.uow = uow

    def _run_row(self, run_id: str) -> RunRow:
        with self.uow.session_factory() as session:
            row = session.get(RunRow, run_id)
            if row is None:
                raise KeyError(f"unknown run: {run_id}")
            session.expunge(row)
            return row

    def _domain_events(self, run_id: str) -> list[DomainEvent]:
        self._run_row(run_id)
        return self.uow.load(run_id)

    def _source_manifest(self, run_id: str) -> dict[str, Any]:
        value = _loads(self._run_row(run_id).manifest_json)
        if not isinstance(value, dict):
            raise TypeError("run manifest must be a JSON object")
        return value

    def events(self, run_id: str) -> list[dict[str, Any]]:
        return [event.model_dump(mode="json") for event in self._domain_events(run_id)]

    def hypotheses(self, run_id: str) -> list[dict[str, Any]]:
        events = self._domain_events(run_id)
        exported: list[dict[str, Any]] = []
        for event in events:
            if event.event_type != "HypothesisContentCreated":
                continue
            hypothesis_id = event.payload.get("hypothesis_id")
            if not isinstance(hypothesis_id, str) or not hypothesis_id:
                raise ValueError("HypothesisContentCreated is missing hypothesis_id")
            content = HypothesisContent.model_validate(event.payload)
            projection = replay_hypothesis(hypothesis_id, events)
            item = content.model_dump(mode="json")
            item.update(
                {
                    "hypothesis_id": hypothesis_id,
                    "content_hash": event.payload.get("content_hash", content.content_hash),
                    "created_sequence": event.sequence,
                    "projection": projection.model_dump(mode="json"),
                }
            )
            exported.append(item)
        return exported

    def reviews(self, run_id: str) -> list[dict[str, Any]]:
        exported: list[dict[str, Any]] = []
        for event in self._domain_events(run_id):
            if event.event_type != "ReviewCompleted":
                continue
            review = Review.model_validate(event.payload).model_dump(mode="json")
            if "safety_passed" in event.payload:
                review["safety_passed"] = event.payload["safety_passed"]
            review["completed_sequence"] = event.sequence
            exported.append(review)
        return sorted(exported, key=lambda item: (item["hypothesis_id"], item["stage"]))

    def novelty_assessments(self, run_id: str) -> list[dict[str, Any]]:
        exported: list[dict[str, Any]] = []
        for event in self._domain_events(run_id):
            candidates: list[Any] = []
            if event.event_type in {"NoveltyAssessmentCreated", "NoveltyAssessmentRecorded"}:
                candidates.append(event.payload)
            singular = event.payload.get("novelty_assessment")
            if singular is not None:
                candidates.append(singular)
            plural = event.payload.get("novelty_assessments", ())
            if isinstance(plural, list | tuple):
                candidates.extend(plural)
            for candidate in candidates:
                assessment = NoveltyAssessment.model_validate(candidate)
                exported.append(assessment.model_dump(mode="json"))
        return _deduplicate(exported, "assessment_id")

    def proximity(self, run_id: str) -> list[dict[str, Any]]:
        exported = [
            ProximityEdge.model_validate(event.payload).model_dump(mode="json")
            for event in self._domain_events(run_id)
            if event.event_type == "ProximityAssessed"
        ]
        return sorted(exported, key=lambda item: (item["left_id"], item["right_id"]))

    def epochs(self, run_id: str) -> list[dict[str, Any]]:
        return [
            TournamentEpoch.model_validate(event.payload).model_dump(mode="json")
            for event in self._domain_events(run_id)
            if event.event_type == "TournamentEpochOpened"
        ]

    def _ratings_and_matches(
        self, run_id: str
    ) -> tuple[dict[str, dict[str, float]], list[dict[str, Any]]]:
        source_manifest = self._source_manifest(run_id)
        profile = source_manifest.get("profile", {})
        tournament = profile.get("tournament", {}) if isinstance(profile, dict) else {}
        k_factor_value = tournament.get("k_factor", 32) if isinstance(tournament, dict) else 32
        if isinstance(k_factor_value, bool) or not isinstance(k_factor_value, int | float):
            raise TypeError("tournament k_factor must be numeric")
        k_factor = float(k_factor_value)
        events = self._domain_events(run_id)
        epochs = {
            epoch.epoch_id: epoch
            for epoch in (
                TournamentEpoch.model_validate(event.payload)
                for event in events
                if event.event_type == "TournamentEpochOpened"
            )
        }
        ratings: dict[str, dict[str, float]] = {}
        for event in events:
            if event.event_type == "InitialRatingAssigned":
                epoch_id = str(event.payload["epoch_id"])
                hypothesis_id = str(event.payload["hypothesis_id"])
                ratings.setdefault(epoch_id, {})[hypothesis_id] = float(event.payload["rating"])

        matches: list[dict[str, Any]] = []
        for event in events:
            if event.event_type != "MatchEvaluated":
                continue
            result = MatchResult.model_validate(event.payload)
            try:
                epoch = epochs[result.epoch_id]
            except KeyError as error:
                raise ValueError(f"match {result.match_id} references an unknown epoch") from error
            validate_match_contract(
                epoch,
                plan_version=int(event.payload["research_plan_version"]),
                rules_hash=str(event.payload["evaluation_rules_hash"]),
                prompt_hash=str(event.payload["ranking_prompt_hash"]),
                judge_hash=str(event.payload["judge_profile_hash"]),
                rating_policy=str(event.payload["rating_policy_version"]),
                admission_policy=str(event.payload["admission_policy_version"]),
            )
            epoch_ratings = ratings.setdefault(result.epoch_id, {})
            try:
                before_left = epoch_ratings[result.left_id]
                before_right = epoch_ratings[result.right_id]
            except KeyError as error:
                raise ValueError(
                    f"match {result.match_id} references an unrated TournamentEntry"
                ) from error
            after_left, after_right = before_left, before_right
            if result.decision.value == "decisive":
                after_left, after_right = apply_match(
                    before_left,
                    before_right,
                    result,
                    k_factor=k_factor,
                )
                epoch_ratings[result.left_id] = after_left
                epoch_ratings[result.right_id] = after_right
            item = result.model_dump(mode="json")
            item.update(
                {
                    "sequence": event.sequence,
                    "ratings_before": {
                        result.left_id: before_left,
                        result.right_id: before_right,
                    },
                    "ratings_after": {
                        result.left_id: after_left,
                        result.right_id: after_right,
                    },
                    "rating_updated": (after_left, after_right)
                    != (before_left, before_right),
                }
            )
            matches.append(item)
        ordered_ratings = {
            epoch_id: dict(sorted(values.items()))
            for epoch_id, values in sorted(ratings.items())
        }
        return ordered_ratings, matches

    def matches(self, run_id: str) -> list[dict[str, Any]]:
        return self._ratings_and_matches(run_id)[1]

    def ratings(self, run_id: str) -> dict[str, dict[str, float]]:
        return self._ratings_and_matches(run_id)[0]

    def tasks(self, run_id: str) -> list[dict[str, Any]]:
        with self.uow.session_factory() as session:
            rows = session.scalars(
                select(TaskRow).where(TaskRow.run_id == run_id).order_by(TaskRow.task_id)
            ).all()
            return [
                {
                    "task_id": row.task_id,
                    "run_id": row.run_id,
                    "idempotency_key": row.idempotency_key,
                    "intent_type": row.intent_type,
                    "state": row.state,
                    "payload": _loads(row.payload_json),
                    "attempt": row.attempt,
                }
                for row in rows
            ]

    def external_calls(self, run_id: str) -> list[dict[str, Any]]:
        with self.uow.session_factory() as session:
            rows = session.scalars(
                select(ExternalCallRow)
                .where(ExternalCallRow.run_id == run_id)
                .order_by(ExternalCallRow.external_call_id)
            ).all()
            return [
                {
                    "external_call_id": row.external_call_id,
                    "run_id": row.run_id,
                    "task_id": row.task_id,
                    "attempt": row.attempt,
                    "request_fingerprint": row.request_fingerprint,
                    "provider": row.provider,
                    "model_or_tool": row.model_or_tool,
                    "state": row.state,
                    "raw_artifact_ref": _loads(row.raw_artifact_ref_json),
                    "validated_payload": _loads(row.validated_artifact_ref_json),
                    "agent_result_id": row.agent_result_id,
                    "agent_result": _loads(row.agent_result_json),
                    "applied_domain_sequence": row.applied_domain_sequence,
                    "parent_call_id": row.parent_call_id,
                    "provider_response_id": row.provider_response_id,
                    "usage": _loads(row.usage_json),
                    "execution_context": _loads(row.execution_context_json),
                }
                for row in rows
            ]

    def costs(self, run_id: str) -> list[dict[str, Any]]:
        with self.uow.session_factory() as session:
            rows = session.scalars(
                select(CostEntryRow)
                .where(CostEntryRow.run_id == run_id)
                .order_by(CostEntryRow.cost_entry_id)
            ).all()
            return [
                {
                    "cost_entry_id": row.cost_entry_id,
                    "run_id": row.run_id,
                    "external_call_id": row.external_call_id,
                    "input_tokens": row.input_tokens,
                    "output_tokens": row.output_tokens,
                    "cost_usd": row.cost_usd,
                    "pricing_version": row.pricing_version,
                }
                for row in rows
            ]

    def literature(self, run_id: str) -> dict[str, Any]:
        queries: set[str] = set()
        cutoffs: set[str] = set()
        sources: list[dict[str, Any]] = []
        access_issues: list[dict[str, Any]] = []
        for event in self._domain_events(run_id):
            query = event.payload.get("pubmed_query")
            if isinstance(query, str) and query:
                queries.add(query)
            cutoff = event.payload.get("pubmed_query_cutoff")
            if isinstance(cutoff, str) and cutoff:
                cutoffs.add(cutoff)
            payload_sources = event.payload.get("source_documents", ())
            if isinstance(payload_sources, list | tuple):
                sources.extend(
                    dict(item) for item in payload_sources if isinstance(item, Mapping)
                )
            payload_issues = event.payload.get("access_issues", ())
            if isinstance(payload_issues, list | tuple):
                access_issues.extend(
                    dict(item) if isinstance(item, Mapping) else {"message": str(item)}
                    for item in payload_issues
                )
        unique_sources = _deduplicate(sources, "source_id") if sources else []
        unique_issues = {
            _canonical(issue): issue
            for issue in access_issues
        }
        return {
            "pubmed_queries": sorted(queries),
            "pubmed_query_cutoffs": sorted(cutoffs),
            "source_documents": unique_sources,
            "access_issues": [unique_issues[key] for key in sorted(unique_issues)],
        }

    def run_manifest(self, run_id: str) -> dict[str, Any]:
        row = self._run_row(run_id)
        events = self._domain_events(run_id)
        source_manifest = self._source_manifest(run_id)
        state_history = ["created"]
        state_history.extend(
            _RUN_EVENT_STATES[event.event_type]
            for event in events
            if event.event_type in _RUN_EVENT_STATES
        )
        stop_reason = next(
            (
                event.payload.get("reason")
                for event in reversed(events)
                if event.event_type == "RunStopping"
            ),
            None,
        )
        completeness = next(
            (
                event.payload.get("completeness")
                for event in reversed(events)
                if event.event_type == "FinalizationCompleted"
            ),
            None,
        )
        calls = self.external_calls(run_id)
        costs = self.costs(run_id)
        literature = self.literature(run_id)
        epochs = self.epochs(run_id)
        ratings = self.ratings(run_id)
        metadata = []
        for call in calls:
            context = call.get("execution_context")
            context = context if isinstance(context, dict) else {}
            metadata.append(
                {
                    "external_call_id": call["external_call_id"],
                    "provider": call["provider"],
                    "model_or_tool": call["model_or_tool"],
                    "provider_response_id": call["provider_response_id"],
                    "request_fingerprint": call["request_fingerprint"],
                    "skill_id": context.get("skill_id"),
                    "skill_version": context.get("skill_version"),
                    "output_schema_version": context.get("output_schema_version"),
                    "input_snapshot_hash": context.get("input_snapshot_hash"),
                }
            )
        return {
            **source_manifest,
            "run_id": run_id,
            "final_state": row.state,
            "current_sequence": row.current_sequence,
            "state_history": state_history,
            "stop_reason": stop_reason,
            "completeness": completeness,
            "finalization_state": "completed" if completeness is not None else "not_completed",
            "tournament_epochs": epochs,
            "anchor_set_ids": sorted(
                str(epoch["anchor_set_id"])
                for epoch in epochs
                if epoch.get("anchor_set_id") is not None
            ),
            "ratings_by_epoch": ratings,
            "ranking_state": {
                epoch_id: sorted(
                    values,
                    key=lambda hypothesis_id: values[hypothesis_id],
                    reverse=True,
                )
                for epoch_id, values in ratings.items()
            },
            "hypothesis_count": len(self.hypotheses(run_id)),
            "review_count": len(self.reviews(run_id)),
            "novelty_assessment_count": len(self.novelty_assessments(run_id)),
            "proximity_edge_count": len(self.proximity(run_id)),
            "match_count": len(self.matches(run_id)),
            "task_count": len(self.tasks(run_id)),
            "external_call_count": len(calls),
            "raw_artifact_count": sum(call["raw_artifact_ref"] is not None for call in calls),
            "cost_entry_count": len(costs),
            "total_cost_usd": str(sum(Decimal(item["cost_usd"]) for item in costs)),
            "skill_prompt_provider_model_metadata": metadata,
            "ranking_prompt_hashes": sorted(
                {str(epoch["ranking_prompt_hash"]) for epoch in epochs}
            ),
            "pubmed_query_cutoffs": literature["pubmed_query_cutoffs"],
            "literature_access_issues": literature["access_issues"],
        }


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, values: list[dict[str, Any]]) -> None:
    lines = [_canonical(value) for value in values]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _export_artifacts(
    output_dir: Path,
    calls: list[dict[str, Any]],
    artifacts: ArtifactStore,
) -> list[dict[str, Any]]:
    exported: list[dict[str, Any]] = []
    raw_dir = output_dir / "raw_artifacts"
    for call in calls:
        raw_value = call.get("raw_artifact_ref")
        if raw_value is None:
            continue
        ref = ArtifactRef.model_validate(raw_value)
        body = artifacts.read(ref)
        digest = hashlib.sha256(body).hexdigest()
        if ref.sha256 != f"sha256:{digest}" or ref.byte_length != len(body):
            raise ValueError(f"raw artifact integrity mismatch for {call['external_call_id']}")
        suffix = ".json" if ref.mime_type.startswith("application/json") else ".bin"
        relative_path = Path("raw_artifacts") / f"{digest}{suffix}"
        destination = output_dir / relative_path
        raw_dir.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if destination.read_bytes() != body:
                raise ValueError(f"raw artifact hash collision for {digest}")
        else:
            destination.write_bytes(body)
        manifest = artifacts.discover_raw(str(call["external_call_id"]))
        if manifest is None:
            raise ValueError(f"raw manifest missing for {call['external_call_id']}")
        artifacts.confirm_raw(manifest)
        exported.append(
            {
                "external_call_id": call["external_call_id"],
                "exported_path": relative_path.as_posix(),
                "artifact_ref": ref.model_dump(mode="json"),
                "raw_manifest": manifest.model_dump(mode="json"),
            }
        )
    return exported


def export_run(
    run_id: str,
    output_dir: Path,
    read_model: RunReadModel,
    artifacts: ArtifactStore,
) -> Path:
    """Export one persisted run without overwriting an existing destination."""

    output_dir = Path(output_dir)
    if output_dir.exists():
        raise FileExistsError(output_dir)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = output_dir.with_name(f".{output_dir.name}.partial")
    staging.mkdir(parents=False, exist_ok=False)
    try:
        calls = read_model.external_calls(run_id)
        _write_json(staging / "manifest.json", read_model.run_manifest(run_id))
        _write_jsonl(staging / "events.jsonl", read_model.events(run_id))
        _write_json(staging / "hypotheses.json", read_model.hypotheses(run_id))
        _write_json(staging / "reviews.json", read_model.reviews(run_id))
        _write_json(
            staging / "novelty_assessments.json",
            read_model.novelty_assessments(run_id),
        )
        _write_json(staging / "proximity.json", read_model.proximity(run_id))
        _write_json(staging / "tournament_epochs.json", read_model.epochs(run_id))
        _write_json(staging / "matches.json", read_model.matches(run_id))
        _write_json(staging / "ratings.json", read_model.ratings(run_id))
        _write_json(staging / "tasks.json", read_model.tasks(run_id))
        _write_json(staging / "external_calls.json", calls)
        _write_json(staging / "costs.json", read_model.costs(run_id))
        _write_json(staging / "literature.json", read_model.literature(run_id))
        _write_json(staging / "artifacts.json", _export_artifacts(staging, calls, artifacts))
        if output_dir.exists():
            raise FileExistsError(output_dir)
        staging.rename(output_dir)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return output_dir


class CoreReleaseReport(BaseModel):
    """Persisted aggregate evidence for the Core Preview release invariants."""

    model_config = ConfigDict(frozen=True)

    persisted_task_count: int
    external_call_count: int
    match_count: int
    agent_created_task_count: int
    cross_epoch_elo_comparison_count: int
    non_decisive_rating_update_count: int
    proximity_derived_novelty_count: int
    run_completed_without_finalization_count: int
    raw_parsed_before_persist_count: int


def verify_core_release_invariants(
    run_id: str,
    read_model: RunReadModel,
) -> CoreReleaseReport:
    """Compute release violations from durable rows, events, and projections."""

    events = read_model.events(run_id)
    tasks = read_model.tasks(run_id)
    calls = read_model.external_calls(run_id)
    supervisor_task_ids = {
        str(event["payload"]["task_id"])
        for event in events
        if event["event_type"] == "TaskEnqueued"
        and event["payload"].get("created_by") == "supervisor"
        and isinstance(event["payload"].get("task_id"), str)
    }
    agent_created_tasks = sum(
        str(task["task_id"]) not in supervisor_task_ids for task in tasks
    )

    epoch_contracts = {
        str(event["payload"]["epoch_id"]): event["payload"]
        for event in events
        if event["event_type"] == "TournamentEpochOpened"
    }
    entry_epochs: dict[str, set[str]] = {}
    for event in events:
        if event["event_type"] == "TournamentEntryCreated":
            entry_epochs.setdefault(str(event["payload"]["hypothesis_id"]), set()).add(
                str(event["payload"]["epoch_id"])
            )
    cross_epoch = 0
    contract_fields = (
        "research_plan_version",
        "evaluation_rules_hash",
        "ranking_prompt_hash",
        "judge_profile_hash",
        "rating_policy_version",
        "admission_policy_version",
    )
    for event in events:
        if event["event_type"] != "MatchEvaluated":
            continue
        payload = event["payload"]
        epoch_id = str(payload.get("epoch_id"))
        epoch = epoch_contracts.get(epoch_id)
        participants_share_epoch = all(
            epoch_id in entry_epochs.get(str(payload.get(side)), set())
            for side in ("left_id", "right_id")
        )
        contract_matches = epoch is not None and all(
            payload.get(field) == epoch.get(field) for field in contract_fields
        )
        cross_epoch += not participants_share_epoch or not contract_matches

    projected_matches = read_model.matches(run_id) if cross_epoch == 0 else []
    non_decisive_ids = {
        str(event["payload"].get("match_id"))
        for event in events
        if event["event_type"] == "MatchEvaluated"
        and event["payload"].get("decision") != "decisive"
    }
    non_decisive_rating_updates = sum(
        bool(match["rating_updated"])
        for match in projected_matches
        if match["decision"] != "decisive"
    ) + sum(
        event["event_type"] == "RatingUpdated"
        and str(event["payload"].get("match_id")) in non_decisive_ids
        for event in events
    )

    proximity_result_ids = {
        str(event["payload"].get("source_result_id"))
        for event in events
        if event["event_type"] == "ProximityAssessed"
        and event["payload"].get("source_result_id") is not None
    }
    proximity_derived_novelty = 0
    for event in events:
        payload = event["payload"]
        has_novelty = (
            event["event_type"] in {"NoveltyAssessmentCreated", "NoveltyAssessmentRecorded"}
            or payload.get("novelty_assessment") is not None
            or bool(payload.get("novelty_assessments"))
        )
        if has_novelty and (
            event["event_type"] == "ProximityAssessed"
            or str(payload.get("source_result_id")) in proximity_result_ids
        ):
            proximity_derived_novelty += 1

    terminal_indexes = [
        index
        for index, event in enumerate(events)
        if event["event_type"] in {"RunCompleted", "RunCompletedPartial"}
    ]
    completed_without_finalization = sum(
        not any(
            event["event_type"] == "FinalizationCompleted"
            for event in events[:terminal_index]
        )
        for terminal_index in terminal_indexes
    )
    parsed_without_raw = sum(
        (
            call.get("validated_payload") is not None
            or call.get("agent_result") is not None
            or call.get("applied_domain_sequence") is not None
        )
        and call.get("raw_artifact_ref") is None
        for call in calls
    )
    return CoreReleaseReport(
        persisted_task_count=len(tasks),
        external_call_count=len(calls),
        match_count=sum(event["event_type"] == "MatchEvaluated" for event in events),
        agent_created_task_count=agent_created_tasks,
        cross_epoch_elo_comparison_count=cross_epoch,
        non_decisive_rating_update_count=non_decisive_rating_updates,
        proximity_derived_novelty_count=proximity_derived_novelty,
        run_completed_without_finalization_count=completed_without_finalization,
        raw_parsed_before_persist_count=parsed_without_raw,
    )
