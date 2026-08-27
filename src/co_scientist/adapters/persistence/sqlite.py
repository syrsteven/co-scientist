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
from co_scientist.domain.budget import (
    BudgetEstimate,
    BudgetPolicy,
    BudgetUsage,
    CostEntry,
    DurableBudgetSnapshot,
    add_budget_usage,
)
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
from co_scientist.events.contracts import EVENT_SCHEMA_VERSIONS
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
        supported = EVENT_SCHEMA_VERSIONS.get(event.event_type)
        if supported is not None and event.schema_version not in supported:
            raise ValueError(
                f"unsupported scientific event version: {event.event_type} v{event.schema_version}"
            )

    def append(
        self,
        run_id: str,
        expected_sequence: int,
        events: Sequence[NewEvent],
    ) -> list[DomainEvent]:
        persisted: list[DomainEvent] = []
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
            validate_run_mutation(
                RunState.RUNNING,
                RunMutationKind.ENQUEUE_EXPLORATION_TASK,
                task_intent=task.intent_type,
            )
        for additional in additional_events:
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
        return usage

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
                paid_usage = self._provider_usage_for_task(
                    session, run_id=run_id, task_id=task.task_id
                )
                policy = BudgetPolicy.model_validate(manifest.get("budget", {}))
                retry_exceeds_budget = paid_usage.model_calls > 0 and not self._fits_budget(
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
            rows = sorted(
                {row.task_id: row for row in (*call_rows, *finalization_rows)}.values(),
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
            if reservation.external_call_id is not None:
                prior = session.get(ExternalCallRow, reservation.external_call_id)
                if prior is None or prior.attempt >= resolved_attempt:
                    raise ValueError("reservation is already bound to an external call")
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

    def _validate_lifecycle_batch(
        self,
        session: Session,
        *,
        run_id: str,
        events: Sequence[NewEvent],
        target_run_state: RunState | None,
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
            self._validate_lifecycle_batch(
                session,
                run_id=run_id,
                events=events,
                target_run_state=run_target,
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
