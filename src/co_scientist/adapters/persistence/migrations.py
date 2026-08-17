"""Application-facing migration and execution-contract diagnostics."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

EXECUTION_CONTRACT_VERSION = 3


def _alembic_config() -> Config:
    project_root = Path(__file__).parents[4]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    return config


def database_revision(database_url: str) -> str | None:
    engine = create_engine(database_url)
    try:
        if "alembic_version" not in inspect(engine).get_table_names():
            return None
        with engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one_or_none()
        return str(revision) if revision is not None else None
    finally:
        engine.dispose()

def database_at_head(database_url: str) -> bool:
    return database_revision(database_url) == ScriptDirectory.from_config(
        _alembic_config()
    ).get_current_head()


def execution_contract_diagnostic(run_id: str, manifest: dict[str, Any]) -> str | None:
    version = manifest.get("execution_contract_version")
    if isinstance(version, int) and not isinstance(version, bool) and version == 3:
        return None
    return f"run {run_id} cannot execute: execution_contract_version 3 is required"


def run_execution_contract_diagnostic(database_url: str, run_id: str) -> str | None:
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            manifest_json = connection.execute(
                text("SELECT manifest_json FROM runs WHERE run_id = :run_id"),
                {"run_id": run_id},
            ).scalar_one_or_none()
        if manifest_json is None:
            raise KeyError(f"unknown run: {run_id}")
        manifest = json.loads(manifest_json)
        if not isinstance(manifest, dict):
            raise TypeError(f"Run manifest is not an object: {run_id}")
        return execution_contract_diagnostic(run_id, manifest)
    finally:
        engine.dispose()
