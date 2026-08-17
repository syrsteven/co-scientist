import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from alembic import command
from co_scientist.adapters.artifacts.filesystem import FilesystemArtifactStore
from co_scientist.adapters.persistence.sqlite import Base, SqliteUnitOfWork
from co_scientist.agents.result import AgentExecutionContext
from co_scientist.events.models import NewEvent
from co_scientist.ports.event_store import ConcurrencyConflict
from co_scientist.runtime.external_calls import (
    ExternalCallRunner,
    execution_context_fingerprint,
    request_fingerprint,
)


class ProviderMustNotRun:
    def __init__(self) -> None:
        self.call_count = 0

    async def invoke(self, request):
        self.call_count += 1
        raise AssertionError("provider must not be called")


def _valid_generation_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "research_plan_version": 1,
        "hypotheses": [
            {
                "schema_version": 1,
                "hypothesis_id": "h-legacy",
                "content_id": "c-legacy",
                "research_plan_version": 1,
                "title": "Legacy recovery",
                "claim": "Legacy calls recover from their durable typed payload.",
                "mechanism_chain": ["persist", "upgrade", "recover"],
                "assumptions": [],
                "predictions": [],
                "falsifiers": [],
                "generation_strategy": "migration fixture",
                "parent_content_ids": [],
                "supersedes_content_id": None,
                "content_hash": None,
            }
        ],
    }


def test_append_rejects_stale_expected_sequence(tmp_path) -> None:
    store = SqliteUnitOfWork(f"sqlite:///{tmp_path / 'core.db'}")
    store.create_schema()

    store.append_new("r-1", expected_sequence=0, event_type="RunCreated", payload={})

    with pytest.raises(ConcurrencyConflict, match="expected 0, got 1"):
        store.append_new("r-1", expected_sequence=0, event_type="RunStarted", payload={})


def test_append_loads_ordered_json_events_after_the_requested_sequence(tmp_path) -> None:
    store = SqliteUnitOfWork(f"sqlite:///{tmp_path / 'core.db'}")
    store.create_schema()

    first = store.append(
        "r-1",
        expected_sequence=0,
        events=[
            NewEvent(
                event_type="RunCreated",
                payload={"nested": {"values": [1, 2]}},
                causation_id="command-1",
                correlation_id="run-1",
            ),
            NewEvent(event_type="RunStarted", schema_version=2, payload={"ready": True}),
        ],
    )

    loaded_all = store.load("r-1")
    loaded = store.load("r-1", after_sequence=1)

    assert [event.sequence for event in first] == [1, 2]
    assert loaded_all[0].model_dump(mode="json", exclude={"occurred_at"}) == {
        "sequence": 1,
        "run_id": "r-1",
        "event_type": "RunCreated",
        "schema_version": 1,
        "payload": {"nested": {"values": [1, 2]}},
        "causation_id": "command-1",
        "correlation_id": "run-1",
    }
    assert len(loaded) == 1
    assert loaded[0].occurred_at.tzinfo is not None
    assert loaded[0].model_dump(mode="json", exclude={"occurred_at"}) == {
        "sequence": 2,
        "run_id": "r-1",
        "event_type": "RunStarted",
        "schema_version": 2,
        "payload": {"ready": True},
        "causation_id": None,
        "correlation_id": None,
    }


def test_empty_append_accepts_the_current_sequence_without_writing(tmp_path) -> None:
    store = SqliteUnitOfWork(f"sqlite:///{tmp_path / 'core.db'}")
    store.create_schema()
    store.append_new("r-1", expected_sequence=0, event_type="RunCreated", payload={})

    assert store.append("r-1", expected_sequence=1, events=[]) == []
    assert [event.sequence for event in store.load("r-1")] == [1]


def test_empty_append_rejects_a_stale_sequence(tmp_path) -> None:
    store = SqliteUnitOfWork(f"sqlite:///{tmp_path / 'core.db'}")
    store.create_schema()
    store.append_new("r-1", expected_sequence=0, event_type="RunCreated", payload={})

    with pytest.raises(ConcurrencyConflict, match="expected 0, got 1"):
        store.append("r-1", expected_sequence=0, events=[])


def test_alembic_schema_matches_runtime_metadata_including_server_defaults(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.delenv("CO_SCIENTIST_DATABASE_URL", raising=False)
    project_root = Path(__file__).parents[3]
    database_url = f"sqlite:///{tmp_path / 'migrated.db'}"
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, "head")

    engine = create_engine(database_url)
    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={"compare_server_default": True},
        )
        differences = compare_metadata(context, Base.metadata)
    engine.dispose()
    assert differences == []


def test_upgrade_existing_0001_database_supports_legacy_runtime_recovery(tmp_path) -> None:
    project_root = Path(__file__).parents[3]
    database_url = f"sqlite:///{tmp_path / 'migrated.db'}"
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "0001_core_tables")

    engine = create_engine(database_url)
    columns_at_0001 = {
        column["name"] for column in inspect(engine).get_columns("external_calls")
    }
    assert "execution_context_json" not in columns_at_0001
    assert "agent_result_json" not in columns_at_0001

    context = AgentExecutionContext(
        run_id="r-1",
        task_id="task-1",
        idempotency_key="generation:r-1:1",
        skill_id="generation",
        skill_version="0.2.0",
        output_schema_id="GenerationResultV1",
        output_schema_version=1,
        research_plan_version=1,
        provider="legacy",
        model_or_tool="legacy",
        input_snapshot_hash="sha256:input",
    )
    artifacts = FilesystemArtifactStore(tmp_path / "artifacts")
    fingerprint = request_fingerprint({"prompt": "generate"})
    payload = _valid_generation_payload()
    raw_payload = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ref = artifacts.persist_raw(
        "call-1",
        raw_payload,
        "application/json",
        request_fingerprint=fingerprint,
        run_id=context.run_id,
        task_id=context.task_id,
        execution_context_fingerprint=execution_context_fingerprint(
            context.model_dump(mode="json")
        ),
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO runs "
                "(run_id, state, current_sequence, manifest_json) "
                "VALUES ('r-1', 'running', 0, '{}')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO tasks "
                "(task_id, run_id, idempotency_key, intent_type, state, payload_json, attempt) "
                "VALUES ('task-1', 'r-1', 'generation:r-1:1', 'generate', 'running', '{}', 1)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO external_calls "
                "(external_call_id, run_id, task_id, attempt, request_fingerprint, provider, "
                "model_or_tool, state, raw_artifact_ref_json, validated_artifact_ref_json, "
                "agent_result_id, usage_json) "
                "VALUES (:call_id, :run_id, :task_id, 1, :fingerprint, 'legacy', 'legacy', "
                "'agent_result_submitted', :raw_ref, :payload, :result_id, '{}')"
            ),
            {
                "call_id": "call-1",
                "run_id": "r-1",
                "task_id": "task-1",
                "fingerprint": fingerprint,
                "raw_ref": ref.model_dump_json(),
                "payload": json.dumps(payload),
                "result_id": "legacy-result-1",
            },
        )
    engine.dispose()

    command.upgrade(config, "head")

    uow = SqliteUnitOfWork(database_url)
    persisted = uow.get_external_call("call-1")
    assert persisted.execution_context is None
    provider = ProviderMustNotRun()
    mismatched_context = context.model_copy(update={"idempotency_key": "foreign-key"})
    with pytest.raises(ValueError, match="execution context"):
        asyncio.run(
            ExternalCallRunner(SimpleNamespace(uow=uow, artifacts=artifacts)).resume(
                "call-1",
                provider=provider,
                validator=lambda raw: json.loads(raw),
                context=mismatched_context,
            )
        )
    result = asyncio.run(
        ExternalCallRunner(SimpleNamespace(uow=uow, artifacts=artifacts)).resume(
            "call-1",
            provider=provider,
            validator=lambda raw: json.loads(raw),
            context=context,
        )
    )
    assert result.result_id == "legacy-result-1"
    assert result.model_dump(mode="json")["payload"] == payload
    assert provider.call_count == 0


# Mutation caught: ORM create_schema drifts from migration head after lease tables are added.
def test_runtime_schema_still_matches_alembic_head_after_worker_migration(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.delenv("CO_SCIENTIST_DATABASE_URL", raising=False)
    project_root = Path(__file__).parents[3]
    database_url = f"sqlite:///{tmp_path / 'worker-head.db'}"
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")

    engine = create_engine(database_url)
    with engine.connect() as connection:
        differences = compare_metadata(
            MigrationContext.configure(
                connection,
                opts={"compare_server_default": True},
            ),
            Base.metadata,
        )
    engine.dispose()
    assert differences == []

    command.downgrade(config, "0001_core_tables")
    engine = create_engine(database_url)
    downgraded_columns = {
        column["name"] for column in inspect(engine).get_columns("external_calls")
    }
    engine.dispose()
    assert "execution_context_json" not in downgraded_columns
    assert "agent_result_json" not in downgraded_columns
