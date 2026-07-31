"""SQLite-backed event store and transactional domain unit of work."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, cast

from pydantic import BaseModel, ConfigDict
from sqlalchemy import (
    DateTime,
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

from co_scientist.domain.budget import CostEntry
from co_scientist.domain.states import ExternalCallState, RunState, TaskState
from co_scientist.domain.task import NewTask, TaskMutation
from co_scientist.domain.transitions import transition_external_call
from co_scientist.events.models import DomainEvent, NewEvent
from co_scientist.ports.artifact_store import ArtifactRef
from co_scientist.ports.event_store import ConcurrencyConflict


class Base(DeclarativeBase):
    """Declarative metadata shared with Alembic."""


class RunRow(Base):
    __tablename__ = "runs"

    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    state: Mapped[str] = mapped_column(String, nullable=False)
    current_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
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
    __table_args__ = (UniqueConstraint("run_id", "idempotency_key"),)

    task_id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(String, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False)
    intent_type: Mapped[str] = mapped_column(String, nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String, nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


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
    usage_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")


class CostEntryRow(Base):
    __tablename__ = "cost_entries"

    cost_entry_id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(String, nullable=False)
    external_call_id: Mapped[str] = mapped_column(String, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[str] = mapped_column(String, nullable=False, default="0")
    pricing_version: Mapped[str] = mapped_column(String, nullable=False)


class IdempotencyCommitRow(Base):
    __tablename__ = "idempotency_commits"

    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String, primary_key=True)
    last_sequence: Mapped[int] = mapped_column(Integer, nullable=False)


class CommitResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    events: tuple[DomainEvent, ...]
    last_sequence: int


class PersistedExternalCall(BaseModel):
    """External-call state required by the raw-first runtime."""

    model_config = ConfigDict(frozen=True)

    external_call_id: str
    state: ExternalCallState
    raw_artifact_ref: ArtifactRef | None = None
    validated_payload: Mapping[str, Any] | None = None
    agent_result_id: str | None = None
    applied_domain_sequence: int | None = None


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


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
    def _set_run_sequence(session: Session, run_id: str, sequence: int) -> None:
        session.execute(
            update(RunRow).where(RunRow.run_id == run_id).values(current_sequence=sequence)
        )

    def append(
        self,
        run_id: str,
        expected_sequence: int,
        events: Sequence[NewEvent],
    ) -> list[DomainEvent]:
        if not events:
            return []
        with self.session_factory.begin() as session:
            self._begin_immediate(session)
            self._assert_sequence(session, run_id, expected_sequence)
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
            session.add_all([self._task_row(task) for task in tasks])

    def transition_task(self, task_id: str, target_state: TaskState | str) -> None:
        target = TaskState(target_state)
        with self.session_factory.begin() as session:
            self._begin_immediate(session)
            result = cast(
                CursorResult[Any],
                session.execute(
                    update(TaskRow).where(TaskRow.task_id == task_id).values(state=target.value)
                ),
            )
            if result.rowcount != 1:
                raise KeyError(f"unknown task: {task_id}")

    def task_state(self, task_id: str) -> str:
        with self.session_factory() as session:
            state = session.scalar(select(TaskRow.state).where(TaskRow.task_id == task_id))
        if state is None:
            raise KeyError(f"unknown task: {task_id}")
        return state

    def plan_external_call(
        self,
        call_id: str,
        request_fingerprint: str,
        *,
        run_id: str = "",
        task_id: str = "",
        attempt: int = 1,
        provider: str = "unknown",
        model_or_tool: str = "unknown",
        parent_call_id: str | None = None,
    ) -> None:
        with self.session_factory.begin() as session:
            self._begin_immediate(session)
            session.add(
                ExternalCallRow(
                    external_call_id=call_id,
                    run_id=run_id,
                    task_id=task_id,
                    attempt=attempt,
                    request_fingerprint=request_fingerprint,
                    provider=provider,
                    model_or_tool=model_or_tool,
                    state=ExternalCallState.PLANNED.value,
                    parent_call_id=parent_call_id,
                    usage_json="{}",
                )
            )

    @staticmethod
    def _external_call(session: Session, call_id: str) -> ExternalCallRow:
        row = session.get(ExternalCallRow, call_id)
        if row is None:
            raise KeyError(f"unknown external call: {call_id}")
        return row

    def transition_call(self, call_id: str, target_state: ExternalCallState | str) -> None:
        target = ExternalCallState(target_state)
        with self.session_factory.begin() as session:
            self._begin_immediate(session)
            row = self._external_call(session, call_id)
            row.state = transition_external_call(ExternalCallState(row.state), target).value

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
        usage: Mapping[str, int] | None = None,
    ) -> None:
        target = ExternalCallState(target_state)
        with self.session_factory.begin() as session:
            self._begin_immediate(session)
            row = self._external_call(session, call_id)
            row.raw_artifact_ref_json = ref.model_dump_json()
            row.provider_response_id = provider_response_id
            row.usage_json = _json(dict(usage or {}))
            row.state = transition_external_call(ExternalCallState(row.state), target).value

    def record_validated(self, call_id: str, payload: Mapping[str, Any]) -> None:
        with self.session_factory.begin() as session:
            self._begin_immediate(session)
            row = self._external_call(session, call_id)
            row.validated_artifact_ref_json = _json(dict(payload))
            row.state = transition_external_call(
                ExternalCallState(row.state), ExternalCallState.VALIDATED
            ).value

    def record_submitted_result(self, call_id: str, result: BaseModel) -> None:
        with self.session_factory.begin() as session:
            self._begin_immediate(session)
            row = self._external_call(session, call_id)
            result_id = getattr(result, "result_id", None)
            if not isinstance(result_id, str):
                raise TypeError("submitted result must have a string result_id")
            row.agent_result_id = result_id
            row.state = transition_external_call(
                ExternalCallState(row.state), ExternalCallState.AGENT_RESULT_SUBMITTED
            ).value

    def get_external_call(self, call_id: str) -> PersistedExternalCall:
        with self.session_factory() as session:
            row = self._external_call(session, call_id)
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
            return PersistedExternalCall(
                external_call_id=row.external_call_id,
                state=ExternalCallState(row.state),
                raw_artifact_ref=raw_ref,
                validated_payload=validated,
                agent_result_id=row.agent_result_id,
                applied_domain_sequence=row.applied_domain_sequence,
            )

    @staticmethod
    def _apply_task_mutations(session: Session, mutations: Sequence[TaskMutation]) -> None:
        for mutation in mutations:
            result = cast(
                CursorResult[Any],
                session.execute(
                    update(TaskRow)
                    .where(TaskRow.task_id == mutation.task_id)
                    .values(state=mutation.target_state.value)
                ),
            )
            if result.rowcount != 1:
                raise KeyError(f"unknown task: {mutation.task_id}")

    def _insert_followup_tasks(self, session: Session, tasks: Sequence[NewTask]) -> None:
        session.add_all([self._task_row(task) for task in tasks])

    @staticmethod
    def _insert_cost_entries(session: Session, entries: Sequence[CostEntry]) -> None:
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
    def _insert_idempotency_commit(
        session: Session,
        run_id: str,
        idempotency_key: str,
        last_sequence: int,
    ) -> None:
        session.add(
            IdempotencyCommitRow(
                run_id=run_id,
                idempotency_key=idempotency_key,
                last_sequence=last_sequence,
            )
        )

    def _mark_external_call_domain_applied(
        self, session: Session, external_call_id: str, sequence: int
    ) -> None:
        row = self._external_call(session, external_call_id)
        row.state = transition_external_call(
            ExternalCallState(row.state), ExternalCallState.DOMAIN_RESULT_APPLIED
        ).value
        row.applied_domain_sequence = sequence

    def commit_domain_batch(
        self,
        *,
        run_id: str,
        expected_sequence: int,
        events: Sequence[NewEvent],
        task_mutations: Sequence[TaskMutation] = (),
        followup_tasks: Sequence[NewTask] = (),
        idempotency_key: str,
        external_call_id: str | None = None,
        cost_entries: Sequence[CostEntry] = (),
    ) -> CommitResult:
        if not events:
            raise ValueError("a domain batch must contain at least one event")
        with self.session_factory.begin() as session:
            self._begin_immediate(session)
            self._assert_sequence(session, run_id, expected_sequence)
            persisted = self._insert_events(session, run_id, expected_sequence, events)
            self._apply_task_mutations(session, task_mutations)
            self._insert_followup_tasks(session, followup_tasks)
            self._insert_cost_entries(session, cost_entries)
            last_sequence = persisted[-1].sequence
            self._insert_idempotency_commit(
                session, run_id, idempotency_key, last_sequence
            )
            if external_call_id is not None:
                self._mark_external_call_domain_applied(
                    session, external_call_id, last_sequence
                )
            self._set_run_sequence(session, run_id, last_sequence)
            session.flush()
        return CommitResult(events=tuple(persisted), last_sequence=last_sequence)
