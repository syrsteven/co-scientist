"""Minimal regressions, all synthetic/temporary and socket-denied by conftest."""

import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest
import yaml

from co_scientist.release.resources import ASSETS, package_file
from co_scientist.release.service import RunService


def prepared(tmp_path):
    goal = tmp_path / "goal.json"
    goal.write_text(
        json.dumps(
            {
                "title": "Synthetic mechanism",
                "goal": "Test recovery causality",
                "required_causal_chain": ["stress", "recovery"],
                "required_outputs": ["prediction"],
            }
        )
    )
    service = RunService(environment={})
    root = Path(service.create(goal, tmp_path / "runs", mock=True)["run_root"])
    return service, root, goal


@pytest.mark.asyncio
async def test_prepared_export_events_have_no_database_side_effect(tmp_path):
    service, root, _ = prepared(tmp_path)
    with pytest.raises(ValueError, match="not started"):
        await service.export(root)
    assert not (root / "runtime").exists()
    assert service.events(root) == []
    assert service.status(root)["state"] == "prepared"
    service.authorize(root, confirm=True, accept_usd="60")
    await service.execute(root, steps=1)
    assert service.status(root)["state"] == "running"


@pytest.mark.parametrize("field", ["watchdog", "role", "pricing", "capability", "budget"])
def test_custom_runtime_profiles_cannot_change_frozen_authorization(tmp_path, field):
    service, _, goal = prepared(tmp_path)
    value = yaml.safe_load(package_file("g3.yaml").read_text())
    runtime = value["execution_runtime"]
    # Mutate concrete existing fields, not merely an invalid/ignored unknown key.
    if field == "watchdog":
        runtime["performance"]["baseline"]["envelope"]["max_wall_seconds"] += 1
    elif field == "role":
        runtime["performance"]["baseline"]["roles"]["ranking"]["max_dispatches"] -= 1
    elif field == "budget":
        value["budget"]["max_usd"] = "59"
    elif field == "pricing":
        runtime["performance"]["baseline"]["pricing"]["input_usd_per_million"] = "0"
    else:
        runtime["performance"]["baseline"]["capabilities"][0]["max_context_tokens"] += 1
    path = tmp_path / "changed.yaml"
    path.write_text(yaml.safe_dump(value))
    # Pricing and the top-level budget overlay already had baseline guards;
    # do not mistake a different valid rejection message for a regression.
    with pytest.raises(ValueError):
        service.validate(goal, path)


def test_tokenizer_repair_corrupt_target(tmp_path, monkeypatch):
    from co_scientist.release.resources import install_openai_asset, resource_path

    original = resource_path("resource:o200k_base.tiktoken")
    monkeypatch.setenv("CO_SCIENTIST_RESOURCE_DIR", str(tmp_path))
    target = tmp_path / "o200k_base.tiktoken"
    target.write_bytes(b"interrupted installation")
    install_openai_asset(original)
    assert hashlib.sha256(target.read_bytes()).hexdigest() == ASSETS[target.name]


@pytest.mark.asyncio
async def test_export_rejects_concurrent_database_change(tmp_path, monkeypatch):
    from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork

    service, root, _ = prepared(tmp_path)
    service.authorize(root, confirm=True, accept_usd="60")
    await service.execute(root, steps=2)
    original = SqliteUnitOfWork.task_definition
    changed = False

    def racing(self, task_id):
        nonlocal changed
        if not changed:
            changed = True
            with sqlite3.connect(root / "runtime/co-scientist.db") as db:
                db.execute("UPDATE runs SET state='paused'")
        return original(self, task_id)

    monkeypatch.setattr(SqliteUnitOfWork, "task_definition", racing)
    with pytest.raises(ValueError, match="snapshot|Snapshot"):
        await service.export(root, tmp_path / "raced")
    assert changed
    assert not (tmp_path / "raced").exists()


@pytest.mark.asyncio
async def test_legacy_cockpit_reports_unsupported_g3_without_writer(tmp_path):
    from co_scientist.application.cockpit import snapshot

    service, root, _ = prepared(tmp_path)
    service.authorize(root, confirm=True, accept_usd="60")
    await service.execute(root, steps=1)
    db = root / "runtime/co-scientist.db"
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="UNSUPPORTED_LEGACY_G3"):
        snapshot(db, root.name)
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before


def test_inventory_strict_rejects_unlisted_file(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "release_verifier", Path("scripts/verify_release.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / "known").write_bytes(b"ok")
    (tmp_path / "SHA256SUMS.json").write_text(
        json.dumps({"files": {"known": hashlib.sha256(b"ok").hexdigest()}})
    )
    (tmp_path / "leak.env").write_text("not-a-real-secret")
    with pytest.raises(ValueError, match="UNLISTED"):
        module.verify(tmp_path, strict=True)


def test_verifier_cli_does_not_silently_accept_strict_flag(tmp_path):
    import shutil
    import subprocess
    import sys

    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copyfile("scripts/verify_release.py", scripts / "verify_release.py")
    (tmp_path / "SHA256SUMS.json").write_text(json.dumps({"files": {}}))
    (tmp_path / "unexpected-data").write_bytes(b"not in manifest")
    result = subprocess.run(
        [sys.executable, str(scripts / "verify_release.py"), "--strict"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0


def test_tokenizer_failure_before_publish_leaves_no_final_file(tmp_path, monkeypatch):
    import os

    from co_scientist.release.resources import install_openai_asset, resource_path

    original = resource_path("resource:o200k_base.tiktoken")
    monkeypatch.setenv("CO_SCIENTIST_RESOURCE_DIR", str(tmp_path))

    def fail(fd):
        raise OSError("injected fsync crash")

    monkeypatch.setattr(os, "fsync", fail)
    with pytest.raises(OSError, match="injected"):
        install_openai_asset(original)
    assert not (tmp_path / "o200k_base.tiktoken").exists()


def test_concurrent_tokenizer_installs_are_identical_and_idempotent(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    from co_scientist.release.resources import install_openai_asset, resource_path

    original = resource_path("resource:o200k_base.tiktoken")
    monkeypatch.setenv("CO_SCIENTIST_RESOURCE_DIR", str(tmp_path))
    with ThreadPoolExecutor(max_workers=4) as pool:
        paths = list(pool.map(install_openai_asset, [original] * 4))
    assert len(set(paths)) == 1
    target = Path(paths[0])
    assert hashlib.sha256(target.read_bytes()).hexdigest() == ASSETS[target.name]
    before = target.stat().st_mtime_ns
    install_openai_asset(tmp_path / "nonexistent-source")
    assert target.stat().st_mtime_ns == before
    assert not list(tmp_path.glob("*.tmp"))


def test_failed_install_preserves_corrupt_target_for_diagnostics(tmp_path, monkeypatch):
    from co_scientist.release.resources import install_openai_asset

    monkeypatch.setenv("CO_SCIENTIST_RESOURCE_DIR", str(tmp_path))
    target = tmp_path / "o200k_base.tiktoken"
    target.write_bytes(b"original corrupt data")
    invalid = tmp_path / "invalid"
    invalid.write_bytes(b"invalid replacement")
    with pytest.raises(ValueError, match="hash"):
        install_openai_asset(invalid)
    assert target.read_bytes() == b"original corrupt data"


def test_identical_profile_copy_is_supported(tmp_path):
    service, _, goal = prepared(tmp_path)
    profile = tmp_path / "same.yaml"
    profile.write_bytes(package_file("g3.yaml").read_bytes())
    assert service.validate(goal, profile)


@pytest.mark.asyncio
async def test_old_code_identity_still_blocks_execution_and_export(tmp_path):
    service, root, _ = prepared(tmp_path)
    plan_path = root / "plan.json"
    plan = json.loads(plan_path.read_bytes())
    plan["code_identity"] = "old-release-identity"
    plan_path.write_text(json.dumps(plan))
    # Authorization cannot reinterpret a Run prepared under another code version.
    with pytest.raises(ValueError, match="identity"):
        service.authorize(root, confirm=True, accept_usd="60")
    with pytest.raises(ValueError, match="identity"):
        await service.export(root)


@pytest.mark.asyncio
@pytest.mark.parametrize("store", ["ledger", "artifacts"])
async def test_export_detects_other_store_races(tmp_path, monkeypatch, store):
    from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork

    service, root, _ = prepared(tmp_path)
    service.authorize(root, confirm=True, accept_usd="60")
    await service.execute(root, steps=2)
    original = SqliteUnitOfWork.task_definition
    changed = False

    def racing(self, task_id):
        nonlocal changed
        if not changed:
            changed = True
            if store == "ledger":
                path = next(root.rglob("dispatch.sqlite3"))
                with sqlite3.connect(path) as db:
                    db.execute("UPDATE policy SET blocked='injected export race'")
            else:
                path = next(root.rglob("*.manifest.json"))
                path.write_bytes(path.read_bytes() + b" ")
        return original(self, task_id)

    monkeypatch.setattr(SqliteUnitOfWork, "task_definition", racing)
    with pytest.raises(ValueError, match="snapshot|identity|hash"):
        await service.export(root, tmp_path / "raced")
    assert changed
    assert not (tmp_path / "raced").exists()
