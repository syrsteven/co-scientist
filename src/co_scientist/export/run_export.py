"""Deterministic export of one durable Core Preview run."""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from co_scientist.adapters.persistence.sqlite import (
    BudgetReservationRow,
    CostEntryRow,
    EventRow,
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
    validate_match_contract,
)
from co_scientist.events.models import DomainEvent
from co_scientist.events.reducers import replay_hypothesis
from co_scientist.ports.artifact_store import ArtifactRef, ArtifactStore, RawArtifactManifest
from co_scientist.ports.external_provider import thaw_json
from co_scientist.runtime.external_calls import execution_context_fingerprint


class RunReadModel(Protocol):
    """Read-only durable data needed by export and release verification."""

    def run_manifest(self, run_id: str) -> dict[str, Any]: ...

    def source_manifest(self, run_id: str) -> dict[str, Any]: ...

    def run_state(self, run_id: str) -> str: ...

    def events(self, run_id: str) -> list[dict[str, Any]]: ...

    def hypotheses(self, run_id: str) -> list[dict[str, Any]]: ...

    def hypothesis_projections(self, run_id: str) -> list[dict[str, Any]]: ...

    def reviews(self, run_id: str) -> list[dict[str, Any]]: ...

    def novelty_assessments(self, run_id: str) -> list[dict[str, Any]]: ...

    def proximity(self, run_id: str) -> list[dict[str, Any]]: ...

    def epochs(self, run_id: str) -> list[dict[str, Any]]: ...

    def matches(self, run_id: str) -> list[dict[str, Any]]: ...

    def ratings(self, run_id: str) -> dict[str, dict[str, float]]: ...

    def tasks(self, run_id: str) -> list[dict[str, Any]]: ...

    def budget_reservations(self, run_id: str) -> list[dict[str, Any]]: ...

    def convergence_checkpoints(self, run_id: str) -> list[dict[str, Any]]: ...

    def stop_decisions(self, run_id: str) -> list[dict[str, Any]]: ...

    def external_calls(self, run_id: str) -> list[dict[str, Any]]: ...

    def costs(self, run_id: str) -> list[dict[str, Any]]: ...

    def literature(self, run_id: str) -> dict[str, Any]: ...

    def snapshot(self, run_id: str) -> AbstractContextManager[RunReadModel]: ...


_RUN_EVENT_STATES = {
    "RunStarted": "running",
    "RunPausing": "pausing",
    "RunPaused": "paused",
    "RunResumed": "running",
    "RunStopping": "stopping",
    "RunCompleted": "completed",
    "RunCompletedPartial": "completed_partial",
    "RunCancelled": "cancelled",
    "RunFailed": "failed",
}


def _loads(value: str | None) -> Any:
    return json.loads(value) if value is not None else None


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


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


def _utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


class SqliteRunReadModel:
    """Build deterministic projections from one SQLite unit of work."""

    def __init__(self, uow: SqliteUnitOfWork) -> None:
        self.uow = uow
        self._snapshot_session: Session | None = None

    @contextmanager
    def snapshot(self, run_id: str) -> Iterator[SqliteRunReadModel]:
        """Use one explicit SQLite read transaction for every exported projection."""

        if self._snapshot_session is not None:
            raise RuntimeError("SQLite read snapshot is already active")
        session = self.uow.session_factory()
        try:
            session.connection().exec_driver_sql("BEGIN")
            self._snapshot_session = session
            self._run_row(run_id)
            yield self
        finally:
            self._snapshot_session = None
            session.rollback()
            session.close()

    def _run_row(self, run_id: str) -> RunRow:
        if self._snapshot_session is not None:
            row = self._snapshot_session.get(RunRow, run_id)
            if row is None:
                raise KeyError(f"unknown run: {run_id}")
            return row
        with self.uow.session_factory() as session:
            row = session.get(RunRow, run_id)
            if row is None:
                raise KeyError(f"unknown run: {run_id}")
            session.expunge(row)
            return row

    def _domain_events(self, run_id: str) -> list[DomainEvent]:
        self._run_row(run_id)
        if self._snapshot_session is not None:
            rows = self._snapshot_session.scalars(
                select(EventRow)
                .where(EventRow.run_id == run_id)
                .order_by(EventRow.sequence)
            ).all()
            return [row.to_domain() for row in rows]
        return self.uow.load(run_id)

    def _source_manifest(self, run_id: str) -> dict[str, Any]:
        value = _loads(self._run_row(run_id).manifest_json)
        if not isinstance(value, dict):
            raise TypeError("run manifest must be a JSON object")
        return value

    def source_manifest(self, run_id: str) -> dict[str, Any]:
        return self._source_manifest(run_id)

    def _anchor_ids(self, run_id: str) -> frozenset[str]:
        manifest = self._source_manifest(run_id)
        raw_sets = manifest.get("anchor_sets", [])
        if not isinstance(raw_sets, list):
            raise TypeError("anchor_sets must be a list")
        return frozenset(
            str(member["anchor_id"])
            for anchor_set in raw_sets
            if isinstance(anchor_set, Mapping)
            for member in anchor_set.get("members", [])
            if isinstance(member, Mapping)
            and isinstance(member.get("anchor_id"), str)
            and member.get("anchor_id")
        )

    def events(self, run_id: str) -> list[dict[str, Any]]:
        return [event.model_dump(mode="json") for event in self._domain_events(run_id)]

    def run_state(self, run_id: str) -> str:
        return self._run_row(run_id).state

    def hypotheses(self, run_id: str) -> list[dict[str, Any]]:
        exported: list[dict[str, Any]] = []
        anchor_ids = self._anchor_ids(run_id)
        for event in self._domain_events(run_id):
            if event.event_type != "HypothesisContentCreated":
                continue
            hypothesis_id = event.payload.get("hypothesis_id")
            if not isinstance(hypothesis_id, str) or not hypothesis_id:
                raise ValueError("HypothesisContentCreated is missing hypothesis_id")
            if hypothesis_id in anchor_ids:
                continue
            content = HypothesisContent.model_validate(event.payload)
            item = content.model_dump(mode="json")
            item.update(
                {
                    "hypothesis_id": hypothesis_id,
                    "content_hash": event.payload.get("content_hash", content.content_hash),
                    "created_sequence": event.sequence,
                }
            )
            exported.append(item)
        return exported

    def hypothesis_projections(self, run_id: str) -> list[dict[str, Any]]:
        events = self._domain_events(run_id)
        anchor_ids = self._anchor_ids(run_id)
        hypothesis_ids = sorted(
            {
                str(event.payload["hypothesis_id"])
                for event in events
                if event.event_type == "HypothesisContentCreated"
                and str(event.payload["hypothesis_id"]) not in anchor_ids
            }
        )
        return [
            replay_hypothesis(hypothesis_id, events).model_dump(mode="json")
            for hypothesis_id in hypothesis_ids
        ]

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
                if event.event_type in {
                    "NoveltyAssessmentCreated",
                    "NoveltyAssessmentRecorded",
                } and candidate is event.payload:
                    candidate = {
                        key: value
                        for key, value in candidate.items()
                        if key
                        not in {
                            "source_result_id",
                            "source_task_id",
                            "status",
                            "epoch_id",
                        }
                    }
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

        rating_updates: dict[str, list[dict[str, Any]]] = {}
        for event in events:
            if event.event_type != "RatingUpdated":
                continue
            match_id = event.payload.get("match_id")
            if not isinstance(match_id, str) or not match_id:
                raise ValueError("RatingUpdated must reference a match_id")
            rating_updates.setdefault(match_id, []).append(dict(event.payload))

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
                updates = rating_updates.pop(result.match_id, [])
                if len(updates) != 2:
                    raise ValueError(
                        f"decisive match {result.match_id} requires two persisted RatingUpdated events"
                    )
                updates_by_hypothesis = {
                    str(update["hypothesis_id"]): update for update in updates
                }
                if set(updates_by_hypothesis) != {result.left_id, result.right_id}:
                    raise ValueError(
                        f"match {result.match_id} rating updates do not match participants"
                    )
                left_update = updates_by_hypothesis[result.left_id]
                right_update = updates_by_hypothesis[result.right_id]
                if (
                    left_update.get("epoch_id") != result.epoch_id
                    or right_update.get("epoch_id") != result.epoch_id
                    or left_update.get("rating_policy_version")
                    != epoch.rating_policy_version
                    or right_update.get("rating_policy_version")
                    != epoch.rating_policy_version
                    or float(left_update["before_rating"]) != before_left
                    or float(right_update["before_rating"]) != before_right
                ):
                    raise ValueError(
                        f"match {result.match_id} persisted rating provenance mismatch"
                    )
                after_left = float(left_update["rating"])
                after_right = float(right_update["rating"])
                epoch_ratings[result.left_id] = after_left
                epoch_ratings[result.right_id] = after_right
            elif rating_updates.pop(result.match_id, []):
                raise ValueError(
                    f"non-decisive match {result.match_id} cannot have RatingUpdated events"
                )
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
        if rating_updates:
            raise ValueError("orphan RatingUpdated events reference unknown matches")
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
        statement = select(TaskRow).where(TaskRow.run_id == run_id).order_by(TaskRow.task_id)
        if self._snapshot_session is not None:
            rows = self._snapshot_session.scalars(statement).all()
        else:
            with self.uow.session_factory() as session:
                rows = session.scalars(statement).all()
        lease_events: dict[str, list[dict[str, Any]]] = {}
        for event in self._domain_events(run_id):
            if event.event_type not in {
                "TaskLeaseClaimed",
                "TaskLeaseAdopted",
                "TaskLeaseExpired",
                "TaskLeaseExhausted",
                "TaskRequeued",
            }:
                continue
            task_id = event.payload.get("task_id")
            if not isinstance(task_id, str):
                continue
            payload = {
                key: value
                for key, value in dict(thaw_json(event.payload)).items()
                if key != "lease_token"
            }
            lease_events.setdefault(task_id, []).append(
                {
                    "sequence": event.sequence,
                    "event_type": event.event_type,
                    "payload": payload,
                }
            )
        return [
            {
                "task_id": row.task_id,
                "run_id": row.run_id,
                "idempotency_key": row.idempotency_key,
                "intent_type": row.intent_type,
                "state": row.state,
                "payload": _loads(row.payload_json),
                "attempt": row.attempt,
                "max_attempts": row.max_attempts,
                "lease_history": lease_events.get(row.task_id, []),
            }
            for row in rows
        ]

    def budget_reservations(self, run_id: str) -> list[dict[str, Any]]:
        statement = (
            select(BudgetReservationRow)
            .where(BudgetReservationRow.run_id == run_id)
            .order_by(BudgetReservationRow.reservation_id)
        )
        if self._snapshot_session is not None:
            rows = self._snapshot_session.scalars(statement).all()
        else:
            with self.uow.session_factory() as session:
                rows = session.scalars(statement).all()
        return [
            {
                "reservation_id": row.reservation_id,
                "run_id": row.run_id,
                "task_id": row.task_id,
                "external_call_id": row.external_call_id,
                "idempotency_key": row.idempotency_key,
                "state": row.state,
                "estimate": {
                    "model_calls": row.estimated_model_calls,
                    "input_tokens": row.estimated_input_tokens,
                    "output_tokens": row.estimated_output_tokens,
                    "cost_usd": row.estimated_cost_usd,
                    "hypotheses": row.estimated_hypotheses,
                    "matches": row.estimated_matches,
                },
                "actual": {
                    "model_calls": row.actual_model_calls,
                    "input_tokens": row.actual_input_tokens,
                    "output_tokens": row.actual_output_tokens,
                    "cost_usd": row.actual_cost_usd,
                    "hypotheses": row.actual_hypotheses,
                    "matches": row.actual_matches,
                },
                "version": row.version,
                "created_at": _utc_iso(row.created_at),
                "updated_at": _utc_iso(row.updated_at),
            }
            for row in rows
        ]

    def convergence_checkpoints(self, run_id: str) -> list[dict[str, Any]]:
        events = self._domain_events(run_id)
        stop_reasons = {
            str(event.payload.get("checkpoint_id")): event.payload.get("reason")
            for event in events
            if event.event_type == "StopPolicyTriggered"
        }
        return [
            {
                **dict(thaw_json(event.payload)),
                "recorded_sequence": event.sequence,
                "stop_reason": stop_reasons.get(str(event.payload.get("checkpoint_id"))),
            }
            for event in events
            if event.event_type == "ConvergenceCheckpointRecorded"
        ]

    def stop_decisions(self, run_id: str) -> list[dict[str, Any]]:
        events = self._domain_events(run_id)
        decisions: list[dict[str, Any]] = []
        for trigger in events:
            if trigger.event_type != "StopPolicyTriggered":
                continue
            checkpoint_id = trigger.payload.get("checkpoint_id")
            suffix = [event for event in events if event.sequence > trigger.sequence]
            signal = next(
                (
                    event
                    for event in reversed(events[: trigger.sequence - 1])
                    if event.event_type == "StopSignalObserved"
                    and event.payload.get("checkpoint_id") == checkpoint_id
                ),
                None,
            )
            stopping = next(
                (
                    event
                    for event in suffix
                    if event.event_type == "RunStopping"
                    and event.payload.get("checkpoint_id") == checkpoint_id
                ),
                None,
            )
            requested = next(
                (
                    event
                    for event in suffix
                    if event.event_type == "FinalizationRequested"
                    and event.payload.get("checkpoint_id") == checkpoint_id
                ),
                None,
            )
            finalized = next(
                (event for event in suffix if event.event_type == "FinalizationCompleted"),
                None,
            )
            terminal = next(
                (
                    event
                    for event in suffix
                    if event.event_type
                    in {"RunCompleted", "RunCompletedPartial", "RunCancelled", "RunFailed"}
                ),
                None,
            )
            decisions.append(
                {
                    "checkpoint_id": checkpoint_id,
                    "checkpoint_source_sequence": trigger.payload.get(
                        "checkpoint_source_sequence"
                    ),
                    "reason": trigger.payload.get("reason"),
                    "signal": (
                        dict(thaw_json(signal.payload)) if signal is not None else None
                    ),
                    "signal_sequence": signal.sequence if signal is not None else None,
                    "trigger_sequence": trigger.sequence,
                    "stopping_sequence": stopping.sequence if stopping is not None else None,
                    "finalization_task_id": (
                        requested.payload.get("task_id") if requested is not None else None
                    ),
                    "finalization_requested_sequence": (
                        requested.sequence if requested is not None else None
                    ),
                    "finalization_state": (
                        "completed"
                        if finalized is not None
                        else "requested"
                        if requested is not None
                        else "missing"
                    ),
                    "finalization_sequence": (
                        finalized.sequence if finalized is not None else None
                    ),
                    "completeness": (
                        finalized.payload.get("completeness")
                        if finalized is not None
                        else None
                    ),
                    "terminal_event": terminal.event_type if terminal is not None else None,
                    "terminal_sequence": terminal.sequence if terminal is not None else None,
                }
            )
        return decisions

    def external_calls(self, run_id: str) -> list[dict[str, Any]]:
        statement = (
            select(ExternalCallRow)
            .where(ExternalCallRow.run_id == run_id)
            .order_by(ExternalCallRow.external_call_id)
        )
        if self._snapshot_session is not None:
            rows = self._snapshot_session.scalars(statement).all()
        else:
            with self.uow.session_factory() as session:
                rows = session.scalars(statement).all()
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
        statement = (
            select(CostEntryRow)
            .where(CostEntryRow.run_id == run_id)
            .order_by(CostEntryRow.cost_entry_id)
        )
        if self._snapshot_session is not None:
            rows = self._snapshot_session.scalars(statement).all()
        else:
            with self.uow.session_factory() as session:
                rows = session.scalars(statement).all()
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
        reservations = self.budget_reservations(run_id)
        checkpoints = self.convergence_checkpoints(run_id)
        stop_decisions = self.stop_decisions(run_id)
        raw_anchor_sets = source_manifest.get("anchor_sets", [])
        if not isinstance(raw_anchor_sets, list):
            raise TypeError("anchor_sets must be a list")
        anchor_sets: list[dict[str, Any]] = []
        anchor_sets_by_id: dict[str, dict[str, Any]] = {}
        for raw_anchor_set in raw_anchor_sets:
            if not isinstance(raw_anchor_set, Mapping):
                raise TypeError("anchor set must be an object")
            anchor_set = dict(raw_anchor_set)
            anchor_set_id = anchor_set.get("anchor_set_id")
            members = anchor_set.get("members")
            if (
                not isinstance(anchor_set_id, str)
                or not anchor_set_id
                or not isinstance(members, list)
                or not members
            ):
                raise ValueError("anchor set must contain frozen members")
            normalized_members: list[dict[str, Any]] = []
            anchor_ids: set[str] = set()
            for member in members:
                if not isinstance(member, Mapping):
                    raise TypeError("anchor set member must be an object")
                anchor_id = member.get("anchor_id")
                if (
                    not isinstance(anchor_id, str)
                    or not anchor_id
                    or anchor_id in anchor_ids
                    or not _is_sha256(member.get("content_hash"))
                ):
                    raise ValueError("anchor set must contain unique frozen members")
                anchor_ids.add(anchor_id)
                normalized_members.append(dict(member))
            if anchor_set_id in anchor_sets_by_id:
                raise ValueError(f"duplicate anchor set: {anchor_set_id}")
            normalized = {
                **anchor_set,
                "members": normalized_members,
            }
            anchor_sets_by_id[anchor_set_id] = normalized
            anchor_sets.append(normalized)
        for epoch in epochs:
            anchor_set_id = epoch.get("anchor_set_id")
            if anchor_set_id is not None and anchor_set_id not in anchor_sets_by_id:
                raise ValueError(f"anchor set {anchor_set_id} has no frozen members")
        profile = source_manifest.get("profile")
        tournament = profile.get("tournament") if isinstance(profile, Mapping) else None
        required_anchor_count = (
            tournament.get("anchor_count") if isinstance(tournament, Mapping) else None
        )
        if isinstance(required_anchor_count, int) and not isinstance(required_anchor_count, bool):
            for anchor_set in anchor_sets:
                if len(anchor_set["members"]) != required_anchor_count:
                    raise ValueError("anchor set member count does not match frozen profile")
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
                    "prompt_hash": context.get("prompt_hash"),
                }
            )
        admission_evidence = [
            {
                "sequence": event.sequence,
                "hypothesis_id": event.payload.get("hypothesis_id"),
                "epoch_id": event.payload.get("epoch_id"),
                "evidence": thaw_json(event.payload),
            }
            for event in events
            if event.event_type == "HypothesisTournamentReady"
        ]
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
            "anchor_sets": sorted(anchor_sets, key=lambda item: str(item["anchor_set_id"])),
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
            "hypothesis_count": len(self.hypothesis_projections(run_id)),
            "review_count": len(self.reviews(run_id)),
            "novelty_assessment_count": len(self.novelty_assessments(run_id)),
            "proximity_edge_count": len(self.proximity(run_id)),
            "match_count": len(self.matches(run_id)),
            "task_count": len(self.tasks(run_id)),
            "external_call_count": len(calls),
            "raw_artifact_count": sum(call["raw_artifact_ref"] is not None for call in calls),
            "cost_entry_count": len(costs),
            "total_cost_usd": str(sum(Decimal(item["cost_usd"]) for item in costs)),
            "budget_reservation_count": len(reservations),
            "convergence_checkpoint_count": len(checkpoints),
            "stop_decision_count": len(stop_decisions),
            "final_stop_evidence": stop_decisions[-1] if stop_decisions else None,
            "admission_evidence": admission_evidence,
            "raw_artifact_bindings": [
                {
                    "external_call_id": call["external_call_id"],
                    "raw_artifact_ref": call["raw_artifact_ref"],
                    "provider_response_id": call["provider_response_id"],
                }
                for call in calls
            ],
            "cost_bindings": costs,
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


_RAW_REQUIRED_STATES = {
    "raw_response_persisted",
    "validated",
    "agent_result_submitted",
    "domain_result_applied",
}


def _validate_raw_artifacts(
    calls: list[dict[str, Any]],
    artifacts: ArtifactStore,
) -> list[tuple[dict[str, Any], ArtifactRef, bytes, RawArtifactManifest]]:
    validated: list[tuple[dict[str, Any], ArtifactRef, bytes, RawArtifactManifest]] = []
    for call in calls:
        raw_value = call.get("raw_artifact_ref")
        if raw_value is None:
            if call.get("state") in _RAW_REQUIRED_STATES:
                raise ValueError(
                    f"call {call['external_call_id']} in state {call['state']} "
                    "requires persisted raw evidence"
                )
            continue
        ref = ArtifactRef.model_validate(raw_value)
        body = artifacts.read(ref)
        digest = hashlib.sha256(body).hexdigest()
        if ref.sha256 != f"sha256:{digest}" or ref.byte_length != len(body):
            raise ValueError(f"raw artifact integrity mismatch for {call['external_call_id']}")
        manifest = artifacts.discover_raw(str(call["external_call_id"]))
        if manifest is None:
            raise ValueError(f"raw manifest missing for {call['external_call_id']}")
        context = call.get("execution_context")
        if not isinstance(context, Mapping):
            raise TypeError(f"raw manifest has no persisted call context for {manifest.call_id}")
        if (
            manifest.call_id != call["external_call_id"]
            or manifest.artifact_ref != ref
            or manifest.run_id != call["run_id"]
            or manifest.task_id != call["task_id"]
            or manifest.request_fingerprint != call["request_fingerprint"]
            or manifest.execution_context_fingerprint
            != execution_context_fingerprint(context)
            or manifest.provider_response_id != call["provider_response_id"]
            or manifest.usage != call["usage"]
        ):
            raise ValueError(
                f"raw manifest does not match persisted call {call['external_call_id']}"
            )
        artifacts.confirm_raw(manifest)
        validated.append((call, ref, body, manifest))
    return validated


def _export_artifacts(
    output_dir: Path,
    validated: list[tuple[dict[str, Any], ArtifactRef, bytes, RawArtifactManifest]],
) -> list[dict[str, Any]]:
    exported: list[dict[str, Any]] = []
    raw_dir = output_dir / "raw_artifacts"
    for call, ref, body, manifest in validated:
        digest = ref.sha256.removeprefix("sha256:")
        suffix = ".json" if ref.mime_type.startswith("application/json") else ".bin"
        relative_path = Path("raw_artifacts") / f"{digest}{suffix}"
        destination = output_dir / relative_path
        raw_dir.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if destination.read_bytes() != body:
                raise ValueError(f"raw artifact hash collision for {digest}")
        else:
            destination.write_bytes(body)
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
        with read_model.snapshot(run_id) as snapshot:
            calls = snapshot.external_calls(run_id)
            raw_artifacts = _validate_raw_artifacts(calls, artifacts)
            _write_json(staging / "manifest.json", snapshot.run_manifest(run_id))
            _write_jsonl(staging / "events.jsonl", snapshot.events(run_id))
            _write_json(staging / "hypotheses.json", snapshot.hypotheses(run_id))
            _write_json(
                staging / "hypothesis_projections.json",
                snapshot.hypothesis_projections(run_id),
            )
            _write_json(staging / "reviews.json", snapshot.reviews(run_id))
            _write_json(
                staging / "novelty_assessments.json",
                snapshot.novelty_assessments(run_id),
            )
            _write_json(staging / "proximity.json", snapshot.proximity(run_id))
            _write_json(staging / "tournament_epochs.json", snapshot.epochs(run_id))
            _write_json(staging / "matches.json", snapshot.matches(run_id))
            _write_json(staging / "ratings.json", snapshot.ratings(run_id))
            _write_json(staging / "tasks.json", snapshot.tasks(run_id))
            _write_json(
                staging / "budget_reservations.json",
                snapshot.budget_reservations(run_id),
            )
            _write_json(
                staging / "convergence_checkpoints.json",
                snapshot.convergence_checkpoints(run_id),
            )
            _write_json(
                staging / "stop_decisions.json",
                snapshot.stop_decisions(run_id),
            )
            _write_json(staging / "external_calls.json", calls)
            _write_json(staging / "costs.json", snapshot.costs(run_id))
            _write_json(staging / "literature.json", snapshot.literature(run_id))
            _write_json(
                staging / "artifacts.json",
                _export_artifacts(staging, raw_artifacts),
            )
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
    violation_count: int
    stale_lease_accepted_count: int
    external_call_without_reservation_count: int
    invalid_budget_reservation_count: int
    stop_without_valid_checkpoint_count: int
    unrecoverable_stopping_count: int
    terminal_mutation_count: int
    projection_mismatch_count: int
    bootstrap_epoch_bypass_count: int
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
    reservations = read_model.budget_reservations(run_id)
    tasks_by_id = {str(task["task_id"]): task for task in tasks}
    reservations_by_id = {
        str(reservation["reservation_id"]): reservation for reservation in reservations
    }
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
    durable_lease_fingerprints = {
        (
            str(event["payload"].get("task_id")),
            event["payload"].get("attempt"),
            event["payload"].get("lease_fence_fingerprint"),
        )
        for event in events
        if event["event_type"] in {"TaskLeaseClaimed", "TaskLeaseAdopted"}
        and isinstance(event["payload"].get("task_id"), str)
        and isinstance(event["payload"].get("attempt"), int)
        and _is_sha256(event["payload"].get("lease_fence_fingerprint"))
    }

    stale_lease_accepted = 0
    calls_without_reservation = 0
    for call in calls:
        context = call.get("execution_context")
        context = context if isinstance(context, Mapping) else {}
        task = tasks_by_id.get(str(call.get("task_id")))
        lease_binding = (
            str(call.get("task_id")),
            call.get("attempt"),
            context.get("lease_fence_fingerprint"),
        )
        if call.get("state") == "domain_result_applied" and (
            task is None
            or call.get("attempt") != task.get("attempt")
            or context.get("attempt") != call.get("attempt")
            or lease_binding not in durable_lease_fingerprints
        ):
            stale_lease_accepted += 1
        reservation_id = context.get("reservation_id")
        reservation = (
            reservations_by_id.get(str(reservation_id))
            if isinstance(reservation_id, str)
            else None
        )
        if (
            reservation is None
            or reservation.get("run_id") != run_id
            or reservation.get("task_id") != call.get("task_id")
            or reservation.get("external_call_id") != call.get("external_call_id")
        ):
            calls_without_reservation += 1

    invalid_reservations = 0
    for key in ("idempotency_key", "task_id", "external_call_id"):
        values = [
            str(item[key])
            for item in reservations
            if item.get(key) is not None
        ]
        invalid_reservations += len(values) - len(set(values))
    invalid_reservations += sum(
        reservation.get("run_id") != run_id
        or str(reservation.get("task_id")) not in tasks_by_id
        or reservation.get("state") not in {"reserved", "settled", "released"}
        for reservation in reservations
    )
    source_manifest = read_model.source_manifest(run_id)
    budget = source_manifest.get("budget")
    budget = budget if isinstance(budget, Mapping) else {}
    estimate_fields = {
        "max_model_calls": "model_calls",
        "max_input_tokens": "input_tokens",
        "max_output_tokens": "output_tokens",
        "max_usd": "cost_usd",
        "max_hypotheses": "hypotheses",
        "max_matches": "matches",
    }
    for limit_key, estimate_key in estimate_fields.items():
        limit = budget.get(limit_key)
        if limit is None:
            continue
        total = sum(
            Decimal(
                str(
                    reservation[
                        "actual" if reservation.get("state") == "settled" else "estimate"
                    ][estimate_key]
                )
            )
            for reservation in reservations
            if reservation.get("state") != "released"
        )
        if total > Decimal(str(limit)):
            invalid_reservations += 1

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

    non_decisive_ids = {
        str(event["payload"].get("match_id"))
        for event in events
        if event["event_type"] == "MatchEvaluated"
        and event["payload"].get("decision") != "decisive"
    }
    persisted_non_decisive_updates = sum(
        event["event_type"] == "RatingUpdated"
        and str(event["payload"].get("match_id")) in non_decisive_ids
        for event in events
    )
    projected_matches = (
        read_model.matches(run_id)
        if cross_epoch == 0 and persisted_non_decisive_updates == 0
        else []
    )
    non_decisive_rating_updates = sum(
        bool(match["rating_updated"])
        for match in projected_matches
        if match["decision"] != "decisive"
    ) + persisted_non_decisive_updates

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

    checkpoint_events: dict[str, list[dict[str, Any]]] = {}
    stop_without_checkpoint = 0
    for event in events:
        if event["event_type"] != "ConvergenceCheckpointRecorded":
            continue
        checkpoint_id = event["payload"].get("checkpoint_id")
        if not isinstance(checkpoint_id, str) or not checkpoint_id:
            stop_without_checkpoint += 1
            continue
        checkpoint_events.setdefault(checkpoint_id, []).append(event)
    checkpoints = {
        checkpoint_id: records[0]
        for checkpoint_id, records in checkpoint_events.items()
        if len(records) == 1
        and records[0]["payload"].get("run_id") == run_id
        and records[0]["payload"].get("source_sequence")
        == records[0]["sequence"] - 1
    }
    for checkpoint_id, records in checkpoint_events.items():
        event = records[0]
        if (
            len(records) != 1
            or event["payload"].get("run_id") != run_id
            or event["payload"].get("source_sequence") != event["sequence"] - 1
        ):
            stop_without_checkpoint += 1

    signals_by_checkpoint: dict[str, list[dict[str, Any]]] = {}
    triggers_by_checkpoint: dict[str, list[dict[str, Any]]] = {}
    stopping_by_checkpoint: dict[str, list[dict[str, Any]]] = {}
    requests_by_checkpoint: dict[str, list[dict[str, Any]]] = {}
    controls_by_type = {
        "StopSignalObserved": signals_by_checkpoint,
        "StopPolicyTriggered": triggers_by_checkpoint,
        "RunStopping": stopping_by_checkpoint,
        "FinalizationRequested": requests_by_checkpoint,
    }
    for event in events:
        event_type = event["event_type"]
        destination = controls_by_type.get(event_type)
        if destination is None:
            continue
        checkpoint_id = event["payload"].get("checkpoint_id")
        if isinstance(checkpoint_id, str) and checkpoint_id:
            destination.setdefault(checkpoint_id, []).append(event)

    cancellations = [event for event in events if event["event_type"] == "RunCancelled"]
    valid_finalization_control_sequences: set[int] = set()
    valid_soft_signal_sequences: set[int] = set()
    for checkpoint_id, checkpoint in checkpoints.items():
        signals = signals_by_checkpoint.get(checkpoint_id, [])
        triggers = triggers_by_checkpoint.get(checkpoint_id, [])
        stopping_events = stopping_by_checkpoint.get(checkpoint_id, [])
        requests = requests_by_checkpoint.get(checkpoint_id, [])
        if cancellations or not (
            len(triggers) == len(stopping_events) == len(requests) == 1
        ):
            continue
        trigger = triggers[0]
        stopping_event = stopping_events[0]
        request = requests[0]
        if trigger["payload"].get("checkpoint_source_sequence") != checkpoint[
            "payload"
        ].get("source_sequence"):
            continue
        control_sequences = (
            checkpoint["sequence"],
            trigger["sequence"],
            stopping_event["sequence"],
            request["sequence"],
        )
        if control_sequences != tuple(sorted(control_sequences)):
            continue
        if signals:
            if (
                len(signals) != 1
                or signals[0]["payload"].get("action") != "soft_stop"
                or checkpoint["payload"].get("stop_cause") != "scientist_stop"
                or not (
                    checkpoint["sequence"]
                    < signals[0]["sequence"]
                    < trigger["sequence"]
                )
            ):
                continue
            valid_soft_signal_sequences.add(signals[0]["sequence"])
        elif checkpoint["payload"].get("stop_cause") is not None:
            continue
        valid_finalization_control_sequences.update(control_sequences[1:])

    signals = [
        event for event in events if event["event_type"] == "StopSignalObserved"
    ]
    finalization_controls = [
        event
        for event in events
        if event["event_type"]
        in {"StopPolicyTriggered", "RunStopping", "FinalizationRequested"}
    ]
    valid_hard_signal_sequences: set[int] = set()
    if (
        len(signals) == 1
        and signals[0]["payload"].get("action") == "hard_cancel"
        and not finalization_controls
        and len(cancellations) == 1
        and events
        and events[-1]["event_type"] == "RunCancelled"
        and cancellations[0]["sequence"] == signals[0]["sequence"] + 1
    ):
        hard_checkpoint_id = signals[0]["payload"].get("checkpoint_id")
        hard_checkpoint = (
            checkpoints.get(hard_checkpoint_id)
            if isinstance(hard_checkpoint_id, str)
            else None
        )
        if (
            hard_checkpoint is not None
            and hard_checkpoint["payload"].get("stop_cause") == "scientist_stop"
            and hard_checkpoint["sequence"] < signals[0]["sequence"]
        ):
            valid_hard_signal_sequences.add(signals[0]["sequence"])

    valid_signal_sequences = (
        valid_soft_signal_sequences | valid_hard_signal_sequences
    )
    stop_without_checkpoint += sum(
        event["sequence"] not in valid_signal_sequences for event in signals
    )
    stop_without_checkpoint += sum(
        event["sequence"] not in valid_finalization_control_sequences
        for event in finalization_controls
    )

    unrecoverable_stopping = 0
    for stopping_event in (
        event for event in events if event["event_type"] == "RunStopping"
    ):
        checkpoint_id = stopping_event["payload"].get("checkpoint_id")
        requests = [
            event
            for event in events
            if event["event_type"] == "FinalizationRequested"
            and event["payload"].get("checkpoint_id") == checkpoint_id
            and event["sequence"] > stopping_event["sequence"]
        ]
        if len(requests) != 1:
            unrecoverable_stopping += 1
            continue
        task_id = requests[0]["payload"].get("task_id")
        task = tasks_by_id.get(str(task_id))
        enqueued = [
            event
            for event in events
            if event["event_type"] == "TaskEnqueued"
            and event["payload"].get("task_id") == task_id
        ]
        if (
            task is None
            or task.get("intent_type") != "finalize_run"
            or len(enqueued) != 1
            or enqueued[0]["payload"].get("payload") != task.get("payload")
        ):
            unrecoverable_stopping += 1

    terminal_indexes = [
        index
        for index, event in enumerate(events)
        if event["event_type"]
        in {"RunCompleted", "RunCompletedPartial", "RunCancelled", "RunFailed"}
    ]
    terminal_mutations = (
        len(events) - terminal_indexes[0] - 1 if terminal_indexes else 0
    )
    projected_state = "created"
    for event in events:
        projected_state = _RUN_EVENT_STATES.get(event["event_type"], projected_state)
    projection_mismatches = int(read_model.run_state(run_id) != projected_state)

    raw_anchor_sets = source_manifest.get("anchor_sets")
    anchor_members: list[Mapping[str, Any]] = []
    anchor_manifest_valid = False
    if (
        isinstance(raw_anchor_sets, list)
        and len(raw_anchor_sets) == 1
        and isinstance(raw_anchor_sets[0], Mapping)
    ):
        raw_members = raw_anchor_sets[0].get("members")
        if isinstance(raw_members, list) and raw_members:
            anchor_members = [member for member in raw_members if isinstance(member, Mapping)]
            anchor_manifest_valid = len(anchor_members) == len(raw_members)

    expected_anchor_events: list[tuple[str, dict[str, Any]]] = []
    proximity_by_id: dict[str, dict[str, Any]] = {}
    epoch_payload = events[1]["payload"] if len(events) > 1 else {}
    research_plan_version = epoch_payload.get("research_plan_version")
    if anchor_manifest_valid:
        for member in anchor_members:
            anchor_id = member.get("anchor_id")
            content = member.get("content")
            if not isinstance(anchor_id, str) or not isinstance(content, Mapping):
                anchor_manifest_valid = False
                break
            expected_anchor_events.append(
                (
                    "HypothesisContentCreated",
                    {
                        **dict(content),
                        "hypothesis_id": anchor_id,
                        "research_plan_version": research_plan_version,
                    },
                )
            )
    if anchor_manifest_valid:
        for member in anchor_members:
            evidence = member.get("evidence")
            if not isinstance(evidence, Mapping):
                anchor_manifest_valid = False
                break
            reviews = evidence.get("reviews")
            novelty = evidence.get("novelty_assessment")
            proximity = evidence.get("proximity_assessment")
            if (
                not isinstance(reviews, list)
                or not reviews
                or not all(isinstance(review, Mapping) for review in reviews)
                or not isinstance(novelty, Mapping)
                or not isinstance(proximity, Mapping)
            ):
                anchor_manifest_valid = False
                break
            expected_anchor_events.extend(
                ("ReviewCompleted", dict(review)) for review in reviews
            )
            expected_anchor_events.append(
                ("NoveltyAssessmentRecorded", dict(novelty))
            )
            edge_id = proximity.get("edge_id")
            if not isinstance(edge_id, str) or not edge_id:
                anchor_manifest_valid = False
                break
            proximity_by_id[edge_id] = dict(proximity)
    if anchor_manifest_valid:
        expected_anchor_events.extend(
            ("ProximityAssessed", payload) for payload in proximity_by_id.values()
        )

    generation_indexes = [
        index
        for index, event in enumerate(events)
        if event["event_type"] == "TaskEnqueued"
        and event["payload"].get("intent_type") == "run_generation"
    ]
    generation_index = generation_indexes[0] if len(generation_indexes) == 1 else None
    anchor_prefix: list[tuple[str, dict[str, Any]]] = []
    generation_event: dict[str, Any] | None = None
    bootstrap_sequences_valid = False
    if generation_index is not None:
        anchor_prefix = [
            (event["event_type"], event["payload"])
            for event in events[2:generation_index]
        ]
        generation_event = events[generation_index]
        bootstrap_sequences_valid = [
            event["sequence"] for event in events[: generation_index + 1]
        ] == list(range(1, generation_index + 2))
    bootstrap_bypass = int(
        len(events) < 3
        or not anchor_manifest_valid
        or [event["event_type"] for event in events[:2]]
        != ["RunStarted", "TournamentEpochOpened"]
        or [event["sequence"] for event in events[:2]] != [1, 2]
        or generation_event is None
        or not bootstrap_sequences_valid
        or anchor_prefix != expected_anchor_events
        or generation_event["payload"].get("created_by") != "supervisor"
        or generation_event["payload"].get("run_id") != run_id
    )

    completion_indexes = [
        index
        for index, event in enumerate(events)
        if event["event_type"] in {"RunCompleted", "RunCompletedPartial"}
    ]
    completed_without_finalization = sum(
        not any(
            event["event_type"] == "FinalizationCompleted"
            for event in events[:terminal_index]
        )
        for terminal_index in completion_indexes
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
    violation_counts = (
        stale_lease_accepted,
        calls_without_reservation,
        invalid_reservations,
        stop_without_checkpoint,
        unrecoverable_stopping,
        terminal_mutations,
        projection_mismatches,
        bootstrap_bypass,
        agent_created_tasks,
        cross_epoch,
        non_decisive_rating_updates,
        proximity_derived_novelty,
        completed_without_finalization,
        parsed_without_raw,
    )
    return CoreReleaseReport(
        persisted_task_count=len(tasks),
        external_call_count=len(calls),
        match_count=sum(event["event_type"] == "MatchEvaluated" for event in events),
        violation_count=sum(violation_counts),
        stale_lease_accepted_count=stale_lease_accepted,
        external_call_without_reservation_count=calls_without_reservation,
        invalid_budget_reservation_count=invalid_reservations,
        stop_without_valid_checkpoint_count=stop_without_checkpoint,
        unrecoverable_stopping_count=unrecoverable_stopping,
        terminal_mutation_count=terminal_mutations,
        projection_mismatch_count=projection_mismatches,
        bootstrap_epoch_bypass_count=bootstrap_bypass,
        agent_created_task_count=agent_created_tasks,
        cross_epoch_elo_comparison_count=cross_epoch,
        non_decisive_rating_update_count=non_decisive_rating_updates,
        proximity_derived_novelty_count=proximity_derived_novelty,
        run_completed_without_finalization_count=completed_without_finalization,
        raw_parsed_before_persist_count=parsed_without_raw,
    )
