from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from alembic import command
from co_scientist.adapters.persistence.sqlite import Base, SqliteUnitOfWork
from co_scientist.events.models import NewEvent
from co_scientist.ports.event_store import ConcurrencyConflict


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
