import pytest

from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork
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
