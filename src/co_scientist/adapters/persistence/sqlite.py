"""SQLite-backed event store and transactional domain unit of work."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    func,
    select,
    update,
)
from sqlalchemy import (
    event as sqlalchemy_event,
)
from sqlalchemy.engine import Engine
from sqlalchemy.engine.cursor import CursorResult
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from co_scientist.adapters.persistence.migrations import execution_contract_diagnostic
from co_scientist.domain.bayesian_ranking import UCBPairingPolicy
from co_scientist.domain.budget import (
    BudgetEstimate,
    BudgetPolicy,
    BudgetUsage,
    CostEntry,
    DurableBudgetSnapshot,
    add_budget_usage,
)
from co_scientist.domain.probe_execution import probe_envelope_for_manifest
from co_scientist.domain.run_mutations import RunMutationKind, validate_run_mutation
from co_scientist.domain.states import ExternalCallState, RunState, TaskState
from co_scientist.domain.task import (
    ClaimedTask,
    ClaimOutcome,
    LeaseRecovery,
    NewTask,
    TaskLeaseFence,
    TaskMutation,
    lease_fence_fingerprint,
)
from co_scientist.domain.transitions import transition_external_call
from co_scientist.domain.transitions import transition_run as validate_run_transition
from co_scientist.domain.transitions import transition_task as validate_task_transition
from co_scientist.events.contracts import (
    EVENT_SCHEMA_VERSIONS,
    PROBE_OPERATIONAL_EVENT_SCHEMA_VERSIONS,
    assert_lineage_v2_event_payload,
)
from co_scientist.events.models import DomainEvent, NewEvent
from co_scientist.ports.artifact_store import ArtifactRef
from co_scientist.ports.event_store import ConcurrencyConflict
from co_scientist.ports.external_provider import thaw_json
from co_scientist.skills.loader import resolve_core_skill_contract

_LIFECYCLE_EVENT_TARGETS = {
    "RunStarted": RunState.RUNNING,
    "RunResumed": RunState.RUNNING,
    "RunPausing": RunState.PAUSING,
    "RunPaused": RunState.PAUSED,
    "RunNeedsAttention": RunState.NEEDS_ATTENTION,
    "RunStopping": RunState.STOPPING,
    "RunCompleted": RunState.COMPLETED,
    "RunCompletedPartial": RunState.COMPLETED_PARTIAL,
    "RunFailed": RunState.FAILED,
    "RunCancelled": RunState.CANCELLED,
}

_LIFECYCLE_TRANSITION_EVENTS = {
    (RunState.CREATED, RunState.RUNNING): "RunStarted",
    (RunState.PAUSED, RunState.RUNNING): "RunResumed",
    (RunState.NEEDS_ATTENTION, RunState.RUNNING): "RunResumed",
    (RunState.RUNNING, RunState.PAUSING): "RunPausing",
    (RunState.PAUSING, RunState.PAUSED): "RunPaused",
    (RunState.RUNNING, RunState.NEEDS_ATTENTION): "RunNeedsAttention",
    (RunState.RUNNING, RunState.STOPPING): "RunStopping",
    (RunState.PAUSED, RunState.STOPPING): "RunStopping",
    (RunState.STOPPING, RunState.COMPLETED): "RunCompleted",
    (RunState.STOPPING, RunState.COMPLETED_PARTIAL): "RunCompletedPartial",
    (RunState.RUNNING, RunState.FAILED): "RunFailed",
    (RunState.CREATED, RunState.CANCELLED): "RunCancelled",
    (RunState.RUNNING, RunState.CANCELLED): "RunCancelled",
    (RunState.PAUSING, RunState.CANCELLED): "RunCancelled",
    (RunState.PAUSED, RunState.CANCELLED): "RunCancelled",
    (RunState.NEEDS_ATTENTION, RunState.CANCELLED): "RunCancelled",
}


class Base(DeclarativeBase):
    """Declarative metadata shared with Alembic."""


class RunRow(Base):
    __tablename__ = "runs"

    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    state: Mapped[str] = mapped_column(String, nullable=False)
    current_sequence: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    manifest_json: Mapped[str] = mapped_column(Text, nullable=False)


class EventRow(Base):
    __tablename__ = "events"

    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    causation_id: Mapped[str | None] = mapped_column(String, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String, nullable=True)

    def to_domain(self) -> DomainEvent:
        occurred_at = self.occurred_at
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=UTC)
        return DomainEvent(
            sequence=self.sequence,
            run_id=self.run_id,
            event_type=self.event_type,
            schema_version=self.schema_version,
            payload=json.loads(self.payload_json),
            occurred_at=occurred_at,
            causation_id=self.causation_id,
            correlation_id=self.correlation_id,
        )


class TaskRow(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("run_id", "idempotency_key", name="uq_tasks_run_id_idempotency_key"),
        UniqueConstraint("lease_token", name="uq_tasks_lease_token"),
        CheckConstraint("attempt >= 0", name="ck_tasks_attempt_non_negative"),
        CheckConstraint("max_attempts > 0", name="ck_tasks_max_attempts_positive"),
        CheckConstraint("attempt <= max_attempts", name="ck_tasks_attempt_within_max"),
        Index("ix_tasks_claimable", "run_id", "state", "intent_type", "task_id"),
        Index("ix_tasks_lease_expiry", "run_id", "state", "lease_expires_at"),
    )

    task_id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(String, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False)
    intent_type: Mapped[str] = mapped_column(String, nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String, nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String, nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3")


class ExternalCallRow(Base):
    __tablename__ = "external_calls"

    external_call_id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(String, nullable=False)
    task_id: Mapped[str] = mapped_column(String, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    model_or_tool: Mapped[str] = mapped_column(String, nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False)
    raw_artifact_ref_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    validated_artifact_ref_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_result_id: Mapped[str | None] = mapped_column(String, nullable=True)
    applied_domain_sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parent_call_id: Mapped[str | None] = mapped_column(String, nullable=True)
    provider_response_id: Mapped[str | None] = mapped_column(String, nullable=True)
    usage_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="{}")
    execution_context_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_result_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class ExternalCallMilestoneRow(Base):
    __tablename__ = "external_call_milestones"
    __table_args__ = (
        UniqueConstraint(
            "external_call_id", "milestone_version", "milestone", "source",
            name="uq_external_call_milestone_identity",
        ),
        Index(
            "ix_external_call_milestones_call_order",
            "external_call_id",
            "observation_id",
            unique=False,
        ),
    )

    observation_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String, nullable=False)
    task_id: Mapped[str] = mapped_column(String, nullable=False)
    external_call_id: Mapped[str] = mapped_column(
        ForeignKey("external_calls.external_call_id"), nullable=False
    )
    milestone_version: Mapped[int] = mapped_column(Integer, nullable=False)
    milestone: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExternalCallFailureDiagnosticRow(Base):
    __tablename__ = "external_call_failure_diagnostics"
    __table_args__ = (
        UniqueConstraint(
            "external_call_id", "capture_layer",
            name="uq_external_call_failure_diagnostic_layer",
        ),
    )

    diagnostic_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_call_id: Mapped[str] = mapped_column(
        ForeignKey("external_calls.external_call_id"), nullable=False
    )
    run_id: Mapped[str] = mapped_column(String, nullable=False)
    task_id: Mapped[str] = mapped_column(String, nullable=False)
    capture_layer: Mapped[str] = mapped_column(String, nullable=False)
    schema_id: Mapped[str] = mapped_column(String, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    diagnostic_json: Mapped[str] = mapped_column(Text, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CostEntryRow(Base):
    __tablename__ = "cost_entries"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "external_call_id",
            name="uq_cost_entries_run_id_external_call_id",
        ),
    )

    cost_entry_id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(String, nullable=False)
    external_call_id: Mapped[str] = mapped_column(String, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cost_usd: Mapped[str] = mapped_column(String, nullable=False, server_default="0")
    pricing_version: Mapped[str] = mapped_column(String, nullable=False)


class BudgetReservationRow(Base):
    __tablename__ = "budget_reservations"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "idempotency_key",
            name="uq_budget_reservations_run_id_idempotency_key",
        ),
        UniqueConstraint("run_id", "task_id", name="uq_budget_reservations_run_id_task_id"),
        UniqueConstraint(
            "run_id",
            "external_call_id",
            name="uq_budget_reservations_run_id_external_call_id",
        ),
        CheckConstraint(
            "state IN ('reserved', 'settled', 'released')",
            name="ck_budget_reservations_state",
        ),
        CheckConstraint(
            "estimated_model_calls >= 0 AND estimated_input_tokens >= 0 "
            "AND estimated_output_tokens >= 0 "
            "AND CAST(estimated_cost_usd AS NUMERIC) >= 0 "
            "AND estimated_hypotheses >= 0 AND estimated_matches >= 0",
            name="ck_budget_reservations_estimates_non_negative",
        ),
        CheckConstraint(
            "actual_model_calls >= 0 AND actual_input_tokens >= 0 "
            "AND actual_output_tokens >= 0 AND CAST(actual_cost_usd AS NUMERIC) >= 0 "
            "AND actual_hypotheses >= 0 AND actual_matches >= 0",
            name="ck_budget_reservations_actuals_non_negative",
        ),
        CheckConstraint("version > 0", name="ck_budget_reservations_version_positive"),
        CheckConstraint(
            "state = 'settled' OR (actual_model_calls = 0 AND actual_input_tokens = 0 "
            "AND actual_output_tokens = 0 AND CAST(actual_cost_usd AS NUMERIC) = 0 "
            "AND actual_hypotheses = 0 AND actual_matches = 0)",
            name="ck_budget_reservations_state_consistency",
        ),
        Index("ix_budget_reservations_run_state", "run_id", "state"),
        Index("ix_budget_reservations_task", "task_id"),
    )

    reservation_id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.run_id", name="fk_budget_reservations_run"), nullable=False
    )
    task_id: Mapped[str] = mapped_column(
        ForeignKey("tasks.task_id", name="fk_budget_reservations_task"), nullable=False
    )
    external_call_id: Mapped[str | None] = mapped_column(String, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False, server_default="reserved")
    estimated_model_calls: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    estimated_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    estimated_output_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    estimated_cost_usd: Mapped[str] = mapped_column(String, nullable=False, server_default="0")
    estimated_hypotheses: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    estimated_matches: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    actual_model_calls: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    actual_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    actual_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    actual_cost_usd: Mapped[str] = mapped_column(String, nullable=False, server_default="0")
    actual_hypotheses: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    actual_matches: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class IdempotencyCommitRow(Base):
    __tablename__ = "idempotency_commits"

    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String, primary_key=True)
    batch_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    first_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    last_sequence: Mapped[int] = mapped_column(Integer, nullable=False)


class CommitResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    events: tuple[DomainEvent, ...]
    last_sequence: int


class PersistedExternalCall(BaseModel):
    """External-call state required by the raw-first runtime."""

    model_config = ConfigDict(frozen=True)

    external_call_id: str
    run_id: str
    task_id: str
    task_idempotency_key: str
    attempt: int
    reservation_id: str
    request_fingerprint: str
    provider: str
    model_or_tool: str
    state: ExternalCallState
    execution_context: Mapping[str, Any] | None
    raw_artifact_ref: ArtifactRef | None = None
    validated_payload: Mapping[str, Any] | None = None
    agent_result_id: str | None = None
    agent_result: Mapping[str, Any] | None = None
    provider_response_id: str | None = None
    usage: Mapping[str, Any]
    applied_domain_sequence: int | None = None


def _json(value: Any) -> str:
    return json.dumps(
        thaw_json(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _configure_sqlite(dbapi_connection: Any, _connection_record: Any) -> None:
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


class SqliteUnitOfWork:
    """SQLite persistence boundary for events and their derived writes."""

    def __init__(self, database_url: str) -> None:
        self.engine: Engine = create_engine(database_url)
        sqlalchemy_event.listen(self.engine, "connect", _configure_sqlite)
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False)

    def create_schema(self) -> None:
        Base.metadata.create_all(self.engine)

    @staticmethod
    def _begin_immediate(session: Session) -> None:
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")

    @staticmethod
    def _current_sequence(session: Session, run_id: str) -> int:
        current = session.scalar(
            select(func.coalesce(func.max(EventRow.sequence), 0)).where(EventRow.run_id == run_id)
        )
        return int(current or 0)

    def _assert_sequence(self, session: Session, run_id: str, expected_sequence: int) -> None:
        current = self._current_sequence(session, run_id)
        if current != expected_sequence:
            raise ConcurrencyConflict(f"expected {expected_sequence}, got {current}")

    @staticmethod
    def _insert_events(
        session: Session,
        run_id: str,
        expected_sequence: int,
        events: Sequence[NewEvent],
    ) -> list[DomainEvent]:
        persisted: list[DomainEvent] = []
        for offset, new_event in enumerate(events, start=1):
            occurred_at = datetime.now(UTC)
            domain_event = DomainEvent(
                sequence=expected_sequence + offset,
                run_id=run_id,
                event_type=new_event.event_type,
                schema_version=new_event.schema_version,
                payload=new_event.model_dump(mode="json")["payload"],
                occurred_at=occurred_at,
                causation_id=new_event.causation_id,
                correlation_id=new_event.correlation_id,
            )
            session.add(
                EventRow(
                    run_id=domain_event.run_id,
                    sequence=domain_event.sequence,
                    event_type=domain_event.event_type,
                    schema_version=domain_event.schema_version,
                    payload_json=_json(domain_event.model_dump(mode="json")["payload"]),
                    occurred_at=occurred_at,
                    causation_id=domain_event.causation_id,
                    correlation_id=domain_event.correlation_id,
                )
            )
            persisted.append(domain_event)
        session.flush()
        return persisted

    @staticmethod
    def _set_run_sequence(
        session: Session, run_id: str, sequence: int, *, required: bool = False
    ) -> None:
        result = cast(
            CursorResult[Any],
            session.execute(
                update(RunRow).where(RunRow.run_id == run_id).values(current_sequence=sequence)
            ),
        )
        if required and result.rowcount != 1:
            raise KeyError(f"unknown run: {run_id}")

    @staticmethod
    def _require_run(session: Session, run_id: str) -> None:
        if session.get(RunRow, run_id) is None:
            raise KeyError(f"unknown run: {run_id}")

    @staticmethod
    def _run_state_in_transaction(session: Session, run_id: str) -> RunState:
        row = session.get(RunRow, run_id)
        if row is None:
            raise KeyError(f"unknown run: {run_id}")
        return RunState(row.state)

    @staticmethod
    def _assert_supported_new_event_version(event: NewEvent) -> None:
        supported = (EVENT_SCHEMA_VERSIONS.get(event.event_type)
                     or PROBE_OPERATIONAL_EVENT_SCHEMA_VERSIONS.get(event.event_type))
        if supported is not None and event.schema_version not in supported:
            raise ValueError(
                f"unsupported scientific event version: {event.event_type} v{event.schema_version}"
            )
        assert_lineage_v2_event_payload(event)

    def append(
        self,
        run_id: str,
        expected_sequence: int,
        events: Sequence[NewEvent],
    ) -> list[DomainEvent]:
        persisted: list[DomainEvent] = []
        if any(event.event_type in {
            "ClaimLineageTargetsFrozenV2", "ClaimLineageAppliedV2",
        } for event in events):
            raise ValueError("lineage V2 events require a fenced atomic batch")
        if any(event.event_type == "CompatibilityProbeTerminatedV1" for event in events):
            raise ValueError("probe terminal requires a validated atomic batch")
        with self.session_factory.begin() as session:
            self._begin_immediate(session)
            self._assert_sequence(session, run_id, expected_sequence)
            for event in events:
                self._assert_supported_new_event_version(event)
            if session.get(RunRow, run_id) is not None:
                self._validate_lifecycle_batch(
                    session,
                    run_id=run_id,
                    events=events,
                    target_run_state=None,
                )
            if any(event.event_type in EVENT_SCHEMA_VERSIONS for event in events):
                state = self._run_state_in_transaction(session, run_id)
                for event in events:
                    if event.event_type not in EVENT_SCHEMA_VERSIONS:
                        continue
                    validate_run_mutation(state, RunMutationKind.APPEND_SCIENTIFIC_EVENT)
            if events:
                persisted = self._insert_events(session, run_id, expected_sequence, events)
                self._set_run_sequence(session, run_id, persisted[-1].sequence)
        return persisted

    def append_new(
        self,
        run_id: str,
        expected_sequence: int,
        event_type: str,
        payload: dict[str, Any],
    ) -> DomainEvent:
        return self.append(
            run_id,
            expected_sequence,
            [NewEvent(event_type=event_type, payload=payload)],
        )[0]

    def load(self, run_id: str, after_sequence: int = 0) -> list[DomainEvent]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(EventRow)
                .where(EventRow.run_id == run_id, EventRow.sequence > after_sequence)
                .order_by(EventRow.sequence)
            ).all()
            return [row.to_domain() for row in rows]

    def run_manifest(self, run_id: str) -> dict[str, Any]:
        """Load the immutable manifest frozen when the Run was created."""

        with self.session_factory() as session:
            row = session.get(RunRow, run_id)
            if row is None:
                raise KeyError(f"unknown run: {run_id}")
            manifest = json.loads(row.manifest_json)
        if not isinstance(manifest, dict):
            raise TypeError(f"Run manifest is not an object: {run_id}")
        return cast(dict[str, Any], manifest)

    def load_command_commit(
        self,
        run_id: str,
        idempotency_key: str,
    ) -> CommitResult | None:
        """Load a prior command result by its Run-scoped idempotency key."""

        with self.session_factory() as session:
            commit = session.get(IdempotencyCommitRow, (run_id, idempotency_key))
            if commit is None:
                return None
            rows = session.scalars(
                select(EventRow)
                .where(
                    EventRow.run_id == run_id,
                    EventRow.sequence >= commit.first_sequence,
                    EventRow.sequence <= commit.last_sequence,
                )
                .order_by(EventRow.sequence)
            ).all()
            return CommitResult(
                events=tuple(row.to_domain() for row in rows),
                last_sequence=commit.last_sequence,
            )

    def create_run(self, run_id: str, manifest: dict[str, Any]) -> None:
        with self.session_factory.begin() as session:
            self._begin_immediate(session)
            session.add(
                RunRow(
                    run_id=run_id,
                    state=RunState.CREATED.value,
                    current_sequence=0,
                    manifest_json=_json(manifest),
                )
            )

    def create_started_run(
        self,
        run_id: str,
        *,
        manifest: dict[str, Any],
        event: NewEvent,
        idempotency_key: str,
        additional_events: Sequence[NewEvent] = (),
        initial_tasks: Sequence[NewTask] = (),
    ) -> CommitResult:
        """Atomically create/start a Run with its initial scientific work."""

        if event.event_type != "RunStarted":
            raise ValueError("started Run initialization requires RunStarted")
        events = (event, *additional_events)
        for task in initial_tasks:
            if task.run_id != run_id:
                raise ValueError("initial task does not belong to started Run")
            if task.payload.get("output_schema_id") == "ClaimDecompositionResultV3":
                raise ValueError("V3 task requires an atomic frozen target transaction")
            validate_run_mutation(
                RunState.RUNNING,
                RunMutationKind.ENQUEUE_EXPLORATION_TASK,
                task_intent=task.intent_type,
            )
        for additional in additional_events:
            if additional.event_type in {
                "ClaimLineageTargetsFrozenV2", "ClaimLineageAppliedV2",
            }:
                raise ValueError("lineage V2 events require a fenced atomic batch")
            self._assert_supported_new_event_version(additional)
        task_events = [item for item in additional_events if item.event_type == "TaskEnqueued"]
        if [_json(item.payload) for item in task_events] != [
            _json(task.model_dump(mode="json")) for task in initial_tasks
        ]:
            raise ValueError("initial task rows and ordered TaskEnqueued events disagree")
        initialization_fingerprint = (
            "sha256:"
            + hashlib.sha256(
                _json(
                    {
                        "run_id": run_id,
                        "manifest": manifest,
                        "events": [item.model_dump(mode="json") for item in events],
                        "initial_tasks": [
                            task.model_dump(mode="json") for task in initial_tasks
                        ],
                        "idempotency_key": idempotency_key,
                    }
                ).encode("utf-8")
            ).hexdigest()
        )
        with self.session_factory.begin() as session:
            self._begin_immediate(session)
            existing_run = session.get(RunRow, run_id)
            if existing_run is not None:
                try:
                    previous = self._load_idempotency_commit(
                        session,
                        run_id,
                        idempotency_key,
                        initialization_fingerprint,
                    )
                except ValueError:
                    previous = None
                if (
                    previous is not None
                    and previous.last_sequence == len(events)
                    and existing_run.manifest_json == _json(manifest)
                    and len(previous.events) == len(events)
                    and previous.events[0].sequence == 1
                    and all(
                        persisted.event_type == requested.event_type
                        and persisted.schema_version == requested.schema_version
                        and _json(persisted.payload)
                        == _json(requested.model_dump(mode="json")["payload"])
                        for persisted, requested in zip(
                            previous.events, events, strict=True
                        )
                    )
                ):
                    return previous
                raise ValueError("run initialization conflicts with existing state")
            session.add(
                RunRow(
                    run_id=run_id,
                    state=RunState.CREATED.value,
                    current_sequence=0,
                    manifest_json=_json(manifest),
                )
            )
            session.flush()
            self._apply_run_transition(session, run_id, RunState.RUNNING)
            self._insert_followup_tasks(session, run_id, initial_tasks)
            persisted = self._insert_events(session, run_id, 0, events)
            self._insert_idempotency_commit(
                session,
                run_id,
                idempotency_key,
                initialization_fingerprint,
                persisted[0].sequence,
                persisted[-1].sequence,
            )
            self._set_run_sequence(session, run_id, persisted[-1].sequence, required=True)
            session.flush()
        return CommitResult(events=tuple(persisted), last_sequence=persisted[-1].sequence)

    @staticmethod
    def _task_row(task: NewTask) -> TaskRow:
        return TaskRow(
            task_id=task.task_id,
            run_id=task.run_id,
            idempotency_key=task.idempotency_key,
            intent_type=task.intent_type,
            state=TaskState.PENDING.value,
            payload_json=_json(task.model_dump(mode="json")["payload"]),
            attempt=0,
        )

    def enqueue_tasks(self, tasks: Sequence[NewTask]) -> None:
        with self.session_factory.begin() as session:
            self._begin_immediate(session)
            for task in tasks:
                if task.payload.get("output_schema_id") == "ClaimDecompositionResultV3":
                    raise ValueError("V3 task requires an atomic frozen target transaction")
                state = self._run_state_in_transaction(session, task.run_id)
                validate_run_mutation(
                    state,
                    (
                        RunMutationKind.ENQUEUE_FINALIZATION_TASK
                        if task.intent_type == "finalize_run"
                        else RunMutationKind.ENQUEUE_EXPLORATION_TASK
                    ),
                    task_intent=task.intent_type,
                )
            session.add_all([self._task_row(task) for task in tasks])

    @staticmethod
    def _runtime_utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        return value.astimezone(UTC)

    @staticmethod
    def _stored_utc(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    @staticmethod
    def _task_budget_estimate(row: TaskRow) -> BudgetEstimate:
        payload = json.loads(row.payload_json)
        if not isinstance(payload, dict) or "budget_estimate" not in payload:
            raise ValueError(f"task {row.task_id} has no budget_estimate")
        return BudgetEstimate.model_validate(payload["budget_estimate"])

    @staticmethod
    def _reservation_estimate(row: BudgetReservationRow) -> BudgetEstimate:
        return BudgetEstimate(
            model_calls=row.estimated_model_calls,
            input_tokens=row.estimated_input_tokens,
            output_tokens=row.estimated_output_tokens,
            cost_usd=Decimal(row.estimated_cost_usd),
            hypotheses=row.estimated_hypotheses,
            matches=row.estimated_matches,
        )

    @classmethod
    def _assert_exact_reservation(cls, task: TaskRow, reservation: BudgetReservationRow) -> None:
        if (
            reservation.idempotency_key != task.idempotency_key
            or reservation.state != "reserved"
            or cls._reservation_estimate(reservation) != cls._task_budget_estimate(task)
        ):
            raise ValueError("task reservation does not exactly replay")

    @staticmethod
    def _budget_usage(session: Session, run_id: str) -> BudgetUsage:
        usage = BudgetUsage()
        rows = session.scalars(
            select(BudgetReservationRow).where(
                BudgetReservationRow.run_id == run_id,
                BudgetReservationRow.state.in_(("reserved", "settled")),
            )
        ).all()
        for row in rows:
            if row.state == "settled":
                values = SqliteUnitOfWork._reservation_actual(row)
            else:
                values = add_budget_usage(
                    SqliteUnitOfWork._provider_usage_for_task(
                        session, run_id=row.run_id, task_id=row.task_id
                    ),
                    SqliteUnitOfWork._active_reservation_estimate(session, row),
                )
            usage = add_budget_usage(usage, values)
        return add_budget_usage(usage, SqliteUnitOfWork._continuous_retained_risk(session, run_id))

    @staticmethod
    def _budget_policy_version(policy: BudgetPolicy) -> str:
        canonical = _json(policy.model_dump(mode="json"))
        return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _reservation_actual(row: BudgetReservationRow) -> BudgetUsage:
        return BudgetUsage(
            model_calls=row.actual_model_calls,
            input_tokens=row.actual_input_tokens,
            output_tokens=row.actual_output_tokens,
            cost_usd=Decimal(row.actual_cost_usd),
            hypotheses=row.actual_hypotheses,
            matches=row.actual_matches,
        )

    @staticmethod
    def _provider_usage_for_task(
        session: Session, *, run_id: str, task_id: str
    ) -> BudgetUsage:
        """Aggregate every paid provider attempt for one logical task."""
        run = session.get(RunRow, run_id)
        manifest = json.loads(run.manifest_json) if run is not None else {}
        model_only = manifest.get("budget", {}).get("call_accounting_version") == "model-only-v2"
        from co_scientist.domain.single_root import single_root

        # New diagnostic mode counts its aggregate retrieval as retrieval, not
        # as one of the four permitted LLM calls. Historical ledgers unchanged.
        retrieval_providers: tuple[str, ...] = ("pubmed:search", "pubmed:summary", "replay_pubmed:search", "replay_pubmed:summary")
        if single_root(manifest) or manifest.get("effective_execution_config", {}).get("continuous_policy"):
            retrieval_providers += ("pubmed:root",)
        rows = session.execute(
            select(CostEntryRow)
            .join(
                ExternalCallRow,
                ExternalCallRow.external_call_id == CostEntryRow.external_call_id,
            )
            .where(
                CostEntryRow.run_id == run_id,
                ExternalCallRow.run_id == run_id,
                ExternalCallRow.task_id == task_id,
                ExternalCallRow.provider.not_in(retrieval_providers) if model_only else True,
            )
            .order_by(CostEntryRow.cost_entry_id)
        ).scalars().all()
        return BudgetUsage(
            model_calls=len(rows),
            input_tokens=sum(row.input_tokens for row in rows),
            output_tokens=sum(row.output_tokens for row in rows),
            cost_usd=sum((Decimal(row.cost_usd) for row in rows), start=Decimal(0)),
        )

    @staticmethod
    def _active_reservation_estimate(
        session: Session, reservation: BudgetReservationRow
    ) -> BudgetEstimate:
        """Return only work that is still reserved but not durably consumed."""

        task = session.get(TaskRow, reservation.task_id)
        if task is None:
            raise ValueError(
                f"budget reservation {reservation.reservation_id} has no persisted task"
            )
        current_attempt_paid = False
        if reservation.external_call_id is not None:
            call = session.get(ExternalCallRow, reservation.external_call_id)
            if call is None:
                raise ValueError("budget reservation points at an unknown external call")
            current_attempt_paid = bool(
                call.attempt == task.attempt
                and session.scalar(
                    select(func.count())
                    .select_from(CostEntryRow)
                    .where(CostEntryRow.external_call_id == call.external_call_id)
                )
            )
        paid_usage = SqliteUnitOfWork._provider_usage_for_task(
            session, run_id=reservation.run_id, task_id=reservation.task_id
        )
        provider_attempt_reserved = paid_usage.model_calls == 0 or (
            TaskState(task.state) in {TaskState.LEASED, TaskState.RUNNING}
            and not current_attempt_paid
        )
        estimate = SqliteUnitOfWork._reservation_estimate(reservation)
        return BudgetEstimate(
            model_calls=estimate.model_calls if provider_attempt_reserved else 0,
            input_tokens=estimate.input_tokens if provider_attempt_reserved else 0,
            output_tokens=estimate.output_tokens if provider_attempt_reserved else 0,
            cost_usd=estimate.cost_usd if provider_attempt_reserved else Decimal(0),
            hypotheses=estimate.hypotheses,
            matches=estimate.matches,
        )

    @staticmethod
    def _retry_provider_estimate(estimate: BudgetEstimate) -> BudgetEstimate:
        return BudgetEstimate(
            model_calls=estimate.model_calls,
            input_tokens=estimate.input_tokens,
            output_tokens=estimate.output_tokens,
            cost_usd=estimate.cost_usd,
        )

    @classmethod
    def _load_budget_snapshot(
        cls,
        session: Session,
        run_id: str,
        *,
        exclude_task_intent: str | None = None,
    ) -> DurableBudgetSnapshot:
        run = session.get(RunRow, run_id)
        if run is None:
            raise KeyError(f"unknown run: {run_id}")
        manifest = json.loads(run.manifest_json)
        if not isinstance(manifest, dict):
            raise TypeError(f"Run manifest is not an object: {run_id}")
        policy = BudgetPolicy.model_validate(manifest.get("budget", {}))
        settled = BudgetUsage()
        reserved = BudgetEstimate()
        reservation_ids: list[str] = []
        cost_ids: list[str] = []
        rows = session.scalars(
            select(BudgetReservationRow)
            .where(BudgetReservationRow.run_id == run_id)
            .order_by(BudgetReservationRow.reservation_id)
        ).all()
        for row in rows:
            if exclude_task_intent is not None:
                task = session.get(TaskRow, row.task_id)
                if task is None:
                    raise ValueError(
                        f"budget reservation {row.reservation_id} has no persisted task"
                    )
                if task.intent_type == exclude_task_intent:
                    continue
            if row.state == "settled":
                settled = add_budget_usage(settled, cls._reservation_actual(row))
                reservation_ids.append(row.reservation_id)
            elif row.state == "reserved":
                settled = add_budget_usage(
                    settled,
                    cls._provider_usage_for_task(
                        session, run_id=row.run_id, task_id=row.task_id
                    ),
                )
                reserved = add_budget_usage(
                    reserved, cls._active_reservation_estimate(session, row)
                )
                reservation_ids.append(row.reservation_id)
            if row.state in {"reserved", "settled"}:
                cost_ids.extend(
                    str(value)
                    for value in session.scalars(
                        select(CostEntryRow.cost_entry_id)
                        .join(
                            ExternalCallRow,
                            ExternalCallRow.external_call_id
                            == CostEntryRow.external_call_id,
                        )
                        .where(
                            CostEntryRow.run_id == run_id,
                            ExternalCallRow.run_id == run_id,
                            ExternalCallRow.task_id == row.task_id,
                        )
                    ).all()
                )
        reserved = add_budget_usage(reserved, cls._continuous_retained_risk(session, run_id))
        total = add_budget_usage(settled, reserved)
        return DurableBudgetSnapshot(
            run_id=run_id,
            policy_version=str(
                manifest.get("budget_policy_version") or cls._budget_policy_version(policy)
            ),
            settled=settled,
            actively_reserved=BudgetEstimate.model_validate(reserved.model_dump()),
            hard_limit_reached=policy.reached(total),
            source_reservation_ids=tuple(reservation_ids),
            source_cost_entry_ids=tuple(sorted(set(cost_ids))),
        )

    def load_budget_snapshot(self, run_id: str) -> DurableBudgetSnapshot:
        """Reconstruct settled and active usage from one database snapshot."""

        with self.session_factory() as session:
            return self._load_budget_snapshot(session, run_id)

    def load_checkpoint_budget_snapshot(self, run_id: str) -> DurableBudgetSnapshot:
        """Load scientific usage while excluding orchestration-only finalization work."""

        with self.session_factory() as session:
            return self._load_budget_snapshot(
                session,
                run_id,
                exclude_task_intent="finalize_run",
            )

    @staticmethod
    def _fits_budget(policy: BudgetPolicy, usage: BudgetUsage, estimate: BudgetEstimate) -> bool:
        checks = (
            (policy.max_model_calls, usage.model_calls + estimate.model_calls),
            (policy.max_input_tokens, usage.input_tokens + estimate.input_tokens),
            (policy.max_output_tokens, usage.output_tokens + estimate.output_tokens),
            (policy.max_usd, usage.cost_usd + estimate.cost_usd),
            (policy.max_hypotheses, usage.hypotheses + estimate.hypotheses),
            (policy.max_matches, usage.matches + estimate.matches),
        )
        return all(limit is None or projected <= limit for limit, projected in checks)

    @classmethod
    def _fits_retry_budget(cls, policy: BudgetPolicy, usage: BudgetUsage, estimate: BudgetEstimate) -> bool:
        # Scientific units already belong to the reservation; only provider work
        # is incremental. Unknown token/price estimates cannot reopen a spent cap.
        reached = any(limit is not None and actual >= limit for limit, actual in (
            (policy.max_model_calls, usage.model_calls), (policy.max_input_tokens, usage.input_tokens),
            (policy.max_output_tokens, usage.output_tokens), (policy.max_usd, usage.cost_usd),
        ))
        return not reached and cls._fits_budget(policy, usage, estimate)

    @staticmethod
    def _reservation_id(run_id: str, idempotency_key: str) -> str:
        digest = hashlib.sha256(f"{run_id}\0{idempotency_key}".encode()).hexdigest()
        return f"reservation-{digest}"

    def _insert_budget_reservation(
        self,
        session: Session,
        *,
        row: TaskRow,
        estimate: BudgetEstimate,
        now: datetime,
    ) -> BudgetReservationRow:
        reservation = BudgetReservationRow(
            reservation_id=self._reservation_id(row.run_id, row.idempotency_key),
            run_id=row.run_id,
            task_id=row.task_id,
            external_call_id=None,
            idempotency_key=row.idempotency_key,
            state="reserved",
            estimated_model_calls=estimate.model_calls,
            estimated_input_tokens=estimate.input_tokens,
            estimated_output_tokens=estimate.output_tokens,
            estimated_cost_usd=str(estimate.cost_usd),
            estimated_hypotheses=estimate.hypotheses,
            estimated_matches=estimate.matches,
            actual_model_calls=0,
            actual_input_tokens=0,
            actual_output_tokens=0,
            actual_cost_usd="0",
            actual_hypotheses=0,
            actual_matches=0,
            version=1,
            created_at=now,
            updated_at=now,
        )
        session.add(reservation)
        session.flush()
        return reservation

    @staticmethod
    def _claimed_task(row: TaskRow, reservation: BudgetReservationRow) -> ClaimedTask:
        if (
            row.lease_owner is None
            or row.lease_token is None
            or row.heartbeat_at is None
            or row.lease_expires_at is None
        ):
            raise ValueError(f"task {row.task_id} has an incomplete lease")
        payload = json.loads(row.payload_json)
        if not isinstance(payload, dict):
            raise TypeError(f"task payload is not an object: {row.task_id}")
        return ClaimedTask(
            run_id=row.run_id,
            task_id=row.task_id,
            lease_token=row.lease_token,
            attempt=row.attempt,
            worker_id=row.lease_owner,
            idempotency_key=row.idempotency_key,
            intent_type=row.intent_type,
            payload=payload,
            reservation_id=reservation.reservation_id,
            heartbeat_at=SqliteUnitOfWork._stored_utc(row.heartbeat_at),
            lease_expires_at=SqliteUnitOfWork._stored_utc(row.lease_expires_at),
            max_attempts=row.max_attempts,
        )

    @staticmethod
    def _require_execution_contract(row: RunRow) -> dict[str, Any]:
        manifest = json.loads(row.manifest_json)
        if not isinstance(manifest, dict):
            raise TypeError(f"Run manifest is not an object: {row.run_id}")
        diagnostic = execution_contract_diagnostic(row.run_id, manifest)
        if diagnostic is not None:
            raise ValueError(diagnostic)
        return cast(dict[str, Any], manifest)

    @staticmethod
    def _requires_explicit_output_retry(manifest: Mapping[str, Any]) -> bool:
        profile = manifest.get("profile")
        return isinstance(profile, Mapping) and profile.get("scientific_context") is True

    @staticmethod
    def _validate_claimable_lineage_task(session: Session, task: TaskRow) -> None:
        payload = json.loads(task.payload_json)
        if payload.get("output_schema_id") != "ClaimDecompositionResultV3":
            return
        from co_scientist.runtime.task_payload import WorkerTaskPayload
        from co_scientist.supervisor.lineage_event_path import (
            validate_persisted_offspring_task_v2,
        )

        events = tuple(row.to_domain() for row in session.scalars(
            select(EventRow).where(EventRow.run_id == task.run_id).order_by(EventRow.sequence)
        ).all())
        validate_persisted_offspring_task_v2(
            events=events, task=WorkerTaskPayload.model_validate(payload),
            task_id=task.task_id, run_id=task.run_id,
        )

    def claim_next_task(
        self,
        *,
        run_id: str,
        worker_id: str,
        lease_token: str,
        now: datetime,
        lease_duration: timedelta,
        allowed_intents: AbstractSet[str] | None = None,
    ) -> ClaimOutcome:
        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        now = self._runtime_utc(now)
        with self.session_factory.begin() as session:
            self._begin_immediate(session)
            run = session.get(RunRow, run_id)
            if run is None:
                raise KeyError(f"unknown run: {run_id}")
            manifest = self._require_execution_contract(run)
            state = RunState(run.state)
            if state in {
                RunState.COMPLETED,
                RunState.COMPLETED_PARTIAL,
                RunState.FAILED,
                RunState.CANCELLED,
            }:
                return ClaimOutcome(status="terminal")
            if state in {
                RunState.PAUSING,
                RunState.PAUSED,
                RunState.NEEDS_ATTENTION,
            }:
                return ClaimOutcome(status="paused")
            if state is RunState.CREATED:
                raise ValueError("run state created does not allow task claims")

            replay = session.scalar(select(TaskRow).where(TaskRow.lease_token == lease_token))
            if replay is not None:
                self._validate_claimable_lineage_task(session, replay)
                if (
                    replay.run_id != run_id
                    or replay.lease_owner != worker_id
                    or TaskState(replay.state) not in {TaskState.LEASED, TaskState.RUNNING}
                ):
                    raise ValueError("lease token already in use")
                reservation = session.scalar(
                    select(BudgetReservationRow).where(
                        BudgetReservationRow.run_id == run_id,
                        BudgetReservationRow.task_id == replay.task_id,
                    )
                )
                if reservation is None:
                    raise ValueError("leased task has no budget reservation")
                self._assert_exact_reservation(replay, reservation)
                return ClaimOutcome(status="claimed", task=self._claimed_task(replay, reservation))

            query = select(TaskRow).where(
                TaskRow.run_id == run_id,
                TaskRow.state == TaskState.PENDING.value,
            )
            if state is RunState.STOPPING:
                query = query.where(TaskRow.intent_type == "finalize_run")
            else:
                query = query.where(TaskRow.intent_type != "finalize_run")
            if allowed_intents is not None:
                if not allowed_intents:
                    return ClaimOutcome(
                        status=(
                            "stopping_no_finalization" if state is RunState.STOPPING else "no_task"
                        )
                    )
                query = query.where(TaskRow.intent_type.in_(sorted(allowed_intents)))
            task = session.scalar(query.order_by(TaskRow.task_id).limit(1))
            if task is None:
                return ClaimOutcome(
                    status=("stopping_no_finalization" if state is RunState.STOPPING else "no_task")
                )

            self._validate_claimable_lineage_task(session, task)

            estimate = self._task_budget_estimate(task)
            existing_reservation = session.scalar(
                select(BudgetReservationRow).where(
                    BudgetReservationRow.run_id == run_id,
                    BudgetReservationRow.task_id == task.task_id,
                )
            )
            if existing_reservation is not None:
                self._assert_exact_reservation(task, existing_reservation)
                reservation = existing_reservation
                prior = (session.get(ExternalCallRow, reservation.external_call_id)
                         if reservation.external_call_id is not None else None)
                if (prior is not None and prior.state == ExternalCallState.VALIDATION_FAILED.value
                        and self._requires_explicit_output_retry(manifest)
                        and not self._output_retry_authorized(session, task, prior, task.attempt + 1)):
                    raise ValueError("invalid output requires an explicit retry authorization")
                paid_usage = self._provider_usage_for_task(
                    session, run_id=run_id, task_id=task.task_id
                )
                policy = BudgetPolicy.model_validate(manifest.get("budget", {}))
                retry_exceeds_budget = paid_usage.model_calls > 0 and not self._fits_retry_budget(
                    policy,
                    self._budget_usage(session, run_id),
                    self._retry_provider_estimate(estimate),
                )
                if retry_exceeds_budget:
                    if reservation.external_call_id is None:
                        raise ValueError("paid retry reservation has no external call")
                    task.state = validate_task_transition(
                        TaskState(task.state), TaskState.FAILED
                    ).value
                    current_sequence = self._current_sequence(session, run_id)
                    settlement = self._settle_budget_reservation(
                        session,
                        run_id=run_id,
                        reservation_id=reservation.reservation_id,
                        external_call_id=reservation.external_call_id,
                        events=(),
                    )
                    events = self._insert_events(
                        session,
                        run_id,
                        current_sequence,
                        (
                            NewEvent(
                                event_type="TaskRetryBudgetExhausted",
                                payload={
                                    "task_id": task.task_id,
                                    "attempts_consumed": task.attempt,
                                    "reservation_id": reservation.reservation_id,
                                },
                            ),
                            settlement,
                        ),
                    )
                    self._set_run_sequence(session, run_id, events[-1].sequence, required=True)
                    session.flush()
                    return ClaimOutcome(status="budget_exhausted")
            else:
                policy = BudgetPolicy.model_validate(manifest.get("budget", {}))
                if not self._fits_budget(policy, self._budget_usage(session, run_id), estimate):
                    return ClaimOutcome(status="budget_exhausted")

                task.state = validate_task_transition(TaskState(task.state), TaskState.LEASED).value
                task.lease_owner = worker_id
                task.lease_token = lease_token
                task.heartbeat_at = now
                task.lease_expires_at = now + lease_duration
                task.attempt += 1
                reservation = self._insert_budget_reservation(
                    session, row=task, estimate=estimate, now=now
                )

            if existing_reservation is not None:
                task.state = validate_task_transition(TaskState(task.state), TaskState.LEASED).value
                task.lease_owner = worker_id
                task.lease_token = lease_token
                task.heartbeat_at = now
                task.lease_expires_at = now + lease_duration
                task.attempt += 1

            current_sequence = self._current_sequence(session, run_id)
            events = self._insert_events(
                session,
                run_id,
                current_sequence,
                (
                    NewEvent(
                        event_type="TaskLeaseClaimed",
                        payload={
                            "task_id": task.task_id,
                            "worker_id": worker_id,
                            "lease_fence_fingerprint": lease_fence_fingerprint(
                                TaskLeaseFence(
                                    run_id=run_id,
                                    task_id=task.task_id,
                                    lease_token=lease_token,
                                    attempt=task.attempt,
                                )
                            ),
                            "attempt": task.attempt,
                            "heartbeat_at": now.isoformat(),
                            "lease_expires_at": (now + lease_duration).isoformat(),
                            "max_attempts": task.max_attempts,
                        },
                    ),
                    NewEvent(
                        event_type="BudgetReserved",
                        payload={
                            "reservation_id": reservation.reservation_id,
                            "task_id": task.task_id,
                            "idempotency_key": task.idempotency_key,
                            "estimate": estimate.model_dump(mode="json"),
                        },
                    ),
                ),
            )
            self._set_run_sequence(session, run_id, events[-1].sequence, required=True)
            session.flush()
            return ClaimOutcome(status="claimed", task=self._claimed_task(task, reservation))

    def adopt_recoverable_task(
        self,
        *,
        run_id: str,
        worker_id: str,
        lease_token: str,
        now: datetime,
        lease_duration: timedelta,
    ) -> ClaimOutcome:
        """Adopt a durable call without changing its attempt or reservation."""

        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        now = self._runtime_utc(now)
        running_durable_states = (
            ExternalCallState.DOMAIN_RAW_PERSIST_FAILED_V2.value,
            ExternalCallState.HTTP_CAPTURE_STARTED_V2.value,
            ExternalCallState.HTTP_CAPTURE_FAILED_V2.value,
            ExternalCallState.HTTP_RESPONSE_CAPTURED_V2.value,
            ExternalCallState.ACCOUNTING_INCOMPLETE_V2.value,
            ExternalCallState.STARTED.value,
            ExternalCallState.RAW_RESPONSE_PERSISTED.value,
            ExternalCallState.VALIDATED.value,
            ExternalCallState.AGENT_RESULT_SUBMITTED.value,
        )
        with self.session_factory.begin() as session:
            self._begin_immediate(session)
            run = session.get(RunRow, run_id)
            if run is None:
                raise KeyError(f"unknown run: {run_id}")
            self._require_execution_contract(run)
            state = RunState(run.state)
            if state in {
                RunState.COMPLETED,
                RunState.COMPLETED_PARTIAL,
                RunState.FAILED,
                RunState.CANCELLED,
            }:
                return ClaimOutcome(status="terminal")
            if state in {
                RunState.PAUSING,
                RunState.PAUSED,
                RunState.NEEDS_ATTENTION,
            }:
                return ClaimOutcome(status="paused")
            if state is RunState.CREATED:
                raise ValueError("run state created does not allow task adoption")
            durable_states = (
                (ExternalCallState.AGENT_RESULT_SUBMITTED.value,)
                if state is RunState.STOPPING
                else running_durable_states
            )
            if (
                session.scalar(select(TaskRow.task_id).where(TaskRow.lease_token == lease_token))
                is not None
            ):
                raise ValueError("lease token already in use")
            call_rows = session.scalars(
                select(TaskRow)
                .join(
                    ExternalCallRow,
                    (ExternalCallRow.run_id == TaskRow.run_id)
                    & (ExternalCallRow.task_id == TaskRow.task_id)
                    & (ExternalCallRow.attempt == TaskRow.attempt),
                )
                .where(
                    TaskRow.run_id == run_id,
                    TaskRow.state.in_((TaskState.RUNNING.value, TaskState.RESULT_RECEIVED.value)),
                    ExternalCallRow.state.in_(durable_states),
                )
                .order_by(TaskRow.task_id)
            ).all()
            finalization_rows = (
                session.scalars(
                    select(TaskRow)
                    .where(
                        TaskRow.run_id == run_id,
                        TaskRow.intent_type == "finalize_run",
                        TaskRow.state.in_(
                            (
                                TaskState.LEASED.value,
                                TaskState.RUNNING.value,
                                TaskState.RESULT_RECEIVED.value,
                            )
                        ),
                    )
                    .order_by(TaskRow.task_id)
                ).all()
                if state is RunState.STOPPING
                else []
            )
            from co_scientist.domain.continuous_execution import policy_for

            continuous = policy_for(json.loads(run.manifest_json)) is not None
            not_sent_rows = session.scalars(select(TaskRow).outerjoin(ExternalCallRow,
                (ExternalCallRow.task_id == TaskRow.task_id) & (ExternalCallRow.attempt == TaskRow.attempt))
                .where(TaskRow.run_id == run_id, TaskRow.intent_type != "finalize_run",
                    TaskRow.state.in_(("leased", "running")), ExternalCallRow.external_call_id.is_(None),
                    TaskRow.lease_expires_at <= now)).all() if continuous and state is RunState.RUNNING else []
            rows = sorted(
                {row.task_id: row for row in (*call_rows, *finalization_rows, *not_sent_rows)}.values(),
                key=lambda row: row.task_id,
            )
            task = next(
                (
                    row
                    for row in rows
                    if row.lease_owner == worker_id
                    or (
                        row.lease_expires_at is not None
                        and self._stored_utc(row.lease_expires_at) <= now
                    )
                ),
                None,
            )
            if task is None:
                return ClaimOutcome(status="no_task")
            reservation = self._task_reservation(
                session,
                TaskLeaseFence(
                    run_id=task.run_id,
                    task_id=task.task_id,
                    lease_token=cast(str, task.lease_token),
                    attempt=task.attempt,
                ),
            )
            self._assert_exact_reservation(task, reservation)
            call = session.scalar(
                select(ExternalCallRow).where(
                    ExternalCallRow.run_id == task.run_id,
                    ExternalCallRow.task_id == task.task_id,
                    ExternalCallRow.attempt == task.attempt,
                )
            )
            if task.intent_type == "finalize_run":
                if call is not None or reservation.external_call_id is not None:
                    raise ValueError("local finalization cannot bind an external call")
                if reservation.state != "reserved":
                    raise ValueError("finalization reservation binding is not current")
            elif task in not_sent_rows:
                if call is not None or reservation.state != "reserved":
                    raise ValueError("not-sent recovery requires an original active reservation")
            elif (
                call is None
                or reservation.external_call_id != call.external_call_id
                or reservation.state != "reserved"
            ):
                raise ValueError("external call reservation binding is not current")
            task.lease_owner = worker_id
            task.lease_token = lease_token
            task.heartbeat_at = now
            task.lease_expires_at = now + lease_duration
            event = self._insert_events(
                session,
                run_id,
                self._current_sequence(session, run_id),
                (
                    NewEvent(
                        event_type="TaskLeaseAdopted",
                        payload={
                            "task_id": task.task_id,
                            "worker_id": worker_id,
                            "attempt": task.attempt,
                            "lease_fence_fingerprint": lease_fence_fingerprint(
                                TaskLeaseFence(
                                    run_id=task.run_id,
                                    task_id=task.task_id,
                                    lease_token=lease_token,
                                    attempt=task.attempt,
                                )
                            ),
                            "lease_expires_at": task.lease_expires_at.isoformat(),
                        },
                    ),
                ),
            )[0]
            self._set_run_sequence(session, run_id, event.sequence, required=True)
            session.flush()
            return ClaimOutcome(status="claimed", task=self._claimed_task(task, reservation))

    @staticmethod
    def _fenced_task(
        session: Session,
        fence: TaskLeaseFence,
        *,
        allowed_states: AbstractSet[TaskState] = frozenset({TaskState.LEASED, TaskState.RUNNING}),
    ) -> TaskRow:
        run = session.get(RunRow, fence.run_id)
        if run is None:
            raise KeyError(f"unknown run: {fence.run_id}")
        state = RunState(run.state)
        if state in {
            RunState.COMPLETED,
            RunState.COMPLETED_PARTIAL,
            RunState.FAILED,
            RunState.CANCELLED,
        }:
            raise ValueError(f"run state {state.value} does not allow lease mutation")
        row = session.get(TaskRow, fence.task_id)
        if (
            row is None
            or row.run_id != fence.run_id
            or row.lease_token != fence.lease_token
            or row.attempt != fence.attempt
            or TaskState(row.state) not in allowed_states
        ):
            raise ValueError("stale task lease fence")
        return row

    @staticmethod
    def _task_reservation(session: Session, fence: TaskLeaseFence) -> BudgetReservationRow:
        reservation = session.scalar(
            select(BudgetReservationRow).where(
                BudgetReservationRow.run_id == fence.run_id,
                BudgetReservationRow.task_id == fence.task_id,
            )
        )
        if reservation is None:
            raise ValueError("leased task has no budget reservation")
        return reservation

    def heartbeat_task(
        self,
        *,
        fence: TaskLeaseFence,
        now: datetime,
        lease_duration: timedelta,
    ) -> ClaimedTask:
        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        now = self._runtime_utc(now)
        with self.session_factory.begin() as session:
            self._begin_immediate(session)
            row = self._fenced_task(session, fence)
            if row.lease_expires_at is None or self._stored_utc(row.lease_expires_at) <= now:
                raise ValueError("stale task lease fence")
            row.heartbeat_at = now
            row.lease_expires_at = now + lease_duration
            reservation = self._task_reservation(session, fence)
            session.flush()
            return self._claimed_task(row, reservation)

    def mark_task_running(self, *, fence: TaskLeaseFence) -> ClaimedTask:
        with self.session_factory.begin() as session:
            self._begin_immediate(session)
            row = self._fenced_task(session, fence)
            if TaskState(row.state) is TaskState.LEASED:
                row.state = validate_task_transition(TaskState(row.state), TaskState.RUNNING).value
            reservation = self._task_reservation(session, fence)
            session.flush()
            return self._claimed_task(row, reservation)

    def acknowledge_task(
        self,
        *,
        fence: TaskLeaseFence,
        target_state: TaskState | str,
    ) -> None:
        target = TaskState(target_state)
        if target not in {
            TaskState.RESULT_RECEIVED,
            TaskState.FAILED,
            TaskState.NEEDS_ATTENTION,
        }:
            raise ValueError(f"task acknowledgement does not allow {target.value}")
        with self.session_factory.begin() as session:
            self._begin_immediate(session)
            row = self._fenced_task(session, fence)
            if TaskState(row.state) is not TaskState.RUNNING:
                raise ValueError("task acknowledgement requires running lease")
            row.state = validate_task_transition(TaskState(row.state), target).value
            session.flush()

    @staticmethod
    def _output_retry_authorized(
        session: Session, task: TaskRow, call: ExternalCallRow, next_attempt: int,
    ) -> bool:
        from co_scientist.domain.continuous_execution import policy_for

        run = session.get(RunRow, task.run_id)
        if run is not None and policy_for(json.loads(run.manifest_json)) is not None:
            rows = session.scalars(select(EventRow).where(EventRow.run_id == task.run_id,
                EventRow.event_type == "ContinuousAttemptPreparedV1")).all()
            return any((p := json.loads(row.payload_json)).get("task_id") == task.task_id
                and p["external_call_id"] == call.external_call_id
                and p["authorized_attempt"] == next_attempt == call.attempt+1
                and p["task_definition"]["payload"] == json.loads(task.payload_json) for row in rows)
        authorizations = [json.loads(row.payload_json) for row in session.scalars(
            select(EventRow).where(EventRow.run_id == task.run_id,
                                   EventRow.event_type == "TaskOutputRetryRequested")
        ).all()]
        matches = [payload for payload in authorizations
                   if payload.get("task_id") == task.task_id
                   and payload.get("external_call_id") == call.external_call_id]
        if len(matches) != 1 or call.raw_artifact_ref_json is None:
            return False
        payload = matches[0]
        return (
            payload.get("retry_policy_version") == "explicit-output-retry-v1"
            and payload.get("authorized_by") == "scientist"
            and payload.get("failed_attempt") == call.attempt
            and payload.get("authorized_attempt") == next_attempt == call.attempt + 1
            and next_attempt <= task.max_attempts
            and payload.get("raw_artifact_ref") == json.loads(call.raw_artifact_ref_json)
            and payload.get("request_fingerprint") == call.request_fingerprint
        )

    def requeue_invalid_output(
        self, *, run_id: str, external_call_id: str, expected_sequence: int,
    ) -> CommitResult:
        """Atomic Supervisor command: evidence, budget, lease revocation and resume.

        One task-scoped reservation accumulates every paid attempt. This command
        neither refunds the failed response nor consumes a second call/cost row.
        The claim path checks budget again before granting a new lease.
        """
        with self.session_factory.begin() as session:
            self._begin_immediate(session)
            self._require_run(session, run_id)
            self._assert_sequence(session, run_id, expected_sequence)
            run = session.get(RunRow, run_id)
            assert run is not None
            manifest = self._require_execution_contract(run)
            if RunState(run.state) is not RunState.NEEDS_ATTENTION:
                raise ValueError("output retry requires needs_attention")
            if not self._requires_explicit_output_retry(manifest):
                raise ValueError("output retry requires a scientific-context Run")
            attention = session.scalar(select(EventRow).where(
                EventRow.run_id == run_id, EventRow.event_type == "RunNeedsAttention",
            ).order_by(EventRow.sequence.desc()).limit(1))
            reason = json.loads(attention.payload_json) if attention else {}
            call = self._external_call(session, external_call_id)
            task = session.get(TaskRow, call.task_id)
            if (call.run_id != run_id or task is None or task.run_id != run_id
                    or reason.get("reason") != "provider_output_invalid"
                    or reason.get("external_call_id") != external_call_id
                    or reason.get("task_id") != call.task_id
                    or task.state != TaskState.RUNNING.value
                    or call.state != ExternalCallState.VALIDATION_FAILED.value
                    or call.attempt != task.attempt or call.raw_artifact_ref_json is None
                    or call.validated_artifact_ref_json is not None
                    or call.agent_result_id is not None or call.agent_result_json is not None
                    or call.applied_domain_sequence is not None):
                raise ValueError("retry target is not the current unapplied invalid output")
            if task.attempt >= task.max_attempts:
                raise ValueError("task max_attempts exhausted; no additional attempt authorized")
            raw_ref = ArtifactRef.model_validate_json(call.raw_artifact_ref_json)
            context = json.loads(call.execution_context_json or "{}")
            task_payload = json.loads(task.payload_json)
            if (not task.lease_token or call.provider != task_payload.get("provider_id")
                    or call.model_or_tool != task_payload.get("model_or_tool")
                    or hashlib.sha256(_json(task_payload.get("inputs")).encode("utf-8")).hexdigest()
                    != task_payload.get("input_snapshot_hash")
                    or any(context.get(field) != task_payload.get(field) for field in (
                        "input_snapshot_hash", "prompt_hash", "skill_id", "skill_version",
                        "research_plan_version", "output_schema_id", "output_schema_version",
                    ))):
                raise ValueError("retry must preserve the frozen task contract")
            fence = TaskLeaseFence(run_id=run_id, task_id=task.task_id,
                                  attempt=task.attempt, lease_token=task.lease_token)
            reservation = self._task_reservation(session, fence)
            self._assert_exact_reservation(task, reservation)
            if (reservation.external_call_id != external_call_id
                    or context.get("run_id") != run_id or context.get("task_id") != task.task_id
                    or context.get("attempt") != task.attempt
                    or context.get("idempotency_key") != task.idempotency_key
                    or context.get("reservation_id") != reservation.reservation_id
                    or context.get("lease_fence_fingerprint") != lease_fence_fingerprint(fence)):
                raise ValueError("retry requires the current reservation and lease binding")
            cost = session.scalar(select(CostEntryRow).where(CostEntryRow.external_call_id == external_call_id))
            expected_cost = self._call_cost_entry(call)
            if (cost is None or cost.run_id != run_id
                    or cost.input_tokens != expected_cost.input_tokens
                    or cost.output_tokens != expected_cost.output_tokens
                    or Decimal(cost.cost_usd) != expected_cost.cost_usd
                    or cost.pricing_version != expected_cost.pricing_version):
                raise ValueError("failed response usage must already be accounted for")
            policy = BudgetPolicy.model_validate(manifest.get("budget", {}))
            estimate = self._retry_provider_estimate(self._task_budget_estimate(task))
            usage = self._budget_usage(session, run_id)
            if policy.max_model_calls is None or not self._fits_retry_budget(policy, usage, estimate):
                raise ValueError("retry requires a finite call budget with sufficient remaining capacity")
            authorization = NewEvent(event_type="TaskOutputRetryRequested", payload={
                "retry_policy_version": "explicit-output-retry-v1", "authorized_by": "scientist",
                "task_id": task.task_id, "external_call_id": external_call_id,
                "failed_attempt": call.attempt, "authorized_attempt": call.attempt + 1,
                "max_attempts": task.max_attempts, "reservation_id": reservation.reservation_id,
                "raw_artifact_ref": raw_ref.model_dump(mode="json"),
                "request_fingerprint": call.request_fingerprint,
                "lease_fence_fingerprint": lease_fence_fingerprint(fence),
                "budget_policy_version": self._budget_policy_version(policy),
                "budget_usage_at_authorization": usage.model_dump(mode="json"),
                "additional_estimate": estimate.model_dump(mode="json"),
            })
            task.state = validate_task_transition(TaskState(task.state), TaskState.PENDING).value
            task.lease_owner = task.lease_token = None
            task.heartbeat_at = task.lease_expires_at = None
            self._apply_run_transition(session, run_id, RunState.RUNNING)
            events = self._insert_events(session, run_id, expected_sequence, (
                authorization,
                NewEvent(event_type="TaskRequeued", payload={
                    "task_id": task.task_id, "failed_attempt": call.attempt,
                    "external_call_id": external_call_id, "reason": "explicit_output_retry",
                }),
                NewEvent(event_type="RunResumed", payload={
                    "reason": "explicit_output_retry", "external_call_id": external_call_id,
                }),
            ))
            self._set_run_sequence(session, run_id, events[-1].sequence, required=True)
            session.flush()
            return CommitResult(events=tuple(events), last_sequence=events[-1].sequence)

    def prepare_continuous_retry(self, *, fence: TaskLeaseFence, external_call_id: str,
                                 reason: str, correction: str | None, delay_seconds: float,
                                 unknown_cost: bool) -> bool:
        """Atomic new-attempt authorization for the opt-in Run policy only."""
        from co_scientist.domain.continuous_execution import policy_for

        with self.session_factory.begin() as session:
            self._begin_immediate(session)
            task = self._fenced_task(session, fence)
            run = session.get(RunRow, fence.run_id)
            assert run is not None
            manifest = json.loads(run.manifest_json)
            policy = policy_for(manifest)
            if policy is None:
                raise ValueError("continuous retry is not authorized")
            call = self._external_call(session, external_call_id)
            retrieval_retry = reason in {"RETRIEVAL_TRANSIENT", "RETRIEVAL_UNKNOWN"} and call.provider == "pubmed:root"
            if (call.task_id != task.task_id or call.attempt != task.attempt
                    or call.provider not in {"deepseek", "openai", "pubmed:root"}
                    or call.applied_domain_sequence is not None
                    or call.agent_result_id is not None and not retrieval_retry):
                raise ValueError("retry cannot duplicate scientific application")
            if reason not in {"OUTPUT_LENGTH", "INVALID_JSON", "SCHEMA", "SOURCE_COVERAGE",
                              "TRANSIENT_HTTP", "DELIVERY_UNKNOWN", "NOT_SENT", "RETRIEVAL_TRANSIENT", "RETRIEVAL_UNKNOWN"}:
                return False
            prior = [json.loads(row.payload_json) for row in session.scalars(select(EventRow).where(
                EventRow.run_id == fence.run_id, EventRow.event_type == "ContinuousAttemptPreparedV1"))]
            if (task.attempt >= min(task.max_attempts, policy.max_attempts)
                    or len([p for p in prior if not p["reason"].startswith("RETRIEVAL_")]) >= policy.max_retry_dispatches and not retrieval_retry
                    or len([p for p in prior if p["reason"].startswith("RETRIEVAL_")]) >= policy.max_retrieval_retry_attempts and retrieval_retry
                    or reason in {"DELIVERY_UNKNOWN", "RETRIEVAL_UNKNOWN"} and any(p["task_id"] == task.task_id
                        and p["reason"] == reason for p in prior)):
                return False
            reservation = self._task_reservation(session, fence)
            self._assert_exact_reservation(task, reservation)
            estimate = self._retry_provider_estimate(self._task_budget_estimate(task))
            usage = self._budget_usage(session, fence.run_id)
            if not self._fits_retry_budget(BudgetPolicy.model_validate(manifest["budget"]), usage, estimate):
                return False
            payload = json.loads(task.payload_json)
            scientific_hash = hashlib.sha256(_json(payload["inputs"]["model_input"]).encode()).hexdigest()
            parameters = dict(payload["inputs"].get("continuous_attempt", {}))
            parameters.update(previous_call_id=call.external_call_id, reason=reason,
                correction=correction, not_before=(datetime.now(UTC)+timedelta(seconds=delay_seconds)).isoformat(),
                length_failures=parameters.get("length_failures", 0)+(reason == "OUTPUT_LENGTH"))
            payload["inputs"]["continuous_attempt"] = parameters
            payload["inputs"]["ideation_task_binding"]["attempt"] = task.attempt+1
            payload["input_snapshot_hash"] = hashlib.sha256(_json(payload["inputs"]).encode()).hexdigest()
            definition = NewTask(task_id=task.task_id, run_id=task.run_id,
                idempotency_key=task.idempotency_key, intent_type=task.intent_type, payload=payload)
            facts = [NewEvent(event_type="ContinuousAttemptPreparedV1", payload={
                "policy_version": policy.version, "task_id": task.task_id,
                "external_call_id": external_call_id, "failed_attempt": task.attempt,
                "authorized_attempt": task.attempt+1, "reason": reason,
                "scientific_input_hash": scientific_hash, "delay_seconds": delay_seconds,
                "task_definition": definition.model_dump(mode="json"),
                "duplicate_billing_risk": reason == "DELIVERY_UNKNOWN",
                "duplicate_read_request_risk": reason == "RETRIEVAL_UNKNOWN"})]
            if unknown_cost:
                facts.append(NewEvent(event_type="ContinuousCostRiskRetainedV1", payload={
                    "task_id": task.task_id, "external_call_id": external_call_id,
                    "reservation_id": reservation.reservation_id,
                    "estimate": estimate.model_dump(mode="json"), "actual_cost": None}))
            task.payload_json = _json(payload)
            task.state = validate_task_transition(TaskState(task.state), TaskState.PENDING).value
            task.lease_owner = task.lease_token = None
            task.heartbeat_at = task.lease_expires_at = None
            events = self._insert_events(session, fence.run_id, self._current_sequence(session, fence.run_id), facts)
            self._set_run_sequence(session, fence.run_id, events[-1].sequence, required=True)
            return True

    @staticmethod
    def _continuous_retained_risk(session: Session, run_id: str) -> BudgetEstimate:
        values = BudgetEstimate()
        for row in session.scalars(select(EventRow).where(EventRow.run_id == run_id,
                EventRow.event_type == "ContinuousCostRiskRetainedV1")):
            data = json.loads(row.payload_json)
            # A later trusted original-response recovery can remove risk only
            # when its actual cost row exists; no guessed refund or zero cost.
            if session.scalar(select(CostEntryRow).where(
                    CostEntryRow.external_call_id == data["external_call_id"])) is None:
                values = add_budget_usage(values, BudgetEstimate.model_validate(data["estimate"]))
        return BudgetEstimate.model_validate(values.model_dump())

    def recover_expired_leases(
        self,
        *,
        run_id: str,
        now: datetime,
        limit: int = 100,
    ) -> tuple[LeaseRecovery, ...]:
        if limit <= 0:
            raise ValueError("recovery limit must be positive")
        now = self._runtime_utc(now)
        with self.session_factory.begin() as session:
            self._begin_immediate(session)
            run = session.get(RunRow, run_id)
            if run is None:
                raise KeyError(f"unknown run: {run_id}")
            self._require_execution_contract(run)
            run_state = RunState(run.state)
            if run_state is RunState.NEEDS_ATTENTION:
                return ()
            if run_state in {
                RunState.COMPLETED,
                RunState.COMPLETED_PARTIAL,
                RunState.FAILED,
                RunState.CANCELLED,
            }:
                raise ValueError(
                    f"run state {run_state.value} does not allow lease recovery"
                )
            rows = session.scalars(
                select(TaskRow)
                .where(
                    TaskRow.run_id == run_id,
                    TaskRow.state.in_((TaskState.LEASED.value, TaskState.RUNNING.value)),
                    TaskRow.lease_expires_at <= now,
                )
                .order_by(TaskRow.lease_expires_at, TaskRow.task_id)
                .limit(limit)
            ).all()
            recoveries: list[LeaseRecovery] = []
            new_events: list[NewEvent] = []
            for row in rows:
                action: Literal["requeued", "exhausted"]
                expired_attempt = row.attempt
                new_events.append(
                    NewEvent(
                        event_type="TaskLeaseExpired",
                        payload={
                            "task_id": row.task_id,
                            "lease_fence_fingerprint": lease_fence_fingerprint(
                                TaskLeaseFence(
                                    run_id=row.run_id,
                                    task_id=row.task_id,
                                    lease_token=cast(str, row.lease_token),
                                    attempt=expired_attempt,
                                )
                            ),
                            "attempt": expired_attempt,
                            "expired_at": now.isoformat(),
                        },
                    )
                )
                if row.attempt >= row.max_attempts:
                    expired_fence = TaskLeaseFence(
                        run_id=row.run_id,
                        task_id=row.task_id,
                        lease_token=cast(str, row.lease_token),
                        attempt=expired_attempt,
                    )
                    current_state = TaskState(row.state)
                    if current_state is TaskState.LEASED:
                        current_state = validate_task_transition(current_state, TaskState.RUNNING)
                    row.state = validate_task_transition(current_state, TaskState.FAILED).value
                    action = "exhausted"
                    new_events.append(
                        NewEvent(
                            event_type="TaskLeaseExhausted",
                            payload={
                                "task_id": row.task_id,
                                "attempt": expired_attempt,
                                "max_attempts": row.max_attempts,
                            },
                        )
                    )
                    reservation = self._task_reservation(session, expired_fence)
                    if (
                        reservation.state == "reserved"
                        and self._reservation_has_no_provider_or_scientific_effect(
                            session, reservation
                        )
                    ):
                        new_events.append(
                            self._release_budget_reservation(
                                session,
                                run_id=run_id,
                                reservation_id=reservation.reservation_id,
                                lease_fence=expired_fence,
                            )
                        )
                    elif reservation.state == "reserved":
                        if reservation.external_call_id is None:
                            raise ValueError("paid exhausted reservation has no external call")
                        new_events.append(
                            self._settle_budget_reservation(
                                session,
                                run_id=run_id,
                                reservation_id=reservation.reservation_id,
                                external_call_id=reservation.external_call_id,
                                events=(),
                            )
                        )
                else:
                    row.state = validate_task_transition(
                        TaskState(row.state), TaskState.PENDING
                    ).value
                    action = "requeued"
                    new_events.append(
                        NewEvent(
                            event_type="TaskRequeued",
                            payload={
                                "task_id": row.task_id,
                                "expired_attempt": expired_attempt,
                            },
                        )
                    )
                row.lease_owner = None
                row.lease_token = None
                row.heartbeat_at = None
                row.lease_expires_at = None
                recoveries.append(
                    LeaseRecovery(
                        task_id=row.task_id,
                        expired_attempt=expired_attempt,
                        action=action,
                    )
                )
            if new_events:
                current_sequence = self._current_sequence(session, run_id)
                events = self._insert_events(session, run_id, current_sequence, new_events)
                self._set_run_sequence(session, run_id, events[-1].sequence, required=True)
            session.flush()
            return tuple(recoveries)

    def transition_task(self, task_id: str, target_state: TaskState | str) -> None:
        target = TaskState(target_state)
        with self.session_factory.begin() as session:
            self._begin_immediate(session)
            row = session.get(TaskRow, task_id)
            if row is None:
                raise KeyError(f"unknown task: {task_id}")
            state = self._run_state_in_transaction(session, row.run_id)
            if state in {
                RunState.COMPLETED,
                RunState.COMPLETED_PARTIAL,
                RunState.FAILED,
                RunState.CANCELLED,
            }:
                raise ValueError(f"run state {state.value} does not allow task mutation")
            row.state = validate_task_transition(TaskState(row.state), target).value

    def task_state(self, task_id: str) -> str:
        with self.session_factory() as session:
            state = session.scalar(select(TaskRow.state).where(TaskRow.task_id == task_id))
        if state is None:
            raise KeyError(f"unknown task: {task_id}")
        return state

    def task_intent(self, task_id: str) -> str:
        with self.session_factory() as session:
            intent = session.scalar(select(TaskRow.intent_type).where(TaskRow.task_id == task_id))
        if intent is None:
            raise KeyError(f"unknown task: {task_id}")
        return intent

    def task_definition(self, task_id: str) -> NewTask:
        """Load the immutable Supervisor-owned task identity and payload."""

        with self.session_factory() as session:
            row = session.get(TaskRow, task_id)
            if row is None:
                raise KeyError(f"unknown task: {task_id}")
            payload = json.loads(row.payload_json)
            if not isinstance(payload, dict):
                raise TypeError(f"task payload is not an object: {task_id}")
            return NewTask(
                task_id=row.task_id,
                run_id=row.run_id,
                idempotency_key=row.idempotency_key,
                intent_type=row.intent_type,
                payload=payload,
            )

    def reservation_id_for_task(self, task_id: str) -> str:
        with self.session_factory() as session:
            reservation_id = session.scalar(
                select(BudgetReservationRow.reservation_id).where(
                    BudgetReservationRow.task_id == task_id
                )
            )
        if reservation_id is None:
            raise KeyError(f"task has no budget reservation: {task_id}")
        return str(reservation_id)

    def unresolved_task_ids(
        self, run_id: str, *, exclude_intent: str | None = None
    ) -> tuple[str, ...]:
        """Return durable work that did not reach a resolved task state."""

        resolved = (
            TaskState.SUCCEEDED.value,
            TaskState.CANCELLED.value,
        )
        with self.session_factory() as session:
            query = select(TaskRow.task_id).where(
                TaskRow.run_id == run_id,
                TaskRow.state.not_in(resolved),
            )
            if exclude_intent is not None:
                query = query.where(TaskRow.intent_type != exclude_intent)
            return tuple(str(value) for value in session.scalars(query.order_by(TaskRow.task_id)))

    def run_state(self, run_id: str) -> str:
        with self.session_factory() as session:
            state = session.scalar(select(RunRow.state).where(RunRow.run_id == run_id))
        if state is None:
            raise KeyError(f"unknown run: {run_id}")
        return state

    def plan_external_call(
        self,
        call_id: str,
        request_fingerprint: str,
        *,
        run_id: str,
        task_id: str,
        execution_context: Mapping[str, Any],
        reservation_id: str,
        fence: TaskLeaseFence,
        attempt: int | None = None,
        provider: str | None = None,
        model_or_tool: str | None = None,
        parent_call_id: str | None = None,
    ) -> None:
        with self.session_factory.begin() as session:
            self._begin_immediate(session)
            self._require_run(session, run_id)
            task = session.get(TaskRow, task_id)
            if task is None:
                raise KeyError(f"unknown task: {task_id}")
            self._assert_run_owner(
                kind="task",
                identifier=task_id,
                actual_run_id=task.run_id,
                expected_run_id=run_id,
            )
            if fence.run_id != run_id or fence.task_id != task_id:
                raise ValueError("stale task lease fence")
            resolved_attempt = fence.attempt if attempt is None else attempt
            if resolved_attempt != fence.attempt:
                raise ValueError("external call attempt does not match task lease fence")
            validate_run_mutation(
                self._run_state_in_transaction(session, run_id),
                (
                    RunMutationKind.PLAN_FINALIZATION_CALL
                    if task.intent_type == "finalize_run"
                    else RunMutationKind.PLAN_EXPLORATION_CALL
                ),
                task_intent=task.intent_type,
            )
            task = self._fenced_task(session, fence)
            context = dict(execution_context)
            resolve_core_skill_contract(
                skill_id=str(context.get("skill_id", "")),
                skill_version=str(context.get("skill_version", "")),
                output_schema_id=str(context.get("output_schema_id", "")),
            )
            if context.get("run_id") != run_id or context.get("task_id") != task_id:
                raise ValueError("execution context does not match external call ownership")
            if context.get("idempotency_key") != task.idempotency_key:
                raise ValueError("execution context does not match task idempotency key")
            context_provider = context.get("provider", "unknown")
            context_model_or_tool = context.get("model_or_tool", "unknown")
            resolved_provider = provider or str(context_provider)
            resolved_model_or_tool = model_or_tool or str(context_model_or_tool)
            if (
                context_provider != resolved_provider
                or context_model_or_tool != resolved_model_or_tool
            ):
                raise ValueError("execution context does not match external call provider")
            if (
                context.get("attempt") != fence.attempt
                or context.get("reservation_id") != reservation_id
                or context.get("lease_fence_fingerprint") != lease_fence_fingerprint(fence)
                or "lease_token" in context
            ):
                raise ValueError("execution context does not match task lease fence")
            reservation = self._task_reservation(session, fence)
            self._assert_exact_reservation(task, reservation)
            if reservation.reservation_id != reservation_id:
                raise ValueError("external call reservation does not match task lease")
            duplicate_attempt = session.scalar(
                select(ExternalCallRow).where(
                    ExternalCallRow.run_id == run_id,
                    ExternalCallRow.task_id == task_id,
                    ExternalCallRow.attempt == resolved_attempt,
                )
            )
            if duplicate_attempt is not None:
                if duplicate_attempt.external_call_id == call_id:
                    return
                raise ValueError("task attempt already has an external call")
            run = session.get(RunRow, run_id)
            assert run is not None
            manifest = self._require_execution_contract(run)
            probe = probe_envelope_for_manifest(manifest)
            if probe is not None:
                from co_scientist.runtime.lineage_workflow_contract import (
                    validate_lineage_task_identity,
                )
                from co_scientist.runtime.task_payload import WorkerTaskPayload
                from co_scientist.supervisor.lineage_event_path import (
                    validate_persisted_offspring_task_v2,
                )

                payload = WorkerTaskPayload.model_validate(json.loads(task.payload_json))
                if (resolved_provider != "deepseek"
                        or resolved_model_or_tool != probe.pricing.model
                        or payload.provider_id != resolved_provider
                        or payload.model_or_tool != resolved_model_or_tool
                        or context.get("output_schema_id") != payload.output_schema_id
                        or context.get("output_schema_version") != payload.output_schema_version
                        or context.get("prompt_hash") != payload.prompt_hash
                        or context.get("input_snapshot_hash") != payload.input_snapshot_hash
                        or payload.inputs.get("probe_execution_envelope_hash")
                        != manifest["probe_execution_envelope_hash"]
                        or resolved_attempt != 1 or parent_call_id is not None):
                    raise ValueError("probe dispatch differs from frozen task/envelope or retries")
                role = (payload.output_schema_id, payload.output_schema_version)
                if role not in {
                    ("PopulationEvolutionResultV2", 2),
                    ("ClaimDecompositionResultV3", 3),
                }:
                    raise ValueError("probe envelope forbids this provider task kind")
                prior_calls = session.scalars(select(ExternalCallRow).where(
                    ExternalCallRow.run_id == run_id,
                )).all()
                terminal = session.scalar(select(EventRow).where(
                    EventRow.run_id == run_id,
                    EventRow.event_type == "CompatibilityProbeTerminatedV1",
                ))
                if terminal is not None or len(prior_calls) >= probe.max_total_model_calls:
                    raise ValueError("probe execution is terminal or dispatch ceiling reached")
                events = tuple(row.to_domain() for row in session.scalars(
                    select(EventRow).where(EventRow.run_id == run_id).order_by(EventRow.sequence)
                ).all())
                if role == ("PopulationEvolutionResultV2", 2):
                    if prior_calls:
                        raise ValueError("probe permits only one Evolution V2 dispatch")
                    validate_lineage_task_identity(manifest, payload)
                else:
                    source_task = (session.get(TaskRow, prior_calls[0].task_id)
                                   if len(prior_calls) == 1 else None)
                    if (source_task is None
                            or prior_calls[0].state != ExternalCallState.DOMAIN_RESULT_APPLIED.value
                            or json.loads(source_task.payload_json).get("output_schema_id")
                            != "PopulationEvolutionResultV2"):
                        raise ValueError("probe B requires a successfully applied A call")
                    validate_persisted_offspring_task_v2(
                        events=events, task=payload, task_id=task_id, run_id=run_id,
                    )
                    validate_lineage_task_identity(
                        manifest, payload, durable_targets_verified=True,
                    )
            if reservation.external_call_id is not None:
                prior = session.get(ExternalCallRow, reservation.external_call_id)
                if prior is None or prior.attempt >= resolved_attempt:
                    raise ValueError("reservation is already bound to an external call")
                prior_usage = json.loads(prior.usage_json)
                from co_scientist.domain.continuous_execution import policy_for

                continuous = policy_for(manifest) is not None
                if continuous and not self._output_retry_authorized(session, task, prior, resolved_attempt):
                    raise ValueError("continuous attempt has no exact durable authorization")
                if not continuous and (prior_usage.get("response_capture_contract") == "http-response-capture-v2"
                        or "http_capture_v2" in prior_usage):
                    raise ValueError("PREVIOUS_ATTEMPT_REPLAY_REQUIRED: capture V2 forbids resend")
                run = session.get(RunRow, run_id)
                assert run is not None
                if (not continuous and prior.state == ExternalCallState.VALIDATION_FAILED.value
                        and self._requires_explicit_output_retry(json.loads(run.manifest_json))):
                    prior_context = json.loads(prior.execution_context_json or "{}")
                    if (not self._output_retry_authorized(session, task, prior, resolved_attempt)
                            or prior.request_fingerprint != request_fingerprint
                            or any(prior_context.get(key) != context.get(key) for key in (
                                "run_id", "task_id", "idempotency_key", "reservation_id",
                                "provider", "model_or_tool", "input_snapshot_hash", "prompt_hash",
                                "skill_id", "skill_version", "output_schema_id",
                                "output_schema_version", "research_plan_version",
                            )) or parent_call_id not in (None, prior.external_call_id)):
                        raise ValueError("output retry must match its authorized frozen request")
                    parent_call_id = prior.external_call_id
                if continuous:
                    parent_call_id = prior.external_call_id
            reservation.external_call_id = call_id
            reservation.version += 1
            reservation.updated_at = datetime.now(UTC)
            session.add(
                ExternalCallRow(
                    external_call_id=call_id,
                    run_id=run_id,
                    task_id=task_id,
                    attempt=resolved_attempt,
                    request_fingerprint=request_fingerprint,
                    provider=resolved_provider,
                    model_or_tool=resolved_model_or_tool,
                    state=ExternalCallState.PLANNED.value,
                    parent_call_id=parent_call_id,
                    usage_json="{}",
                    execution_context_json=_json(context),
                )
            )

    @staticmethod
    def _external_call(session: Session, call_id: str) -> ExternalCallRow:
        row = session.get(ExternalCallRow, call_id)
        if row is None:
            raise KeyError(f"unknown external call: {call_id}")
        return row

    @classmethod
    def _fenced_external_call(
        cls,
        session: Session,
        call_id: str,
        reservation_id: str,
        fence: TaskLeaseFence,
        *,
        allowed_task_states: AbstractSet[TaskState] = frozenset({TaskState.RUNNING}),
    ) -> ExternalCallRow:
        task = cls._fenced_task(session, fence, allowed_states=allowed_task_states)
        row = cls._external_call(session, call_id)
        if (
            row.run_id != fence.run_id
            or row.task_id != fence.task_id
            or row.attempt != fence.attempt
            or task.run_id != row.run_id
        ):
            raise ValueError("stale task lease fence")
        reservation = session.get(BudgetReservationRow, reservation_id)
        task_reservation = cls._task_reservation(session, fence)
        cls._assert_exact_reservation(task, task_reservation)
        if (
            reservation is None
            or reservation.reservation_id != task_reservation.reservation_id
            or reservation.run_id != row.run_id
            or reservation.task_id != row.task_id
            or reservation.external_call_id != row.external_call_id
            or reservation.state != "reserved"
        ):
            raise ValueError("external call reservation binding is not current")
        return row

    @staticmethod
    def _validate_external_call_write_state(
        session: Session, row: ExternalCallRow
    ) -> None:
        state = SqliteUnitOfWork._run_state_in_transaction(session, row.run_id)
        if state is not RunState.RUNNING:
            raise ValueError(
                f"run state {state.value} does not allow external call write"
            )

    def assert_task_fence(self, *, fence: TaskLeaseFence) -> None:
        """Validate a lease immediately before a non-database side effect."""

        with self.session_factory.begin() as session:
            self._begin_immediate(session)
            self._fenced_task(session, fence, allowed_states=frozenset({TaskState.RUNNING}))

    def assert_finalization_fence(self, *, fence: TaskLeaseFence) -> None:
        with self.session_factory.begin() as session:
            self._begin_immediate(session)
            task = self._fenced_task(
                session,
                fence,
                allowed_states=frozenset({TaskState.RESULT_RECEIVED}),
            )
            if task.intent_type != "finalize_run":
                raise ValueError("lease fence does not belong to finalization task")

    def assert_finalization_replay_fence(self, *, fence: TaskLeaseFence) -> None:
        """Validate the exact completed finalization lease without permitting mutation."""

        with self.session_factory() as session:
            task = session.get(TaskRow, fence.task_id)
            if (
                task is None
                or task.run_id != fence.run_id
                or task.intent_type != "finalize_run"
                or task.lease_token != fence.lease_token
                or task.attempt != fence.attempt
                or TaskState(task.state) is not TaskState.SUCCEEDED
            ):
                raise ValueError("stale finalization lease fence")
            reservation = self._task_reservation(session, fence)
            if reservation.state != "released":
                raise ValueError("finalization replay reservation is not released")

    def assert_external_call_fence(
        self,
        *,
        call_id: str,
        reservation_id: str,
        fence: TaskLeaseFence,
    ) -> None:
        with self.session_factory.begin() as session:
            self._begin_immediate(session)
            row = self._fenced_external_call(session, call_id, reservation_id, fence)
            self._validate_external_call_write_state(session, row)

    def transition_call(
        self,
        call_id: str,
        target_state: ExternalCallState | str,
        *,
        reservation_id: str,
        fence: TaskLeaseFence,
    ) -> None:
        target = ExternalCallState(target_state)
        with self.session_factory.begin() as session:
            self._begin_immediate(session)
            row = self._fenced_external_call(session, call_id, reservation_id, fence)
            self._validate_external_call_write_state(session, row)
            row.state = transition_external_call(ExternalCallState(row.state), target).value
            if target is ExternalCallState.VALIDATION_FAILED:
                event = self._insert_events(
                    session,
                    row.run_id,
                    self._current_sequence(session, row.run_id),
                    (
                        NewEvent(
                            event_type="ExternalCallAttemptFailed",
                            payload={
                                "external_call_id": row.external_call_id,
                                "task_id": row.task_id,
                                "attempt": row.attempt,
                                "reservation_id": reservation_id,
                                "failure_state": target.value,
                            },
                        ),
                    ),
                )[0]
                self._set_run_sequence(session, row.run_id, event.sequence, required=True)

    def external_call_state(self, call_id: str) -> str:
        with self.session_factory() as session:
            state = session.scalar(
                select(ExternalCallRow.state).where(ExternalCallRow.external_call_id == call_id)
            )
        if state is None:
            raise KeyError(f"unknown external call: {call_id}")
        return state

    def record_external_call_milestone(
        self,
        call_id: str,
        milestone: str,
        *,
        reservation_id: str,
        fence: TaskLeaseFence,
        milestone_version: int = 1,
        source: str = "bounded_transport",
    ) -> None:
        """Append one truthful, idempotent transport/external-call milestone."""

        from co_scientist.runtime.transport_observability import TransportMilestone

        allowed: tuple[str, ...] = (
            "request_constructed",
            "request_serialized",
            "bounded_transport_reserved",
            "inner_transport_entered",
            "response_headers_received",
            "response_body_complete",
            "raw_persisted",
            "usage_parsed",
        )
        if milestone_version != 1 or milestone not in allowed or source not in {
            "bounded_transport", "external_call_runner"
        }:
            raise ValueError("unsupported transport milestone contract")
        _ = cast(TransportMilestone, milestone)
        with self.session_factory.begin() as session:
            self._begin_immediate(session)
            call = self._fenced_external_call(session, call_id, reservation_id, fence)
            existing = session.scalar(
                select(ExternalCallMilestoneRow).where(
                    ExternalCallMilestoneRow.external_call_id == call_id,
                    ExternalCallMilestoneRow.milestone_version == milestone_version,
                    ExternalCallMilestoneRow.milestone == milestone,
                    ExternalCallMilestoneRow.source == source,
                )
            )
            if existing is not None:
                if existing.run_id != call.run_id or existing.task_id != call.task_id:
                    raise ValueError("transport milestone identity conflict")
                return
            session.add(
                ExternalCallMilestoneRow(
                    run_id=call.run_id,
                    task_id=call.task_id,
                    external_call_id=call.external_call_id,
                    milestone_version=milestone_version,
                    milestone=milestone,
                    source=source,
                    recorded_at=datetime.now(UTC),
                )
            )

    def record_external_call_failure_diagnostic(
        self,
        call_id: str,
        diagnostic: Mapping[str, Any],
        *,
        reservation_id: str,
        fence: TaskLeaseFence,
        capture_layer: str = "worker",
    ) -> None:
        """Persist a safe diagnostic without changing external-call state."""

        from co_scientist.runtime.transport_observability import (
            ExternalCallFailureDiagnosticV1,
            bounded_diagnostic_json,
        )

        document = dict(diagnostic)
        if capture_layer not in {"external_call_runner", "worker"}:
            raise ValueError("unsupported failure diagnostic capture layer")
        if (
            document.get("schema_id") != "ExternalCallFailureDiagnosticV1"
            or document.get("schema_version") != 1
        ):
            raise ValueError("unsupported external-call failure diagnostic")
        parsed_diagnostic = ExternalCallFailureDiagnosticV1.model_validate(document)
        encoded = bounded_diagnostic_json(parsed_diagnostic)
        with self.session_factory.begin() as session:
            self._begin_immediate(session)
            call = self._fenced_external_call(session, call_id, reservation_id, fence)
            failed_states = {
                ExternalCallState.DOMAIN_RAW_PERSIST_FAILED_V2.value,
                ExternalCallState.ACCOUNTING_INCOMPLETE_V2.value,
                ExternalCallState.HTTP_CAPTURE_FAILED_V2.value,
                ExternalCallState.FAILED_BEFORE_RESPONSE.value,
                ExternalCallState.RAW_PERSIST_FAILED.value,
                ExternalCallState.VALIDATION_FAILED.value,
                ExternalCallState.SUBMISSION_FAILED.value,
                ExternalCallState.DOMAIN_APPLY_FAILED.value,
            }
            if (capture_layer == "worker" and call.state not in failed_states) or (
                capture_layer == "external_call_runner"
                and call.state not in {ExternalCallState.STARTED.value,
                    ExternalCallState.HTTP_CAPTURE_STARTED_V2.value,
                    ExternalCallState.HTTP_RESPONSE_CAPTURED_V2.value,
                    ExternalCallState.ACCOUNTING_INCOMPLETE_V2.value,
                    ExternalCallState.HTTP_CAPTURE_FAILED_V2.value}
            ):
                raise ValueError("failure diagnostic capture does not match call lifecycle")
            existing = session.scalar(
                select(ExternalCallFailureDiagnosticRow).where(
                    ExternalCallFailureDiagnosticRow.external_call_id == call_id,
                    ExternalCallFailureDiagnosticRow.capture_layer == capture_layer,
                )
            )
            if existing is not None:
                if existing.diagnostic_json != encoded:
                    raise ValueError("external-call failure diagnostic is immutable")
                return
            session.add(
                ExternalCallFailureDiagnosticRow(
                    external_call_id=call.external_call_id,
                    run_id=call.run_id,
                    task_id=call.task_id,
                    capture_layer=capture_layer,
                    schema_id="ExternalCallFailureDiagnosticV1",
                    schema_version=1,
                    diagnostic_json=encoded,
                    recorded_at=datetime.now(UTC),
                )
            )

    def external_call_observability(self, call_id: str) -> dict[str, Any]:
        """Read milestones and diagnostic for audits; never backfills history."""

        with self.session_factory() as session:
            call = self._external_call(session, call_id)
            milestones = session.scalars(
                select(ExternalCallMilestoneRow)
                .where(ExternalCallMilestoneRow.external_call_id == call_id)
                .order_by(ExternalCallMilestoneRow.observation_id)
            ).all()
            diagnostics = session.scalars(
                select(ExternalCallFailureDiagnosticRow)
                .where(ExternalCallFailureDiagnosticRow.external_call_id == call_id)
                .order_by(ExternalCallFailureDiagnosticRow.diagnostic_id)
            ).all()
            return {
                "run_id": call.run_id,
                "task_id": call.task_id,
                "external_call_id": call_id,
                "milestones": [
                    {
                        "version": row.milestone_version,
                        "milestone": row.milestone,
                        "source": row.source,
                        "recorded_at": row.recorded_at.isoformat(),
                    }
                    for row in milestones
                ],
                "failure_diagnostics": [
                    {
                        "capture_layer": row.capture_layer,
                        "schema_id": row.schema_id,
                        "schema_version": row.schema_version,
                        "diagnostic": json.loads(row.diagnostic_json),
                    }
                    for row in diagnostics
                ],
                "failure_diagnostic": (
                    json.loads(diagnostics[-1].diagnostic_json) if diagnostics else None
                ),
            }

    def start_http_capture_v2(self, call_id: str, *, reservation_id: str,
                              fence: TaskLeaseFence) -> None:
        """Freeze the response-capture revision before any provider I/O."""
        with self.session_factory.begin() as session:
            self._begin_immediate(session)
            row = self._fenced_external_call(session, call_id, reservation_id, fence)
            self._validate_external_call_write_state(session, row)
            row.state = transition_external_call(ExternalCallState(row.state),
                ExternalCallState.HTTP_CAPTURE_STARTED_V2).value
            row.usage_json = _json({"response_capture_contract": "http-response-capture-v2"})

    def record_http_capture_v2(
        self, call_id: str, capture: Mapping[str, Any], *,
        reservation_id: str, fence: TaskLeaseFence,
    ) -> None:
        """Commit task-bound HTTP evidence and state, without a cost entry."""
        with self.session_factory.begin() as session:
            self._begin_immediate(session)
            row = self._fenced_external_call(session, call_id, reservation_id, fence)
            self._validate_external_call_write_state(session, row)
            if row.execution_context_json is None:
                raise ValueError("HTTP capture requires authoritative execution context")
            if (capture.get("version") != 2 or capture.get("request_fingerprint")
                    != row.request_fingerprint or capture.get("provider") != row.provider
                    or capture.get("model") != row.model_or_tool
                    or capture.get("attempt") != row.attempt
                    or capture.get("run_id") != row.run_id
                    or capture.get("task_id") != row.task_id
                    or capture.get("reservation_id") != reservation_id
                    or capture.get("execution_context_fingerprint") != hashlib.sha256(
                        _json(json.loads(row.execution_context_json)).encode()).hexdigest()):
                raise ValueError("HTTP capture identity mismatch")
            ref = ArtifactRef.model_validate(capture["artifact_ref"])
            if not ref.path.startswith(f"raw/{call_id}:http-v2/"):
                raise ValueError("HTTP capture artifact belongs to another call")
            existing = json.loads(row.usage_json).get("http_capture_v2")
            if existing is not None:
                if existing != dict(capture):
                    raise ValueError("immutable HTTP capture conflict")
                return
            if row.state not in {ExternalCallState.HTTP_CAPTURE_STARTED_V2.value,
                                 ExternalCallState.HTTP_CAPTURE_FAILED_V2.value}:
                raise ValueError("HTTP capture requires V2 capture-started call")
            row.usage_json = _json({"response_capture_contract": "http-response-capture-v2",
                                   "http_capture_v2": dict(capture)})
            row.state = transition_external_call(ExternalCallState(row.state),
                ExternalCallState.HTTP_RESPONSE_CAPTURED_V2).value

    def record_raw_and_transition(
        self,
        call_id: str,
        ref: ArtifactRef,
        target_state: ExternalCallState | str,
        *,
        provider_response_id: str | None = None,
        usage: Mapping[str, Any] | None = None,
        reservation_id: str,
        fence: TaskLeaseFence,
    ) -> None:
        target = ExternalCallState(target_state)
        with self.session_factory.begin() as session:
            self._begin_immediate(session)
            row = self._fenced_external_call(session, call_id, reservation_id, fence)
            self._validate_external_call_write_state(session, row)
            if row.state in {ExternalCallState.HTTP_RESPONSE_CAPTURED_V2.value,
                             ExternalCallState.DOMAIN_RAW_PERSIST_FAILED_V2.value,
                             ExternalCallState.ACCOUNTING_INCOMPLETE_V2.value}:
                accounting = dict(usage or {})
                old_capture = json.loads(row.usage_json).get("http_capture_v2")
                if (accounting.get("http_capture_v2") != old_capture
                        or type(accounting.get("input_tokens")) is not int
                        or type(accounting.get("output_tokens")) is not int
                        or accounting["input_tokens"] < 0 or accounting["output_tokens"] < 0
                        or "cost_usd" not in accounting
                        or not str(accounting.get("pricing_version", "")).startswith("estimated:")):
                    raise ValueError("captured response requires trustworthy accounting")
                cost = Decimal(str(accounting["cost_usd"]))
                if not cost.is_finite() or cost < 0:
                    raise ValueError("invalid captured response cost")
            row.raw_artifact_ref_json = ref.model_dump_json()
            row.provider_response_id = provider_response_id
            row.usage_json = _json(thaw_json(usage or {}))
            row.state = transition_external_call(ExternalCallState(row.state), target).value
            self._insert_cost_entries(session, row.run_id, (self._call_cost_entry(row),))

    def record_validated(
        self,
        call_id: str,
        payload: Mapping[str, Any],
        *,
        reservation_id: str,
        fence: TaskLeaseFence,
    ) -> None:
        with self.session_factory.begin() as session:
            self._begin_immediate(session)
            row = self._fenced_external_call(session, call_id, reservation_id, fence)
            self._validate_external_call_write_state(session, row)
            row.validated_artifact_ref_json = _json(dict(payload))
            row.state = transition_external_call(
                ExternalCallState(row.state), ExternalCallState.VALIDATED
            ).value

    @staticmethod
    def _assert_result_matches_call(
        row: ExternalCallRow,
        result_data: Mapping[str, Any],
        *,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        if row.execution_context_json is None:
            raise ValueError("external call has no persisted execution context")
        context = json.loads(row.execution_context_json)
        trace_fields = (
            "run_id",
            "task_id",
            "idempotency_key",
            "skill_id",
            "skill_version",
            "output_schema_id",
            "output_schema_version",
            "research_plan_version",
            "provider",
            "model_or_tool",
            "input_snapshot_hash",
            "prompt_hash",
            "attempt",
            "reservation_id",
            "lease_fence_fingerprint",
        )
        if result_data.get("external_call_id") != row.external_call_id or any(
            result_data.get(field) != context.get(field) for field in trace_fields
        ):
            raise ValueError("submitted result does not match external call traceability")
        raw_ref = (
            json.loads(row.raw_artifact_ref_json) if row.raw_artifact_ref_json is not None else None
        )
        if result_data.get("raw_artifact_ref") != raw_ref:
            raise ValueError("submitted result does not match external call raw artifact")
        if payload is not None and result_data.get("payload") != dict(payload):
            raise ValueError("submitted result does not match validated payload")

    def record_submitted_result(
        self,
        call_id: str,
        result: BaseModel,
        *,
        reservation_id: str,
        fence: TaskLeaseFence,
    ) -> None:
        result_data = result.model_dump(mode="json")
        result_json = _json(result_data)
        with self.session_factory.begin() as session:
            self._begin_immediate(session)
            row = self._fenced_external_call(session, call_id, reservation_id, fence)
            self._validate_external_call_write_state(session, row)
            self._assert_result_matches_call(row, result_data)
            result_id = getattr(result, "result_id", None)
            if not isinstance(result_id, str):
                raise TypeError("submitted result must have a string result_id")
            row.agent_result_id = result_id
            row.agent_result_json = result_json
            row.state = transition_external_call(
                ExternalCallState(row.state), ExternalCallState.AGENT_RESULT_SUBMITTED
            ).value

    def record_validated_and_submitted(
        self,
        call_id: str,
        payload: Mapping[str, Any],
        result: BaseModel,
        *,
        reservation_id: str,
        fence: TaskLeaseFence,
    ) -> None:
        payload_json = _json(dict(payload))
        result_data = result.model_dump(mode="json")
        result_json = _json(result_data)
        result_id = getattr(result, "result_id", None)
        if not isinstance(result_id, str):
            raise TypeError("submitted result must have a string result_id")
        with self.session_factory.begin() as session:
            self._begin_immediate(session)
            row = self._fenced_external_call(session, call_id, reservation_id, fence)
            self._validate_external_call_write_state(session, row)
            self._assert_result_matches_call(row, result_data, payload=payload)
            validated = transition_external_call(
                ExternalCallState(row.state), ExternalCallState.VALIDATED
            )
            submitted = transition_external_call(
                validated, ExternalCallState.AGENT_RESULT_SUBMITTED
            )
            row.validated_artifact_ref_json = payload_json
            row.agent_result_id = result_id
            row.agent_result_json = result_json
            row.state = submitted.value

    def get_external_call(self, call_id: str) -> PersistedExternalCall:
        with self.session_factory() as session:
            row = self._external_call(session, call_id)
            task = session.get(TaskRow, row.task_id)
            if task is None:
                raise KeyError(f"unknown task: {row.task_id}")
            self._assert_run_owner(
                kind="task",
                identifier=row.task_id,
                actual_run_id=task.run_id,
                expected_run_id=row.run_id,
            )
            reservation = session.scalar(
                select(BudgetReservationRow).where(
                    BudgetReservationRow.run_id == row.run_id,
                    BudgetReservationRow.task_id == row.task_id,
                )
            )
            if reservation is None:
                raise ValueError("external call task has no budget reservation")
            raw_ref = (
                ArtifactRef.model_validate_json(row.raw_artifact_ref_json)
                if row.raw_artifact_ref_json is not None
                else None
            )
            validated = (
                json.loads(row.validated_artifact_ref_json)
                if row.validated_artifact_ref_json is not None
                else None
            )
            result = (
                json.loads(row.agent_result_json) if row.agent_result_json is not None else None
            )
            return PersistedExternalCall(
                external_call_id=row.external_call_id,
                run_id=row.run_id,
                task_id=row.task_id,
                task_idempotency_key=task.idempotency_key,
                attempt=row.attempt,
                reservation_id=reservation.reservation_id,
                request_fingerprint=row.request_fingerprint,
                provider=row.provider,
                model_or_tool=row.model_or_tool,
                state=ExternalCallState(row.state),
                execution_context=(
                    json.loads(row.execution_context_json)
                    if row.execution_context_json is not None
                    else None
                ),
                raw_artifact_ref=raw_ref,
                validated_payload=validated,
                agent_result_id=row.agent_result_id,
                agent_result=result,
                provider_response_id=row.provider_response_id,
                usage=json.loads(row.usage_json),
                applied_domain_sequence=row.applied_domain_sequence,
            )

    def external_call_for_task_attempt(
        self, *, run_id: str, task_id: str, attempt: int
    ) -> PersistedExternalCall | None:
        """Find the one durable call identity assigned to a task attempt."""

        with self.session_factory() as session:
            call_id = session.scalar(
                select(ExternalCallRow.external_call_id).where(
                    ExternalCallRow.run_id == run_id,
                    ExternalCallRow.task_id == task_id,
                    ExternalCallRow.attempt == attempt,
                )
            )
        return None if call_id is None else self.get_external_call(call_id)

    @staticmethod
    def _assert_run_owner(
        *, kind: str, identifier: str, actual_run_id: str, expected_run_id: str
    ) -> None:
        if actual_run_id != expected_run_id:
            raise ValueError(f"{kind} {identifier} does not belong to run {expected_run_id}")

    @classmethod
    def _apply_task_mutations(
        cls,
        session: Session,
        run_id: str,
        mutations: Sequence[TaskMutation],
        *,
        source_external_call_id: str | None = None,
    ) -> None:
        for mutation in mutations:
            row = session.get(TaskRow, mutation.task_id)
            if row is None:
                raise KeyError(f"unknown task: {mutation.task_id}")
            cls._assert_run_owner(
                kind="task",
                identifier=mutation.task_id,
                actual_run_id=row.run_id,
                expected_run_id=run_id,
            )
            current = TaskState(row.state)
            if source_external_call_id is not None and current is TaskState.RUNNING:
                call = cls._external_call(session, source_external_call_id)
                if call.task_id != mutation.task_id:
                    raise ValueError("domain result task mutation does not match external call")
                current = validate_task_transition(current, TaskState.RESULT_RECEIVED)
            row.state = validate_task_transition(current, mutation.target_state).value

    @staticmethod
    def _apply_run_transition(
        session: Session,
        run_id: str,
        target_state: RunState | None,
    ) -> None:
        if target_state is None:
            return
        row = session.get(RunRow, run_id)
        if row is None:
            raise KeyError(f"unknown run: {run_id}")
        row.state = validate_run_transition(RunState(row.state), target_state).value

    def _insert_followup_tasks(
        self, session: Session, run_id: str, tasks: Sequence[NewTask]
    ) -> None:
        for task in tasks:
            self._assert_run_owner(
                kind="follow-up task",
                identifier=task.task_id,
                actual_run_id=task.run_id,
                expected_run_id=run_id,
            )
        session.add_all([self._task_row(task) for task in tasks])

    @classmethod
    def _insert_cost_entries(
        cls, session: Session, run_id: str, entries: Sequence[CostEntry]
    ) -> None:
        for entry in entries:
            cls._assert_run_owner(
                kind="cost entry",
                identifier=entry.cost_entry_id,
                actual_run_id=entry.run_id,
                expected_run_id=run_id,
            )
        session.add_all(
            [
                CostEntryRow(
                    cost_entry_id=entry.cost_entry_id,
                    run_id=entry.run_id,
                    external_call_id=entry.external_call_id,
                    input_tokens=entry.input_tokens,
                    output_tokens=entry.output_tokens,
                    cost_usd=str(entry.cost_usd),
                    pricing_version=entry.pricing_version,
                )
                for entry in entries
            ]
        )

    @staticmethod
    def _call_cost_entry(row: ExternalCallRow) -> CostEntry:
        usage = json.loads(row.usage_json)
        if not isinstance(usage, dict):
            raise TypeError("persisted external call usage is not an object")
        nested = usage.get("tokens")
        tokens = nested if isinstance(nested, dict) else {}

        def integer(value: Any) -> int:
            return value if isinstance(value, int) and not isinstance(value, bool) else 0

        return CostEntry(
            cost_entry_id=f"cost:{row.external_call_id}",
            run_id=row.run_id,
            external_call_id=row.external_call_id,
            input_tokens=integer(usage.get("input_tokens", tokens.get("input"))),
            output_tokens=integer(usage.get("output_tokens", tokens.get("output"))),
            cost_usd=Decimal(str(usage.get("cost_usd", "0"))),
            pricing_version=str(usage.get("pricing_version", "unpriced")),
        )

    @classmethod
    def _validate_cost_entries_from_calls(
        cls,
        session: Session,
        run_id: str,
        entries: Sequence[CostEntry],
    ) -> None:
        for entry in entries:
            call = cls._external_call(session, entry.external_call_id)
            cls._assert_run_owner(
                kind="external call",
                identifier=entry.external_call_id,
                actual_run_id=call.run_id,
                expected_run_id=run_id,
            )
            if entry != cls._call_cost_entry(call):
                raise ValueError("cost entry does not match persisted call usage")

    @classmethod
    def _settle_budget_reservation(
        cls,
        session: Session,
        *,
        run_id: str,
        reservation_id: str,
        external_call_id: str,
        events: Sequence[NewEvent],
    ) -> NewEvent:
        reservation = session.get(BudgetReservationRow, reservation_id)
        if (
            reservation is None
            or reservation.run_id != run_id
            or reservation.external_call_id != external_call_id
        ):
            raise ValueError("budget settlement reservation is not bound to external call")
        if reservation.state != "reserved":
            raise ValueError("budget settlement requires an active reservation")
        cost_rows = session.execute(
            select(CostEntryRow)
            .join(
                ExternalCallRow,
                ExternalCallRow.external_call_id == CostEntryRow.external_call_id,
            )
            .where(
                CostEntryRow.run_id == run_id,
                ExternalCallRow.run_id == run_id,
                ExternalCallRow.task_id == reservation.task_id,
            )
            .order_by(CostEntryRow.cost_entry_id)
        ).scalars().all()
        if not cost_rows:
            raise ValueError("budget settlement requires persisted provider cost")
        provider_actual = cls._provider_usage_for_task(
            session, run_id=run_id, task_id=reservation.task_id
        )
        actual = BudgetUsage(
            model_calls=provider_actual.model_calls,
            input_tokens=provider_actual.input_tokens,
            output_tokens=provider_actual.output_tokens,
            cost_usd=provider_actual.cost_usd,
            hypotheses=sum(event.event_type == "HypothesisContentCreated" for event in events),
            matches=sum(event.event_type == "MatchEvaluated" for event in events),
        )
        reservation.state = "settled"
        reservation.actual_model_calls = actual.model_calls
        reservation.actual_input_tokens = actual.input_tokens
        reservation.actual_output_tokens = actual.output_tokens
        reservation.actual_cost_usd = str(actual.cost_usd)
        reservation.actual_hypotheses = actual.hypotheses
        reservation.actual_matches = actual.matches
        reservation.version += 1
        reservation.updated_at = datetime.now(UTC)
        return NewEvent(
            event_type="BudgetSettled",
            payload={
                "reservation_id": reservation_id,
                "external_call_id": external_call_id,
                "actual": actual.model_dump(mode="json"),
                "source_cost_entry_ids": tuple(row.cost_entry_id for row in cost_rows),
            },
        )

    @classmethod
    def _reservation_has_no_provider_or_scientific_effect(
        cls,
        session: Session,
        reservation: BudgetReservationRow,
    ) -> bool:
        if reservation.external_call_id is None:
            return True
        calls = session.scalars(
            select(ExternalCallRow).where(
                ExternalCallRow.run_id == reservation.run_id,
                ExternalCallRow.task_id == reservation.task_id,
            )
        ).all()
        safe_states = {
            ExternalCallState.PLANNED,
            ExternalCallState.FAILED_BEFORE_RESPONSE,
        }
        return all(
            ExternalCallState(call.state) in safe_states
            and json.loads(call.usage_json).get("response_capture_contract")
                != "http-response-capture-v2"
            and "http_capture_v2" not in json.loads(call.usage_json)
            and call.raw_artifact_ref_json is None
            and call.provider_response_id is None
            for call in calls
        ) and not session.scalar(
            select(func.count())
            .select_from(CostEntryRow)
            .join(
                ExternalCallRow,
                ExternalCallRow.external_call_id == CostEntryRow.external_call_id,
            )
            .where(
                ExternalCallRow.run_id == reservation.run_id,
                ExternalCallRow.task_id == reservation.task_id,
            )
        )

    @classmethod
    def _release_budget_reservation(
        cls,
        session: Session,
        *,
        run_id: str,
        reservation_id: str,
        lease_fence: TaskLeaseFence,
    ) -> NewEvent:
        task = cls._fenced_task(
            session,
            lease_fence,
            allowed_states=frozenset(
                {
                    TaskState.RUNNING,
                    TaskState.RESULT_RECEIVED,
                    TaskState.FAILED,
                    TaskState.NEEDS_ATTENTION,
                    TaskState.CANCELLED,
                }
            ),
        )
        reservation = cls._task_reservation(session, lease_fence)
        if reservation.reservation_id != reservation_id or reservation.run_id != run_id:
            raise ValueError("budget release does not match task lease")
        if reservation.state != "reserved":
            raise ValueError("budget release requires an active reservation")
        if not cls._reservation_has_no_provider_or_scientific_effect(session, reservation):
            raise ValueError("reservation cannot release after provider or scientific effect")
        reservation.state = "released"
        reservation.version += 1
        reservation.updated_at = datetime.now(UTC)
        return NewEvent(
            event_type="BudgetReleased",
            payload={
                "reservation_id": reservation_id,
                "task_id": task.task_id,
                "reason": "no_provider_or_scientific_effect",
            },
        )

    @staticmethod
    def _insert_idempotency_commit(
        session: Session,
        run_id: str,
        idempotency_key: str,
        batch_fingerprint: str,
        first_sequence: int,
        last_sequence: int,
    ) -> None:
        session.add(
            IdempotencyCommitRow(
                run_id=run_id,
                idempotency_key=idempotency_key,
                batch_fingerprint=batch_fingerprint,
                first_sequence=first_sequence,
                last_sequence=last_sequence,
            )
        )

    @staticmethod
    def _load_idempotency_commit(
        session: Session,
        run_id: str,
        idempotency_key: str,
        batch_fingerprint: str,
    ) -> CommitResult | None:
        commit = session.get(IdempotencyCommitRow, (run_id, idempotency_key))
        if commit is None:
            return None
        if commit.batch_fingerprint != batch_fingerprint:
            raise ValueError("idempotency key reused with a different batch")
        rows = session.scalars(
            select(EventRow)
            .where(
                EventRow.run_id == run_id,
                EventRow.sequence >= commit.first_sequence,
                EventRow.sequence <= commit.last_sequence,
            )
            .order_by(EventRow.sequence)
        ).all()
        return CommitResult(
            events=tuple(row.to_domain() for row in rows),
            last_sequence=commit.last_sequence,
        )

    @staticmethod
    def _batch_fingerprint(
        *,
        events: Sequence[NewEvent],
        target_run_state: RunState | None,
        task_mutations: Sequence[TaskMutation],
        followup_tasks: Sequence[NewTask],
        external_call_id: str | None,
        reservation_id: str | None,
        lease_fence: TaskLeaseFence | None,
        settle_reservation_id: str | None,
        release_reservation_id: str | None,
        cost_entries: Sequence[CostEntry],
    ) -> str:
        canonical = _json(
            {
                "events": [event.model_dump(mode="json") for event in events],
                "target_run_state": target_run_state.value if target_run_state else None,
                "task_mutations": [mutation.model_dump(mode="json") for mutation in task_mutations],
                "followup_tasks": [task.model_dump(mode="json") for task in followup_tasks],
                "external_call_id": external_call_id,
                "reservation_id": reservation_id,
                "lease_fence_fingerprint": (
                    lease_fence_fingerprint(lease_fence) if lease_fence is not None else None
                ),
                "settle_reservation_id": settle_reservation_id,
                "release_reservation_id": release_reservation_id,
                "cost_entries": [entry.model_dump(mode="json") for entry in cost_entries],
            }
        )
        return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _mark_external_call_domain_applied(
        self,
        session: Session,
        run_id: str,
        external_call_id: str,
        sequence: int,
    ) -> None:
        row = self._external_call(session, external_call_id)
        self._assert_run_owner(
            kind="external call",
            identifier=external_call_id,
            actual_run_id=row.run_id,
            expected_run_id=run_id,
        )
        row.state = transition_external_call(
            ExternalCallState(row.state), ExternalCallState.DOMAIN_RESULT_APPLIED
        ).value
        row.applied_domain_sequence = sequence

    @classmethod
    def _validate_domain_fence(
        cls,
        session: Session,
        *,
        external_call_id: str,
        reservation_id: str,
        fence: TaskLeaseFence,
    ) -> None:
        call = cls._external_call(session, external_call_id)
        if ExternalCallState(call.state) is ExternalCallState.DOMAIN_RESULT_APPLIED:
            task = cls._fenced_task(
                session,
                fence,
                allowed_states=frozenset(
                    {TaskState.SUCCEEDED, TaskState.PENDING, TaskState.FAILED}
                ),
            )
            reservation = session.get(BudgetReservationRow, reservation_id)
            if (
                call.run_id != fence.run_id
                or call.task_id != fence.task_id
                or call.attempt != fence.attempt
                or task.run_id != call.run_id
                or reservation is None
                or reservation.run_id != fence.run_id
                or reservation.task_id != fence.task_id
                or reservation.external_call_id != external_call_id
                or reservation.state != "settled"
            ):
                raise ValueError("settled external call does not match task lease")
            return
        cls._fenced_external_call(
            session,
            external_call_id,
            reservation_id,
            fence,
            allowed_task_states=frozenset(
                {
                    TaskState.RUNNING,
                    TaskState.RESULT_RECEIVED,
                    TaskState.SUCCEEDED,
                    TaskState.PENDING,
                    TaskState.FAILED,
                }
            ),
        )
        reservation = session.get(BudgetReservationRow, reservation_id)
        if (
            reservation is None
            or reservation.run_id != fence.run_id
            or reservation.task_id != fence.task_id
            or reservation.external_call_id != external_call_id
        ):
            raise ValueError("external call reservation does not match task lease")

    def assert_domain_fence(
        self,
        *,
        external_call_id: str,
        reservation_id: str,
        fence: TaskLeaseFence,
    ) -> None:
        """Fail stale Supervisor commands before reconstructing durable results."""

        with self.session_factory.begin() as session:
            self._begin_immediate(session)
            self._validate_domain_fence(
                session,
                external_call_id=external_call_id,
                reservation_id=reservation_id,
                fence=fence,
            )

    def _validate_domain_batch_mutations(
        self,
        session: Session,
        *,
        run_id: str,
        events: Sequence[NewEvent],
        task_mutations: Sequence[TaskMutation],
        followup_tasks: Sequence[NewTask],
        external_call_id: str | None,
        cost_entries: Sequence[CostEntry],
        target_run_state: RunState | None,
    ) -> None:
        state = self._run_state_in_transaction(session, run_id)
        effective_state = target_run_state or state
        source_task_intent: str | None = None
        if external_call_id is not None:
            call = self._external_call(session, external_call_id)
            self._assert_run_owner(
                kind="external call",
                identifier=external_call_id,
                actual_run_id=call.run_id,
                expected_run_id=run_id,
            )
            if ExternalCallState(call.state) is not ExternalCallState.AGENT_RESULT_SUBMITTED:
                raise ValueError("scientific result is not durably submitted")
            task = session.get(TaskRow, call.task_id)
            if task is None:
                raise KeyError(f"unknown task: {call.task_id}")
            source_task_intent = task.intent_type
            validate_run_mutation(
                effective_state,
                RunMutationKind.APPLY_SCIENTIFIC_RESULT,
                task_intent=source_task_intent,
            )

        for event in events:
            self._assert_supported_new_event_version(event)
            if event.event_type in EVENT_SCHEMA_VERSIONS:
                validate_run_mutation(
                    effective_state,
                    RunMutationKind.APPEND_SCIENTIFIC_EVENT,
                    task_intent=source_task_intent,
                )

        for followup_task in followup_tasks:
            self._assert_run_owner(
                kind="follow-up task",
                identifier=followup_task.task_id,
                actual_run_id=followup_task.run_id,
                expected_run_id=run_id,
            )
            validate_run_mutation(
                effective_state,
                (
                    RunMutationKind.ENQUEUE_FINALIZATION_TASK
                    if followup_task.intent_type == "finalize_run"
                    else RunMutationKind.ENQUEUE_EXPLORATION_TASK
                ),
                task_intent=followup_task.intent_type,
            )

        if state is RunState.STOPPING:
            for mutation in task_mutations:
                task = session.get(TaskRow, mutation.task_id)
                if task is None:
                    raise KeyError(f"unknown task: {mutation.task_id}")
                self._assert_run_owner(
                    kind="task",
                    identifier=mutation.task_id,
                    actual_run_id=task.run_id,
                    expected_run_id=run_id,
                )
                if task.intent_type != "finalize_run" and external_call_id is None:
                    raise ValueError("run state stopping does not allow task result mutation")

        if cost_entries:
            validate_run_mutation(
                effective_state,
                RunMutationKind.RECORD_COST,
                task_intent=source_task_intent,
            )

    def _validate_lineage_v2_atomic_batch(
        self, session: Session, *, run_id: str,
        events: Sequence[NewEvent], followup_tasks: Sequence[NewTask],
        external_call_id: str | None,
    ) -> None:
        """Keep a V3 task invisible unless its exact frozen plan commits with it."""
        from co_scientist.agents.payloads import (
            ClaimDecompositionResultV3,
            PopulationEvolutionResultV2,
        )
        from co_scientist.domain.claim_lineage import (
            FrozenLineagePlanV2,
            LineageChangeProposalV2,
            RemovedParentProposalV2,
            freeze_claim_lineage_v2,
        )
        from co_scientist.domain.claim_verification import (
            ClaimDecompositionOutputPolicy,
            ClaimVerificationPolicy,
            scientific_hash,
        )
        from co_scientist.domain.hypothesis import HypothesisContent
        from co_scientist.runtime.lineage_workflow_contract import (
            validate_lineage_task_identity,
            validate_lineage_workflow_contract,
        )
        from co_scientist.runtime.task_payload import WorkerTaskPayload
        from co_scientist.supervisor.lineage_event_path import (
            durable_parent_scope_v2,
            frozen_targets_event_id_v2,
            resolve_child_decomposition_events_v2,
            validate_persisted_offspring_task_v2,
        )

        freezes = [e for e in events if e.event_type == "ClaimLineageTargetsFrozenV2"]
        applies = [e for e in events if e.event_type == "ClaimLineageAppliedV2"]
        v3_tasks = [task for task in followup_tasks
                    if task.payload.get("output_schema_id") == "ClaimDecompositionResultV3"]
        if not (freezes or applies or v3_tasks):
            return
        if len(freezes) > 1 or len(applies) > 1 or len(v3_tasks) > 1:
            raise ValueError("lineage V2 batch has duplicate freeze, application or V3 task")
        if freezes and applies:
            raise ValueError("lineage freeze and application require separate fenced results")
        run = session.get(RunRow, run_id)
        if run is None:
            raise KeyError(f"unknown run: {run_id}")
        manifest = json.loads(run.manifest_json)
        validate_lineage_workflow_contract(manifest)
        prior_rows = session.scalars(select(EventRow).where(
            EventRow.run_id == run_id).order_by(EventRow.sequence)).all()
        prior_events = tuple(row.to_domain() for row in prior_rows)
        if external_call_id is None and (freezes or applies):
            raise ValueError("lineage event requires a fenced external result")
        call = self._external_call(session, external_call_id) if external_call_id else None
        persisted_result = (json.loads(call.agent_result_json)
                            if call is not None and call.agent_result_json else None)
        if (freezes or applies) and (call is None or persisted_result is None
                                    or call.raw_artifact_ref_json is None):
            raise ValueError("lineage event requires a raw-persisted submitted result")
        if freezes:
            if len(v3_tasks) != 1:
                raise ValueError("lineage freeze requires a fenced result and atomic V3 task")
            freeze = freezes[0]
            data = freeze.payload
            plan = FrozenLineagePlanV2.model_validate(data.get("frozen_lineage_plan"))
            if data.get("frozen_lineage_plan_hash") != scientific_hash(
                plan.model_dump(mode="json")
            ):
                raise ValueError("frozen lineage plan hash mismatch")
            task = v3_tasks[0]
            payload = WorkerTaskPayload.model_validate(task.payload)
            validate_lineage_task_identity(manifest, payload, durable_targets_verified=True)
            if (payload.inputs.get("frozen_lineage_plan") != plan.model_dump(mode="json")
                    or payload.inputs.get("lineage_targets_frozen_event_id")
                    != data.get("lineage_targets_frozen_event_id")
                    or data.get("offspring_task_id") != task.task_id
                    or data.get("offspring_task_snapshot_hash") != payload.input_snapshot_hash
                    or data.get("lineage_workflow_contract_hash")
                    != payload.inputs.get("lineage_workflow_contract_hash")):
                raise ValueError("frozen lineage event and V3 task identity disagree")
            assert call is not None and persisted_result is not None
            proposal = PopulationEvolutionResultV2.model_validate(data.get("proposal_payload"))
            if not proposal.valid or proposal.child is None:
                raise ValueError("lineage freeze requires an accepted child proposal")
            raw_ref_json = call.raw_artifact_ref_json
            if raw_ref_json is None:
                raise ValueError("lineage freeze requires persisted raw response")
            if (PopulationEvolutionResultV2.model_validate(persisted_result.get("payload"))
                    != proposal
                    or persisted_result.get("result_id") != data.get("source_result_id")
                    or persisted_result.get("task_id") != data.get("source_task_id")
                    or persisted_result.get("raw_artifact_ref")
                    != json.loads(raw_ref_json)
                    or data.get("raw_artifact_ref")
                    != json.loads(raw_ref_json)
                    or call.task_id != data.get("source_task_id")):
                raise ValueError("frozen lineage proposal differs from durable raw-first result")
            if data.get("lineage_targets_frozen_event_id") != frozen_targets_event_id_v2(
                run_id=run_id, plan=plan, source_result_id=str(data["source_result_id"]),
            ):
                raise ValueError("frozen lineage event identity mismatch")
            source_task = session.get(TaskRow, call.task_id)
            if source_task is None:
                raise ValueError("lineage source task is missing")
            source_payload = WorkerTaskPayload.model_validate(json.loads(source_task.payload_json))
            validate_lineage_task_identity(manifest, source_payload)
            source_inputs = source_payload.inputs
            decisions = [event for event in prior_events
                         if event.event_type == "ParentSelectionDecisionRecorded"
                         and event.payload.get("decision_id") == proposal.selection_decision_id]
            if (len(decisions) != 1
                    or source_inputs.get("selection_decision_id")
                    != proposal.selection_decision_id
                    or tuple(source_inputs.get("parent_ids", ())) != proposal.parent_ids
                    or source_inputs.get("generation_id") != proposal.generation_id
                    or tuple(decisions[0].payload.get("chosen_parent_ids", ()))
                    != proposal.parent_ids):
                raise ValueError("frozen lineage proposal differs from durable parent selection")
            selected_hashes = source_inputs.get("parent_content_hashes")
            if not isinstance(selected_hashes, Mapping):
                raise TypeError("lineage source task has no parent content hash map")
            parents = durable_parent_scope_v2(
                events=prior_events, selected_parent_ids=proposal.parent_ids,
                selected_parent_hashes=selected_hashes,
            )
            child = HypothesisContent.model_validate(proposal.child.model_dump(mode="json"))
            expected_plan = freeze_claim_lineage_v2(
                proposal_id=proposal.proposal_id,
                generation_id=proposal.generation_id,
                child_hypothesis_id=proposal.child.hypothesis_id,
                child_content=child, parents=parents,
                changes=tuple(LineageChangeProposalV2.model_validate(
                    group.model_dump(mode="json")) for group in proposal.change_groups),
                removed_parent_proposals=tuple(RemovedParentProposalV2.model_validate(
                    item.model_dump(mode="json")) for item in proposal.removed_parent_claims),
            )
            if plan != expected_plan:
                raise ValueError("frozen lineage parent scope or targets differ from durable state")
            kinds = [event.event_type for event in events]
            required = ["HypothesisContentCreated", "OffspringHypothesisCreated",
                        "OffspringValidationStarted", "ClaimLineageTargetsFrozenV2",
                        "TaskEnqueued"]
            if any(kinds.count(kind) != 1 for kind in required) or [
                kinds.index(kind) for kind in required
            ] != sorted(kinds.index(kind) for kind in required):
                raise ValueError("child, lineage targets and V3 task must commit in order")
            content = events[kinds.index("HypothesisContentCreated")].payload
            offspring = events[kinds.index("OffspringHypothesisCreated")].payload
            start = events[kinds.index("OffspringValidationStarted")].payload
            enqueued = events[kinds.index("TaskEnqueued")].payload
            if (content.get("hypothesis_id") != plan.child_hypothesis_id
                    or content.get("content_hash") != plan.child_hypothesis_content_hash
                    or HypothesisContent.model_validate(dict(content)).content_hash
                    != plan.child_hypothesis_content_hash
                    or offspring.get("proposal_id") != plan.proposal_id
                    or offspring.get("hypothesis_id") != plan.child_hypothesis_id
                    or offspring.get("content_hash") != plan.child_hypothesis_content_hash
                    or start.get("hypothesis_id") != plan.child_hypothesis_id
                    or start.get("content_hash") != plan.child_hypothesis_content_hash
                    or thaw_json(enqueued) != task.model_dump(mode="json")):
                raise ValueError("atomic lineage child identity mismatch")
            if any(event.event_type == "ClaimLineageTargetsFrozenV2"
                   and event.payload.get("frozen_lineage_plan", {}).get("proposal_id")
                   == plan.proposal_id for event in prior_events):
                raise ValueError("proposal already has a frozen lineage target set")
        elif v3_tasks:
            raise ValueError("V3 task cannot be enqueued without an atomic frozen target event")
        if applies:
            assert call is not None and persisted_result is not None
            result = ClaimDecompositionResultV3.model_validate(persisted_result.get("payload"))
            task_row = session.get(TaskRow, call.task_id)
            if task_row is None:
                raise ValueError("lineage child task is missing")
            task_payload = WorkerTaskPayload.model_validate(json.loads(task_row.payload_json))
            claim_policy = ClaimVerificationPolicy.model_validate(
                task_payload.inputs.get("claim_verification_policy"))
            output_policy = ClaimDecompositionOutputPolicy.model_validate(
                task_payload.inputs.get("claim_decomposition_output"))
            if (len(result.claims) > output_policy.max_total_claims
                    or sum(item.importance == "critical" for item in result.claims)
                    > claim_policy.max_critical_claims_per_hypothesis):
                raise ValueError("child claim count exceeds frozen decomposition limits")
            plan = validate_persisted_offspring_task_v2(
                events=prior_events, task=task_payload,
                task_id=call.task_id, run_id=run_id,
            )
            validate_lineage_task_identity(manifest, task_payload,
                                           durable_targets_verified=True)
            contents = [event for event in prior_events
                        if event.event_type == "HypothesisContentCreated"
                        and event.payload.get("hypothesis_id") == plan.child_hypothesis_id]
            if len(contents) != 1:
                raise ValueError("lineage child content event is missing or ambiguous")
            child_content = HypothesisContent.model_validate(dict(contents[0].payload))
            parents = durable_parent_scope_v2(
                events=prior_events,
                selected_parent_ids=tuple(ref.parent_hypothesis_id
                                          for ref in plan.selected_parents),
                selected_parent_hashes={ref.parent_hypothesis_id:
                                        ref.parent_hypothesis_content_hash
                                        for ref in plan.selected_parents},
            )
            expected_events, application = resolve_child_decomposition_events_v2(
                run_id=run_id, result_id=str(persisted_result["result_id"]),
                plan=plan, parents=parents,
                child_content=child_content, result=result,
            )
            scientific_events = events[:len(expected_events)]
            continuation_events = events[len(expected_events):]
            probe_terminal = (
                len(continuation_events) == 1
                and continuation_events[0].event_type == "CompatibilityProbeTerminatedV1"
                and manifest.get("probe_execution_envelope") is not None
                and not followup_tasks
            )
            expected_continuation = tuple(NewEvent(
                event_type="TaskEnqueued", payload=task.model_dump(mode="json"),
                causation_id=str(persisted_result["result_id"]), correlation_id=run_id,
            ) for task in followup_tasks)
            if ([event.model_dump(mode="json") for event in expected_events]
                    != [event.model_dump(mode="json") for event in scientific_events]
                    or (not probe_terminal and
                        [event.model_dump(mode="json") for event in expected_continuation]
                        != [event.model_dump(mode="json") for event in continuation_events])
                    or (application.state != "complete" and followup_tasks)
                    or applies[0].payload.get("application_hash")
                    != scientific_hash(application.model_dump(mode="json"))):
                raise ValueError("lineage claim events or application differ from durable result")
            if any(event.event_type == "ClaimLineageAppliedV2"
                   and event.payload.get("source_result_id")
                   == persisted_result["result_id"] for event in prior_events):
                raise ValueError("child decomposition result was already applied")

    def _validate_scientist_resolution(
        self, session: Session, run_id: str, events: Sequence[NewEvent], tasks: Sequence[NewTask],
    ) -> None:
        """Closed resolution bundle; ordinary resume must never clear scientific attention."""
        from co_scientist.domain.research_protocol import protocol_hash

        if ([e.event_type for e in events] != ["ScientistFeedbackRecorded", "RunResumed", "TaskEnqueued"]
                or len(tasks) != 1):
            raise ValueError("needs_attention requires a dedicated resolution command")
        record, resumed, enqueued = (thaw_json(e.payload) for e in events)
        task = tasks[0]
        inputs = thaw_json(task.payload).get("inputs", {})
        prior = session.scalars(select(EventRow).where(EventRow.run_id == run_id).order_by(EventRow.sequence)).all()
        feedback: dict[str, Any] = next((json.loads(e.payload_json) for e in reversed(prior)
                         if e.event_type == "ResearchFeedbackRecorded"), {})
        attention: dict[str, Any] = next((json.loads(e.payload_json) for e in reversed(prior)
                          if e.event_type == "RunNeedsAttention"), {})
        run = session.get(RunRow, run_id)
        assert run is not None
        manifest = self._require_execution_contract(run)
        meta = manifest.get("profile", {}).get("meta_review", {})
        rounds = sum(e.event_type == "TaskEnqueued"
                     and bool(json.loads(e.payload_json).get("payload", {}).get("inputs", {}).get("meta_review_round"))
                     for e in prior)
        pending = session.scalar(select(TaskRow).where(TaskRow.run_id == run_id,
            TaskRow.state.in_(["pending", "running", "result_received"])))
        unsigned = {k: v for k, v in record.items() if k != "feedback_hash"}
        if (pending is not None or record.get("feedback_hash") != protocol_hash(unsigned)
                or not isinstance(record.get("note"), str) or not record["note"].strip()
                or len(record["note"]) > 12000 or not isinstance(record.get("actor"), str)
                or not record["actor"].strip() or len(record["actor"]) > 200
                or record.get("handling_policy") != "scientist-reassessment-v1"
                or attention.get("reason") != "meta_review_requires_scientist_input"
                or feedback.get("safety_direction_check") not in {"concern", "insufficient_evidence"}
                or record.get("source_feedback_id") != feedback.get("feedback_id")
                or attention.get("feedback_id") != feedback.get("feedback_id")
                or record.get("source_feedback_hash") != feedback.get("feedback_hash")
                or any(record.get(k) != feedback.get(k) for k in ("epoch_id", "research_plan_version", "source_content_hashes"))
                or record.get("epoch_id") != manifest["tournament_contract"]["epoch_id"]
                or record.get("research_plan_version") != manifest["tournament_contract"]["research_plan_version"]
                or rounds >= meta.get("max_rounds", 0) or inputs.get("meta_review_round") != rounds + 1
                or task.run_id != run_id or task.intent_type != "run_meta_review"
                or task.payload.get("provider_id") != manifest["provider_configuration"]["provider"]
                or task.payload.get("model_or_tool") != manifest["provider_configuration"]["model"]
                or task.payload.get("skill_id") != "meta_review" or inputs.get("scientist_feedback") != record
                or inputs.get("source_content_hashes") != feedback.get("source_content_hashes")
                or inputs.get("research_feedback") != feedback
                or inputs.get("task_goal") != manifest["feedback_contract"]["meta_review_instruction"]
                or resumed.get("reason") != "scientist_reassessment_queued"
                or resumed.get("scientist_feedback_id") != record.get("scientist_feedback_id")
                or resumed.get("task_id") != task.task_id or enqueued.get("task_id") != task.task_id
                or enqueued.get("payload") != thaw_json(task.payload)):
            raise ValueError("invalid scientist reassessment evidence or task binding")
        snapshot = self._load_budget_snapshot(session, run_id)
        policy = BudgetPolicy.model_validate(manifest.get("budget", {}))
        estimate = BudgetEstimate.model_validate(task.payload.get("budget_estimate", {}))
        if (policy.max_model_calls is None or snapshot.hard_limit_reached or estimate.model_calls != 1
                or not self._fits_budget(policy, snapshot.total_usage, estimate)):
            raise ValueError("scientist reassessment exceeds frozen budget")

    def _validate_lifecycle_batch(
        self,
        session: Session,
        *,
        run_id: str,
        events: Sequence[NewEvent],
        target_run_state: RunState | None,
        followup_tasks: Sequence[NewTask] = (),
    ) -> None:
        lifecycle_events = [
            event.event_type for event in events if event.event_type in _LIFECYCLE_EVENT_TARGETS
        ]
        if target_run_state is None:
            if lifecycle_events:
                event_type = lifecycle_events[0]
                required = _LIFECYCLE_EVENT_TARGETS[event_type]
                raise ValueError(f"lifecycle event {event_type} requires target {required.value}")
            return

        state = self._run_state_in_transaction(session, run_id)
        if state is RunState.NEEDS_ATTENTION and target_run_state is RunState.RUNNING:
            self._validate_scientist_resolution(session, run_id, events, followup_tasks)
        validate_run_transition(state, target_run_state)
        for event_type in lifecycle_events:
            required = _LIFECYCLE_EVENT_TARGETS[event_type]
            if required is not target_run_state:
                raise ValueError(f"lifecycle event {event_type} requires target {required.value}")
        expected_event = _LIFECYCLE_TRANSITION_EVENTS.get((state, target_run_state))
        if expected_event is None:
            raise ValueError(
                f"run transition {state.value} -> {target_run_state.value} "
                "has no lifecycle event contract"
            )
        if lifecycle_events != [expected_event]:
            raise ValueError(
                f"run transition to {target_run_state.value} requires {expected_event}"
            )

    @staticmethod
    def _validate_probe_execution_batch(
        session: Session, *, run_id: str, events: Sequence[NewEvent],
        followup_tasks: Sequence[NewTask], external_call_id: str | None,
    ) -> None:
        """A probe terminal is operational, never a scientific admission/finalization."""

        run = session.get(RunRow, run_id)
        assert run is not None
        probe = probe_envelope_for_manifest(json.loads(run.manifest_json))
        if probe is None:
            if any(e.event_type == "CompatibilityProbeTerminatedV1" for e in events):
                raise ValueError("probe terminal requires a frozen probe envelope")
            return
        prior_terminal = session.scalar(select(EventRow).where(
            EventRow.run_id == run_id,
            EventRow.event_type == "CompatibilityProbeTerminatedV1",
        ))
        if prior_terminal is not None:
            raise ValueError("compatibility probe is already operationally terminal")
        terminal = [e for e in events if e.event_type == "CompatibilityProbeTerminatedV1"]
        if len(terminal) > 1 or (terminal and followup_tasks):
            raise ValueError("probe terminal must be unique and have no follow-up tasks")
        if not terminal:
            return
        event = terminal[0]
        payload = event.payload
        if (event.schema_version != 1
                or payload.get("policy_version") != probe.version
                or payload.get("status") not in {"passed", "failed"}
                or payload.get("stage") not in {"A", "B"}
                or not isinstance(payload.get("task_id"), str)
                or not isinstance(payload.get("reason"), str)
                or not payload["reason"]):
            raise ValueError("invalid versioned probe terminal event")
        task = session.get(TaskRow, payload["task_id"])
        if task is None or task.run_id != run_id:
            raise ValueError("probe terminal task identity mismatch")
        task_payload = json.loads(task.payload_json)
        expected_schema = (
            "PopulationEvolutionResultV2" if payload["stage"] == "A"
            else "ClaimDecompositionResultV3"
        )
        if task_payload.get("output_schema_id") != expected_schema:
            raise ValueError("probe terminal stage differs from frozen task")
        if payload["status"] == "passed":
            applies = [e for e in events if e.event_type == "ClaimLineageAppliedV2"]
            if (payload["stage"] != "B" or len(applies) != 1
                    or applies[0].payload.get("application", {}).get("state") != "complete"
                    or external_call_id is None):
                raise ValueError("probe success requires an applied complete V3 lineage result")
        if external_call_id is not None and payload.get("external_call_id") != external_call_id:
            raise ValueError("probe terminal differs from source external call")

    @staticmethod
    def _validate_bayesian_pair_reservations(
        session: Session, *, run_id: str, events: Sequence[NewEvent],
        followup_tasks: Sequence[NewTask],
    ) -> None:
        run = session.get(RunRow, run_id)
        if run is None:
            raise KeyError(run_id)
        manifest = json.loads(run.manifest_json)
        profile = manifest.get("profile")
        if not isinstance(profile, dict):
            return
        tournament = profile.get("tournament", {})
        if not isinstance(tournament, dict):
            return
        if tournament.get("rating_policy_version") != "trueskill_v1":
            return
        from co_scientist.domain.ideation_core_boundary import batch34_execution_enabled

        if batch34_execution_enabled(manifest):
            from co_scientist.domain.bayesian_ranking import (
                TrueSkillConfig,
                replay_bayesian_rating,
                select_baseline_pair,
            )
            from co_scientist.domain.research_protocol import protocol_hash

            rows = session.scalars(select(EventRow).where(EventRow.run_id == run_id)
                                   .order_by(EventRow.sequence)).all()
            history = [DomainEvent(run_id=run_id, sequence=row.sequence, event_type=row.event_type,
                schema_version=row.schema_version, payload=json.loads(row.payload_json)) for row in rows]
            new = [e.payload for e in events if e.event_type == "MatchPairReserved"]
            tasks = {t.task_id: t for t in followup_tasks if t.intent_type == "run_ranking"}
            if len(new) != len(tasks) or len(new) > 1:
                raise ValueError("baseline committed-match order requires at most one reserved match")
            if new and session.scalar(select(TaskRow.task_id).where(
                    TaskRow.run_id == run_id, TaskRow.intent_type == "run_ranking",
                    TaskRow.state.not_in(("succeeded", "failed", "cancelled"))).limit(1)) is not None:
                raise ValueError("baseline requires prior Ranking opportunity to terminate before enqueue")
            for item in new:
                task = tasks.get(str(item["task_id"]))
                if task is None or task.payload["output_schema_id"] != "BaselineRankingResultV1":
                    raise ValueError("baseline match requires exact versioned ranking task")
                visible = task.payload["inputs"]["model_input"]
                if any(thaw_json(item.get(key)) != thaw_json(visible.get(key)) for key in (
                    "match_id", "epoch_id", "left_id", "right_id", "focal_id", "pairing")):
                    raise ValueError("baseline reservation differs from exact frozen task")
                prior = [e for e in history if e.event_type == "MatchPairReserved"]
                limit = profile["budget"].get("max_matches")
                if limit is None or len(prior) >= limit:
                    raise ValueError("baseline reservation exceeds finite run-global match envelope")
                if any(e.payload["match_id"] == item["match_id"] for e in prior):
                    raise ValueError("duplicate baseline logical opportunity")
                epoch = manifest["tournament_contract"]["epoch_id"]
                ratings = replay_bayesian_rating(history, epoch_id=epoch, policy=TrueSkillConfig())
                seed = protocol_hash({"run_id": run_id, "manifest_hash": protocol_hash(manifest)})
                baseline_pair, state = select_baseline_pair(ratings, history, epoch_id=epoch, seed=seed)
                if baseline_pair is None or state != "MATCH_REQUIRED" or baseline_pair.model_dump(mode="json") != thaw_json(item["pairing"]):
                    raise ValueError("baseline opportunity violates focal quota/cap/pair/orientation policy")
            return
        policy = UCBPairingPolicy.model_validate(tournament["selection"])
        new = [event.payload for event in events if event.event_type == "MatchPairReserved"]
        task_by_id = {task.task_id: task for task in followup_tasks
                      if task.intent_type == "run_ranking"}
        if len(new) != len(task_by_id):
            raise ValueError("each Bayesian ranking task requires one pair reservation")
        prior_rows = session.scalars(select(EventRow).where(
            EventRow.run_id == run_id,
            EventRow.event_type == "MatchPairReserved",
        ).order_by(EventRow.sequence)).all()
        all_reservations = [json.loads(row.payload_json) for row in prior_rows]
        match_ids = {str(item["match_id"]) for item in all_reservations}
        from collections import Counter

        candidate_counts: Counter[tuple[str, str]] = Counter()
        pair_counts: Counter[tuple[str, str, str]] = Counter()
        tiebreaker_counts: Counter[tuple[str, str, str]] = Counter()
        for item in all_reservations:
            epoch = str(item["epoch_id"])
            left, right = str(item["left_id"]), str(item["right_id"])
            pair = (epoch, *sorted((left, right)))
            candidate_counts.update(((epoch, left), (epoch, right)))
            pair_counts[pair] += 1
            if item.get("comparison_kind") == "tiebreaker":
                tiebreaker_counts[pair] += 1
        for item in new:
            task_id = str(item["task_id"])
            task = task_by_id.pop(task_id, None)
            if task is None:
                raise ValueError("Bayesian reservation has no matching ranking task")
            inputs = task.payload["inputs"]
            if any(item.get(key) != inputs.get(key) for key in (
                "match_id", "epoch_id", "left_id", "right_id", "evidence_context_hash",
                "comparison_kind",
            )):
                raise ValueError("Bayesian pair reservation does not match frozen task")
            match_id = str(item["match_id"])
            if match_id in match_ids:
                raise ValueError("duplicate Bayesian match reservation")
            match_ids.add(match_id)
            epoch = str(item["epoch_id"])
            left, right = str(item["left_id"]), str(item["right_id"])
            if left == right:
                raise ValueError("self-comparison is not a match")
            pair = (epoch, *sorted((left, right)))
            if (candidate_counts[(epoch, left)] >= policy.max_matches_per_candidate
                    or candidate_counts[(epoch, right)] >= policy.max_matches_per_candidate
                    or pair_counts[pair] >= policy.max_matches_per_pair
                    or (item.get("comparison_kind") == "tiebreaker"
                        and tiebreaker_counts[pair] >= policy.max_tiebreakers_per_pair)):
                raise ValueError("Bayesian pair exceeds frozen match caps")
            candidate_counts.update(((epoch, left), (epoch, right)))
            pair_counts[pair] += 1
            if item.get("comparison_kind") == "tiebreaker":
                tiebreaker_counts[pair] += 1

    def commit_domain_batch(
        self,
        *,
        run_id: str,
        expected_sequence: int,
        events: Sequence[NewEvent],
        target_run_state: RunState | str | None = None,
        task_mutations: Sequence[TaskMutation] = (),
        followup_tasks: Sequence[NewTask] = (),
        idempotency_key: str,
        external_call_id: str | None = None,
        reservation_id: str | None = None,
        lease_fence: TaskLeaseFence | None = None,
        fence: TaskLeaseFence | None = None,
        settle_reservation_id: str | None = None,
        release_reservation_id: str | None = None,
        cost_entries: Sequence[CostEntry] = (),
        _validate_sequence_before_replay: bool = False,
    ) -> CommitResult:
        if not events and release_reservation_id is None:
            raise ValueError("a domain batch must contain at least one event")
        if lease_fence is not None and fence is not None:
            raise ValueError("provide lease_fence or fence, not both")
        resolved_fence = lease_fence or fence
        if settle_reservation_id is not None and release_reservation_id is not None:
            raise ValueError("a reservation cannot settle and release in one batch")
        if release_reservation_id is not None and (
            external_call_id is not None
            or cost_entries
            or any(event.event_type in EVENT_SCHEMA_VERSIONS for event in events)
        ):
            raise ValueError(
                "budget release batch cannot contain provider, cost, or scientific effects"
            )
        run_target = RunState(target_run_state) if target_run_state is not None else None
        batch_fingerprint = self._batch_fingerprint(
            events=events,
            target_run_state=run_target,
            task_mutations=task_mutations,
            followup_tasks=followup_tasks,
            external_call_id=external_call_id,
            reservation_id=reservation_id,
            lease_fence=resolved_fence,
            settle_reservation_id=settle_reservation_id,
            release_reservation_id=release_reservation_id,
            cost_entries=cost_entries,
        )
        with self.session_factory.begin() as session:
            self._begin_immediate(session)
            self._require_run(session, run_id)
            if _validate_sequence_before_replay:
                self._assert_sequence(session, run_id, expected_sequence)
            previous = self._load_idempotency_commit(
                session, run_id, idempotency_key, batch_fingerprint
            )
            if previous is not None:
                return previous
            if external_call_id is not None:
                if reservation_id is None or resolved_fence is None:
                    raise ValueError("domain application requires reservation and task lease fence")
                self._validate_domain_fence(
                    session,
                    external_call_id=external_call_id,
                    reservation_id=reservation_id,
                    fence=resolved_fence,
                )
            elif reservation_id is not None:
                raise ValueError("external-call reservation requires an external call")
            elif resolved_fence is not None and release_reservation_id is None:
                raise ValueError("task lease fence requires an external call or release")
            if not _validate_sequence_before_replay:
                self._assert_sequence(session, run_id, expected_sequence)
            self._validate_probe_execution_batch(
                session, run_id=run_id, events=events,
                followup_tasks=followup_tasks, external_call_id=external_call_id,
            )
            self._validate_lifecycle_batch(
                session,
                run_id=run_id,
                events=events,
                target_run_state=run_target,
                followup_tasks=followup_tasks,
            )
            self._validate_bayesian_pair_reservations(
                session, run_id=run_id, events=events, followup_tasks=followup_tasks,
            )
            self._validate_domain_batch_mutations(
                session,
                run_id=run_id,
                events=events,
                task_mutations=task_mutations,
                followup_tasks=followup_tasks,
                external_call_id=external_call_id,
                cost_entries=cost_entries,
                target_run_state=run_target,
            )
            self._validate_lineage_v2_atomic_batch(
                session, run_id=run_id, events=events,
                followup_tasks=followup_tasks, external_call_id=external_call_id,
            )
            if settle_reservation_id is not None:
                if external_call_id is None or settle_reservation_id != reservation_id:
                    raise ValueError("budget settlement requires its fenced external call")
                self._validate_cost_entries_from_calls(session, run_id, cost_entries)
            self._insert_cost_entries(session, run_id, cost_entries)
            session.flush()
            persisted_events = list(events)
            if settle_reservation_id is not None:
                persisted_events.append(
                    self._settle_budget_reservation(
                        session,
                        run_id=run_id,
                        reservation_id=settle_reservation_id,
                        external_call_id=cast(str, external_call_id),
                        events=events,
                    )
                )
            elif release_reservation_id is not None:
                if resolved_fence is None:
                    raise ValueError("budget release requires a task lease fence")
                persisted_events.insert(
                    0,
                    self._release_budget_reservation(
                        session,
                        run_id=run_id,
                        reservation_id=release_reservation_id,
                        lease_fence=resolved_fence,
                    )
                )
            self._apply_run_transition(session, run_id, run_target)
            self._apply_task_mutations(
                session,
                run_id,
                task_mutations,
                source_external_call_id=external_call_id,
            )
            self._insert_followup_tasks(session, run_id, followup_tasks)
            persisted = self._insert_events(
                session, run_id, expected_sequence, persisted_events
            )
            last_sequence = persisted[-1].sequence
            self._insert_idempotency_commit(
                session,
                run_id,
                idempotency_key,
                batch_fingerprint,
                persisted[0].sequence,
                last_sequence,
            )
            if external_call_id is not None:
                self._mark_external_call_domain_applied(
                    session, run_id, external_call_id, last_sequence
                )
            self._set_run_sequence(session, run_id, last_sequence, required=True)
            session.flush()
        return CommitResult(events=tuple(persisted), last_sequence=last_sequence)

    def commit_lifecycle_batch(
        self,
        *,
        run_id: str,
        expected_sequence: int,
        events: Sequence[NewEvent],
        target_run_state: RunState | str | None = None,
        task_mutations: Sequence[TaskMutation] = (),
        followup_tasks: Sequence[NewTask] = (),
        idempotency_key: str,
        lease_fence: TaskLeaseFence | None = None,
        release_reservation_id: str | None = None,
    ) -> CommitResult:
        """Commit lifecycle state only after validating the caller's current sequence."""

        return self.commit_domain_batch(
            run_id=run_id,
            expected_sequence=expected_sequence,
            events=events,
            target_run_state=target_run_state,
            task_mutations=task_mutations,
            followup_tasks=followup_tasks,
            idempotency_key=idempotency_key,
            lease_fence=lease_fence,
            release_reservation_id=release_reservation_id,
            _validate_sequence_before_replay=True,
        )
