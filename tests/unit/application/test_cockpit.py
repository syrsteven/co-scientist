"""The cockpit must not upgrade databases, mutate runs, or call providers."""

from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from co_scientist.adapters.persistence.sqlite import RunRow, SqliteUnitOfWork
from co_scientist.application.cockpit import ReadOnlyUnitOfWork, list_runs, redact, snapshot


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "co-scientist.db"
    uow = SqliteUnitOfWork(f"sqlite:///{path}")
    uow.create_schema()
    with uow.session_factory.begin() as session:
        session.add(RunRow(run_id="demo", state="created", current_sequence=0,
                           manifest_json='{"goal":{"title":"Demo"}}'))
    uow.engine.dispose()
    return path


def test_missing_database_is_not_created(tmp_path: Path) -> None:
    path = tmp_path / "missing.db"
    with pytest.raises(FileNotFoundError):
        list_runs(path)
    assert not path.exists()


def test_list_is_read_only(database: Path) -> None:
    assert list_runs(database) == [
        {"runId": "demo", "state": "created", "sequence": 0, "updatedAt": None}
    ]


def test_sqlite_itself_rejects_writes(database: Path) -> None:
    uow = ReadOnlyUnitOfWork(database)
    try:
        with uow.session_factory() as session, pytest.raises(OperationalError):
            session.execute(text("UPDATE runs SET state='completed'"))
        assert list_runs(database)[0]["state"] == "created"
    finally:
        uow.engine.dispose()


def test_snapshot_uses_existing_export_shape(database: Path) -> None:
    before = database.read_bytes()
    result = snapshot(database, "demo")
    assert result["manifest"]["run_id"] == "demo"
    assert result["manifest"]["final_state"] == "created"
    assert result["tasks"] == result["hypotheses"] == result["events"] == []
    assert database.read_bytes() == before


def test_unknown_run_does_not_create_it(database: Path) -> None:
    with pytest.raises(KeyError):
        snapshot(database, "absent")
    assert len(list_runs(database)) == 1


def test_redaction_preserves_cost_measurements() -> None:
    assert redact({"nested": [{"api_key": "hidden", "Authorization": "hidden"}],
                   "input_tokens": 123}) == {
                       "nested": [{"api_key": "[redacted]", "Authorization": "[redacted]"}],
                       "input_tokens": 123,
                   }
