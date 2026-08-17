"""SQLite-backed event store and transactional domain unit of work."""

from __future__ import annotations

import hashlib
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
from co_scientist.domain.run_mutations import RunMutationKind, validate_run_mutation
from co_scientist.domain.states import ExternalCallState, RunState, TaskState
from co_scientist.domain.task import NewTask, TaskMutation
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
    __table_args__ = (UniqueConstraint("run_id", "idempotency_key"),)

    task_id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(String, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False)
    intent_type: Mapped[str] = mapped_column(String, nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String, nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


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

    cost_entry_id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(String, nullable=False)
    external_call_id: Mapped[str] = mapped_column(String, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cost_usd: Mapped[str] = mapped_column(String, nullable=False, server_default="0")
    pricing_version: Mapped[str] = mapped_column(String, nullable=False)


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
                "unsupported scientific event version: "
                f"{event.event_type} v{event.schema_version}"
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
                    validate_run_mutation(
                        state, RunMutationKind.APPEND_SCIENTIFIC_EVENT
                    )
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
    ) -> CommitResult:
        """Atomically create a Run and persist its validated start transition."""

        if event.event_type != "RunStarted":
            raise ValueError("started Run initialization requires RunStarted")
        initialization_fingerprint = "sha256:" + hashlib.sha256(
            _json(
                {
                    "run_id": run_id,
                    "manifest": manifest,
                    "event": {
                        "event_type": event.event_type,
                        "schema_version": event.schema_version,
                        "payload": event.model_dump(mode="json")["payload"],
                    },
                    "idempotency_key": idempotency_key,
                }
            ).encode("utf-8")
        ).hexdigest()
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
                    and previous.last_sequence == 1
                    and existing_run.manifest_json == _json(manifest)
                    and len(previous.events) == 1
                    and previous.events[0].sequence == 1
                    and previous.events[0].event_type == event.event_type
                    and previous.events[0].schema_version == event.schema_version
                    and _json(previous.events[0].payload)
                    == _json(event.model_dump(mode="json")["payload"])
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
            persisted = self._insert_events(session, run_id, 0, (event,))
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

    def transition_task(self, task_id: str, target_state: TaskState | str) -> None:
        target = TaskState(target_state)
        with self.session_factory.begin() as session:
            self._begin_immediate(session)
            row = session.get(TaskRow, task_id)
            if row is None:
                raise KeyError(f"unknown task: {task_id}")
            row.state = validate_task_transition(TaskState(row.state), target).value

    def task_state(self, task_id: str) -> str:
        with self.session_factory() as session:
            state = session.scalar(select(TaskRow.state).where(TaskRow.task_id == task_id))
        if state is None:
            raise KeyError(f"unknown task: {task_id}")
        return state

    def task_intent(self, task_id: str) -> str:
        with self.session_factory() as session:
            intent = session.scalar(
                select(TaskRow.intent_type).where(TaskRow.task_id == task_id)
            )
        if intent is None:
            raise KeyError(f"unknown task: {task_id}")
        return intent

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
        attempt: int = 1,
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
            validate_run_mutation(
                self._run_state_in_transaction(session, run_id),
                (
                    RunMutationKind.PLAN_FINALIZATION_CALL
                    if task.intent_type == "finalize_run"
                    else RunMutationKind.PLAN_EXPLORATION_CALL
                ),
                task_intent=task.intent_type,
            )
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
            session.add(
                ExternalCallRow(
                    external_call_id=call_id,
                    run_id=run_id,
                    task_id=task_id,
                    attempt=attempt,
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
        usage: Mapping[str, Any] | None = None,
    ) -> None:
        target = ExternalCallState(target_state)
        with self.session_factory.begin() as session:
            self._begin_immediate(session)
            row = self._external_call(session, call_id)
            row.raw_artifact_ref_json = ref.model_dump_json()
            row.provider_response_id = provider_response_id
            row.usage_json = _json(thaw_json(usage or {}))
            row.state = transition_external_call(ExternalCallState(row.state), target).value

    def record_validated(self, call_id: str, payload: Mapping[str, Any]) -> None:
        with self.session_factory.begin() as session:
            self._begin_immediate(session)
            row = self._external_call(session, call_id)
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
        )
        if result_data.get("external_call_id") != row.external_call_id or any(
            result_data.get(field) != context.get(field) for field in trace_fields
        ):
            raise ValueError("submitted result does not match external call traceability")
        raw_ref = (
            json.loads(row.raw_artifact_ref_json)
            if row.raw_artifact_ref_json is not None
            else None
        )
        if result_data.get("raw_artifact_ref") != raw_ref:
            raise ValueError("submitted result does not match external call raw artifact")
        if payload is not None and result_data.get("payload") != dict(payload):
            raise ValueError("submitted result does not match validated payload")

    def record_submitted_result(self, call_id: str, result: BaseModel) -> None:
        result_data = result.model_dump(mode="json")
        result_json = _json(result_data)
        with self.session_factory.begin() as session:
            self._begin_immediate(session)
            row = self._external_call(session, call_id)
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
    ) -> None:
        payload_json = _json(dict(payload))
        result_data = result.model_dump(mode="json")
        result_json = _json(result_data)
        result_id = getattr(result, "result_id", None)
        if not isinstance(result_id, str):
            raise TypeError("submitted result must have a string result_id")
        with self.session_factory.begin() as session:
            self._begin_immediate(session)
            row = self._external_call(session, call_id)
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

    @staticmethod
    def _assert_run_owner(
        *, kind: str, identifier: str, actual_run_id: str, expected_run_id: str
    ) -> None:
        if actual_run_id != expected_run_id:
            raise ValueError(f"{kind} {identifier} does not belong to run {expected_run_id}")

    @classmethod
    def _apply_task_mutations(
        cls, session: Session, run_id: str, mutations: Sequence[TaskMutation]
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
            row.state = validate_task_transition(
                TaskState(row.state), mutation.target_state
            ).value

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
        cost_entries: Sequence[CostEntry],
    ) -> str:
        canonical = _json(
            {
                "events": [event.model_dump(mode="json") for event in events],
                "target_run_state": target_run_state.value if target_run_state else None,
                "task_mutations": [mutation.model_dump(mode="json") for mutation in task_mutations],
                "followup_tasks": [task.model_dump(mode="json") for task in followup_tasks],
                "external_call_id": external_call_id,
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
            event.event_type
            for event in events
            if event.event_type in _LIFECYCLE_EVENT_TARGETS
        ]
        if target_run_state is None:
            if lifecycle_events:
                event_type = lifecycle_events[0]
                required = _LIFECYCLE_EVENT_TARGETS[event_type]
                raise ValueError(
                    f"lifecycle event {event_type} requires target {required.value}"
                )
            return

        state = self._run_state_in_transaction(session, run_id)
        validate_run_transition(state, target_run_state)
        for event_type in lifecycle_events:
            required = _LIFECYCLE_EVENT_TARGETS[event_type]
            if required is not target_run_state:
                raise ValueError(
                    f"lifecycle event {event_type} requires target {required.value}"
                )
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
        cost_entries: Sequence[CostEntry] = (),
        _validate_sequence_before_replay: bool = False,
    ) -> CommitResult:
        if not events:
            raise ValueError("a domain batch must contain at least one event")
        run_target = RunState(target_run_state) if target_run_state is not None else None
        batch_fingerprint = self._batch_fingerprint(
            events=events,
            target_run_state=run_target,
            task_mutations=task_mutations,
            followup_tasks=followup_tasks,
            external_call_id=external_call_id,
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
            self._apply_run_transition(session, run_id, run_target)
            persisted = self._insert_events(session, run_id, expected_sequence, events)
            self._apply_task_mutations(session, run_id, task_mutations)
            self._insert_followup_tasks(session, run_id, followup_tasks)
            self._insert_cost_entries(session, run_id, cost_entries)
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
            _validate_sequence_before_replay=True,
        )
