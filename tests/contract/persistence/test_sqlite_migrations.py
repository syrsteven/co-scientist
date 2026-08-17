import json
from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from co_scientist.adapters.persistence.migrations import (
    database_at_head,
    database_revision,
    run_execution_contract_diagnostic,
)


def _config(database_url: str) -> Config:
    project_root = Path(__file__).parents[3]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _schema_signature(database_url: str) -> dict[str, object]:
    engine = create_engine(database_url)
    inspector = inspect(engine)
    signature = {
        "columns": {
            table: sorted(
                (
                    column["name"],
                    str(column["type"]),
                    column["nullable"],
                    str(column["default"]),
                )
                for column in inspector.get_columns(table)
            )
            for table in sorted(inspector.get_table_names())
            if table != "alembic_version"
        },
        "indexes": {
            table: sorted(
                (
                    index["name"],
                    tuple(index["column_names"]),
                    bool(index["unique"]),
                )
                for index in inspector.get_indexes(table)
            )
            for table in sorted(inspector.get_table_names())
            if table != "alembic_version"
        },
        "unique_constraints": {
            table: sorted(
                (constraint["name"] or "", tuple(constraint["column_names"]))
                for constraint in inspector.get_unique_constraints(table)
            )
            for table in sorted(inspector.get_table_names())
            if table != "alembic_version"
        },
        "check_constraints": {
            table: sorted(
                (constraint["name"] or "", " ".join(constraint["sqltext"].split()))
                for constraint in inspector.get_check_constraints(table)
            )
            for table in sorted(inspector.get_table_names())
            if table != "alembic_version"
        },
        "foreign_keys": {
            table: sorted(
                (
                    constraint["name"] or "",
                    tuple(constraint["constrained_columns"]),
                    constraint["referred_table"],
                    tuple(constraint["referred_columns"]),
                )
                for constraint in inspector.get_foreign_keys(table)
            )
            for table in sorted(inspector.get_table_names())
            if table != "alembic_version"
        },
    }
    engine.dispose()
    return signature


# Mutation caught: drift between databases upgraded from 0002 and databases created at head.
def test_upgrade_from_0002_matches_fresh_head_schema_and_revision(tmp_path) -> None:
    upgraded_url = f"sqlite:///{tmp_path / 'upgraded.db'}"
    fresh_url = f"sqlite:///{tmp_path / 'fresh.db'}"
    upgraded_config = _config(upgraded_url)
    fresh_config = _config(fresh_url)

    command.upgrade(upgraded_config, "0002_external_call_recovery")
    command.upgrade(upgraded_config, "head")
    command.upgrade(fresh_config, "head")

    assert _schema_signature(upgraded_url) == _schema_signature(fresh_url)
    assert database_revision(upgraded_url) == "0003_worker_leases_budget_reservations"
    assert database_revision(fresh_url) == "0003_worker_leases_budget_reservations"
    assert database_at_head(upgraded_url)
    assert database_at_head(fresh_url)


# Mutation caught: migration omits lease/reservation constraints that make invalid rows impossible.
def test_head_schema_contains_worker_fences_budget_checks_and_indexes(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'head.db'}"
    command.upgrade(_config(database_url), "head")
    engine = create_engine(database_url)
    inspector = inspect(engine)

    task_columns = {column["name"]: column for column in inspector.get_columns("tasks")}
    assert {"lease_token", "heartbeat_at", "max_attempts"} <= set(task_columns)
    assert str(task_columns["max_attempts"]["default"]).strip("'\"") == "3"
    assert {index["name"] for index in inspector.get_indexes("tasks")} >= {
        "ix_tasks_claimable",
        "ix_tasks_lease_expiry",
    }
    assert {constraint["name"] for constraint in inspector.get_check_constraints("tasks")} >= {
        "ck_tasks_attempt_non_negative",
        "ck_tasks_max_attempts_positive",
        "ck_tasks_attempt_within_max",
    }
    assert {constraint["name"] for constraint in inspector.get_unique_constraints("tasks")} >= {
        "uq_tasks_run_id_idempotency_key",
        "uq_tasks_lease_token",
    }

    reservation_columns = {
        column["name"] for column in inspector.get_columns("budget_reservations")
    }
    assert reservation_columns >= {
        "reservation_id",
        "run_id",
        "task_id",
        "external_call_id",
        "idempotency_key",
        "state",
        "estimated_model_calls",
        "estimated_input_tokens",
        "estimated_output_tokens",
        "estimated_cost_usd",
        "estimated_hypotheses",
        "estimated_matches",
        "actual_model_calls",
        "actual_input_tokens",
        "actual_output_tokens",
        "actual_cost_usd",
        "actual_hypotheses",
        "actual_matches",
        "version",
        "created_at",
        "updated_at",
    }
    assert {index["name"] for index in inspector.get_indexes("budget_reservations")} >= {
        "ix_budget_reservations_run_state",
        "ix_budget_reservations_task",
    }
    assert len(inspector.get_foreign_keys("budget_reservations")) == 2
    engine.dispose()


# Mutation caught: silently treating a pre-0003 Run as executable after schema upgrade.
def test_upgraded_legacy_run_gets_stable_execution_contract_diagnostic(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'legacy.db'}"
    config = _config(database_url)
    command.upgrade(config, "0002_external_call_recovery")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO runs (run_id, state, current_sequence, manifest_json) "
                "VALUES (:run_id, 'running', 0, :manifest)"
            ),
            {"run_id": "r-legacy", "manifest": json.dumps({"budget": {}})},
        )
    engine.dispose()
    command.upgrade(config, "head")

    assert run_execution_contract_diagnostic(database_url, "r-legacy") == (
        "run r-legacy cannot execute: execution_contract_version 3 is required"
    )
