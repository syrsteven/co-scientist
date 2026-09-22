"""Read-only local cockpit bridge. No migrations, workers, or provider calls."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from co_scientist.adapters.persistence.sqlite import EventRow, RunRow, SqliteUnitOfWork
from co_scientist.application.output_retry import output_retry_preview
from co_scientist.export.run_export import SqliteRunReadModel


class ReadOnlyUnitOfWork(SqliteUnitOfWork):
    """Reuse the read boundary without the writer's WAL configuration hook."""

    def __init__(self, database: Path) -> None:
        uri = database.resolve(strict=True).as_uri() + "?mode=ro"
        self.engine = create_engine(
            "sqlite://", creator=lambda: sqlite3.connect(uri, uri=True, timeout=10)
        )
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False)


def redact(value: Any) -> Any:
    """Defense in depth for configuration objects; never redact token counts."""
    if isinstance(value, dict):
        return {
            key: "[redacted]"
            if str(key).lower().replace("-", "_") in {
                "api_key", "authorization", "access_token", "secret", "password",
            }
            else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def list_runs(database: Path) -> list[dict[str, Any]]:
    uow = ReadOnlyUnitOfWork(database)
    try:
        with uow.session_factory() as session:
            rows = session.execute(
                select(RunRow, func.max(EventRow.occurred_at))
                .outerjoin(EventRow, RunRow.run_id == EventRow.run_id)
                .group_by(RunRow.run_id)
            ).all()
            return [
                {"runId": row.run_id, "state": row.state, "sequence": row.current_sequence,
                 "updatedAt": updated.isoformat() + "Z" if updated else None}
                for row, updated in rows
            ]
    finally:
        uow.engine.dispose()


def snapshot(database: Path, run_id: str) -> dict[str, Any]:
    uow = ReadOnlyUnitOfWork(database)
    try:
        with SqliteRunReadModel(uow).snapshot(run_id) as model:
            result = {
                "manifest": model.run_manifest(run_id),
                "tournament_epochs": model.epochs(run_id),
                **{
                    name: getattr(model, name)(run_id)
                    for name in (
                        "events", "hypotheses", "hypothesis_projections", "reviews",
                        "novelty_assessments", "proximity", "matches", "ratings", "tasks",
                        "budget_reservations", "convergence_checkpoints", "stop_decisions",
                        "external_calls", "costs", "literature",
                    )
                },
            }
            result["output_retry"] = output_retry_preview(result, model.budget_snapshot(run_id))
        return dict(redact(result))
    finally:
        uow.engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("command", choices=["list", "snapshot"])
    parser.add_argument("run_id", nargs="?")
    args = parser.parse_args()
    if args.command == "snapshot" and not args.run_id:
        parser.error("snapshot requires run_id")
    result = (
        list_runs(args.database)
        if args.command == "list"
        else snapshot(args.database, args.run_id)
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
