import asyncio
import json
import shutil

import pytest
from sqlalchemy import select

from co_scientist.adapters.persistence.sqlite import (
    ExternalCallRow,
    RunRow,
    SqliteUnitOfWork,
    TaskRow,
)
from co_scientist.application.cockpit import snapshot
from co_scientist.application.cockpit_retry import MAX_RAW_BYTES, read_raw, retry_output
from tests.scenario.test_explicit_output_retry import BAD_RAW, RUN, create_failed_run


@pytest.fixture(scope="module")
def seed(tmp_path_factory):
    root = tmp_path_factory.mktemp("cockpit-retry-seed")
    asyncio.run(create_failed_run(root))
    return root / "data"


@pytest.fixture
def case(tmp_path, seed):
    shutil.copytree(seed, tmp_path / "data")
    db = tmp_path / "data/co-scientist.db"
    data = snapshot(db, RUN)
    p = data["output_retry"]
    return db, data, {"external_call_id": p["external_call_id"], "expected_sequence": p["expected_sequence"], "confirmed": True}


def test_retry_bridge_shares_cli_boundary_without_provider_or_migration(case):
    db, before, payload = case
    preview = before["output_retry"]
    assert preview["eligible"] and preview["attempt"] == 1 and preview["max_attempts"] == 3
    assert preview["budget"]["usage"]["model_calls"] == 1
    assert preview["budget"]["additional_estimate"]["model_calls"] == 1
    raw = read_raw(db, RUN, payload["external_call_id"])
    assert raw["integrity_verified"] and raw["text"].encode() == BAD_RAW
    result = retry_output(db, RUN, payload)
    assert result["ok"] and result["worker_started"] is False
    assert result["authorized_attempt"] == 2 and "worker run" in result["worker_command"]
    after = snapshot(db, RUN)
    assert after["manifest"]["final_state"] == "running" and after["output_retry"] is None
    assert after["costs"] == before["costs"] and after["external_calls"] == before["external_calls"]
    assert retry_output(db, RUN, payload)["status"] == 409
    assert snapshot(db, RUN) == after


@pytest.mark.parametrize("change, status", [
    ({"confirmed": False}, 422), ({"confirmed": "true"}, 422),
    ({"expected_sequence": True}, 422), ({"expected_sequence": 0}, 409),
    ({"external_call_id": "different-run-call"}, 404), ({"database": "/tmp/injected"}, 422),
    ({"run_id": "injected"}, 422),
])
def test_rejected_web_requests_do_not_write(case, change, status):
    db, before, payload = case
    assert retry_output(db, RUN, {**payload, **change})["status"] == status
    assert snapshot(db, RUN) == before


@pytest.mark.parametrize("limit", ["attempts", "budget"])
def test_preview_disables_unavailable_retry_and_writer_also_refuses(case, limit):
    db, _, payload = case
    uow = SqliteUnitOfWork(f"sqlite:///{db}")
    with uow.session_factory.begin() as session:
        if limit == "attempts":
            session.scalar(select(TaskRow).where(TaskRow.attempt == 1)).max_attempts = 1
        else:
            row = session.get(RunRow, RUN)
            manifest = json.loads(row.manifest_json)
            manifest["budget"]["max_model_calls"] = 1
            row.manifest_json = json.dumps(manifest)
    before = snapshot(db, RUN)
    assert before["output_retry"]["eligible"] is False and before["output_retry"]["reasons"]
    assert retry_output(db, RUN, payload)["status"] == 409
    assert snapshot(db, RUN) == before
    uow.engine.dispose()


@pytest.mark.parametrize("bad", ["hash", "symlink", "oversized"])
def test_raw_safety_and_integrity_fail_closed(case, tmp_path, bad):
    db, before, payload = case
    call = before["external_calls"][0]
    ref = call["raw_artifact_ref"]
    path = db.parent / "artifacts" / ref["path"]
    if bad == "hash":
        path.write_bytes(b"changed")
    elif bad == "symlink":
        outside = tmp_path / "outside"
        outside.write_bytes(BAD_RAW)
        path.unlink()
        path.symlink_to(outside)
    else:
        uow = SqliteUnitOfWork(f"sqlite:///{db}")
        with uow.session_factory.begin() as session:
            row = session.get(ExternalCallRow, call["external_call_id"])
            ref["byte_length"] = MAX_RAW_BYTES + 1
            row.raw_artifact_ref_json = json.dumps(ref)
        uow.engine.dispose()
    data = snapshot(db, RUN)
    status = 413 if bad == "oversized" else 409
    result = read_raw(db, RUN, payload["external_call_id"])
    assert result["status"] == status and "text" not in result
    assert retry_output(db, RUN, payload)["status"] == status
    assert snapshot(db, RUN) == data


def test_raw_is_run_scoped_and_missing_database_not_created(case, tmp_path):
    db, _, payload = case
    assert read_raw(db, "another-run", payload["external_call_id"])["status"] == 404
    assert read_raw(db, RUN, "../../outside")["status"] == 404
    absent = tmp_path / "absent/co-scientist.db"
    assert retry_output(absent, RUN, payload)["status"] == 404
    assert not absent.parent.exists()
