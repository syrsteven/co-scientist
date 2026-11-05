"""OFFLINE explicit P09 retry authorization; no real DB/key/provider access."""

import copy
import json
import os
import runpy
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

from co_scientist_next import review_trial as trial
from co_scientist_next.candidate_review import CandidateReviewService
from co_scientist_next.generation_migration import ReadOnlyStore
from co_scientist_next.responses_model import OpenAIResponses
from co_scientist_next.store import Store, encode

H = runpy.run_path(str(Path(__file__).with_name("test_review_trial.py")))
R = H["R"]


def uncertain(tmp_path, monkeypatch):
    _, db, package, _ = H["prepared"](tmp_path)
    frozen = trial.read(package / "trial.json")
    wire = R["Wire"]([ConnectionResetError()])
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_: wire)
    with Store(db) as s:
        g = CandidateReviewService(
            s,
            OpenAIResponses(frozen["model_config"], R["SECRET"], authorized=True),
            development=True,
        )
        a = g.submit(frozen["run_id"], frozen["request_ids"]["P09"], frozen["p09_request"])
        g.execute(a["request_id"])
        old = s.one("SELECT * FROM attempts WHERE task_id=?", (a["task_id"],))
    monkeypatch.setattr(trial, "RECOVERY_TASK", a["task_id"])
    monkeypatch.setattr(trial, "RECOVERY_ATTEMPT", old["id"])
    return db, package, frozen, wire, a, old


def recover(db, package, old):
    return trial.recover_p09(db, package, old["id"], acknowledgements=trial.RECOVERY_ACKS)


def test_explicit_recovery_requires_all_acknowledgements_before_any_write_or_key(
    tmp_path, monkeypatch
):
    db, package, _, _, _, old = uncertain(tmp_path, monkeypatch)
    before = trial.sha_file(db)
    monkeypatch.setattr(
        trial, "load_credential", lambda **_: pytest.fail("No key without authorization")
    )
    with pytest.raises(ValueError):
        trial.recover_p09(db, package, old["id"], acknowledgements=set())
    with pytest.raises(ValueError):
        trial.recover_p09(db, package, "wrong-attempt", acknowledgements=trial.RECOVERY_ACKS)
    assert trial.sha_file(db) == before


def test_one_retry_same_request_lineage_repeat_command_and_id_query_only(tmp_path, monkeypatch):
    db, package, _, wire, a, old = uncertain(tmp_path, monkeypatch)
    monkeypatch.setattr(trial, "load_credential", lambda **_: R["SECRET"])
    wire.responses.append(R["envelope"]("queued"))
    recover(db, package, old)
    monkeypatch.setattr(
        trial, "load_credential", lambda **_: pytest.fail("Repeated command must not load key")
    )
    recover(db, package, old)
    with ReadOnlyStore(db) as s:
        attempts = s.rows(
            "SELECT * FROM attempts WHERE task_id=? ORDER BY ordinal", (a["task_id"],)
        )
        assert len(attempts) == 2 and attempts[1]["previous_id"] == old["id"]
        assert (
            attempts[1]["request"] == old["request"] and attempts[1]["call_key"] == old["call_key"]
        )
        assert {k: v for k, v in attempts[0].items() if k != "retry_authorization"} == {
            k: v for k, v in old.items() if k != "retry_authorization"
        }
        assert attempts[0]["retry_authorization"] and attempts[0]["status"] == "uncertain"
    monkeypatch.setattr(trial, "load_credential", lambda **_: R["SECRET"])
    wire.responses.append(R["envelope"]("completed", encode(H["decision"](json.loads(a["input"])))))
    trial.operate(db, package, "P09", query=True)
    assert [v[0] for v in wire.sent] == ["POST", "POST", "GET"]
    assert trial.assemble_p10(db, package, tmp_path / "P10")["assembled"]


def test_second_uncertain_stops_and_does_not_authorize_third(tmp_path, monkeypatch):
    db, package, _, wire, a, old = uncertain(tmp_path, monkeypatch)
    monkeypatch.setattr(trial, "load_credential", lambda **_: R["SECRET"])
    wire.responses.append(ConnectionResetError())
    recover(db, package, old)
    monkeypatch.setattr(
        trial, "load_credential", lambda **_: pytest.fail("Third submission forbidden")
    )
    recover(db, package, old)
    with ReadOnlyStore(db) as s:
        attempts = s.rows(
            "SELECT * FROM attempts WHERE task_id=? ORDER BY ordinal", (a["task_id"],)
        )
        assert len(attempts) == 2 and attempts[1]["status"] == "uncertain"
        assert not attempts[1]["retry_authorization"]
        assert not s.rows("SELECT * FROM candidate_review_actions WHERE operation='P10'")
    assert [v[0] for v in wire.sent] == ["POST", "POST"]


def test_frozen_request_mismatch_is_rejected_before_authorization(tmp_path, monkeypatch):
    db, package, _, wire, _, old = uncertain(tmp_path, monkeypatch)
    with Store(db) as s, s.db:
        request = json.loads(old["request"])
        request["actual_request"]["body"]["max_output_tokens"] = 999
        s.db.execute("UPDATE attempts SET request=? WHERE id=?", (encode(request), old["id"]))
    monkeypatch.setattr(
        trial, "load_credential", lambda **_: pytest.fail("Changed input must not read key")
    )
    with pytest.raises(ValueError):
        recover(db, package, old)
    assert len(wire.sent) == 1
    with ReadOnlyStore(db) as s:
        assert not s.one("SELECT retry_authorization FROM attempts WHERE id=?", (old["id"],))[
            "retry_authorization"
        ]


def test_reservation_before_send_is_idempotent_and_never_globally_unblocks(tmp_path, monkeypatch):
    db, package, f, wire, _, old = uncertain(tmp_path, monkeypatch)
    with Store(db) as s:
        _, service = trial.validate_package(s, package)
        trial.reserve_p09_retry(service, f, old["id"])
        trial.reserve_p09_retry(service, f, old["id"])
        assert (
            len(s.rows("SELECT * FROM execution_facts WHERE kind='p09_single_retry_reserved'")) == 1
        )
    monkeypatch.setattr(trial, "load_credential", lambda **_: R["SECRET"])
    wire.responses.append(R["envelope"]("queued"))
    recover(db, package, old)
    assert [v[0] for v in wire.sent] == ["POST", "POST"]


def test_crash_during_retry_new_process_marks_only_retry_uncertain_no_send(tmp_path, monkeypatch):
    db, package, _, _, a, old = uncertain(tmp_path, monkeypatch)
    code = r"""
import os,sys,urllib.request
from co_scientist_next import review_trial as t
from co_scientist_next.responses_model import OpenAIResponses
t.RECOVERY_TASK=sys.argv[3];t.RECOVERY_ATTEMPT=sys.argv[4]
t.load_credential=lambda **_:'OFFLINE-KEY'
OpenAIResponses.__call__=lambda self,req:os._exit(79)
t.recover_p09(sys.argv[1],sys.argv[2],sys.argv[4],acknowledgements=t.RECOVERY_ACKS)
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(db), str(package), a["task_id"], old["id"]],
        env={**os.environ, "PYTHONPATH": "src"},
        capture_output=True,
        check=False,
    )
    assert result.returncode == 79
    monkeypatch.setattr(
        trial, "load_credential", lambda **_: pytest.fail("Interrupted retry cannot resend")
    )
    recover(db, package, old)
    with ReadOnlyStore(db) as s:
        attempts = s.rows(
            "SELECT * FROM attempts WHERE task_id=? ORDER BY ordinal", (a["task_id"],)
        )
        assert len(attempts) == 2 and attempts[1]["status"] == "uncertain"
        assert attempts[1]["previous_id"] == old["id"]


def test_existing_response_is_not_overwritten_or_retried(tmp_path, monkeypatch):
    db, package, _, _, _, old = uncertain(tmp_path, monkeypatch)
    with Store(db) as s, s.db:
        s.db.execute(
            "UPDATE attempts SET response=? WHERE id=?",
            (encode({"original_response_requires_inspection": True}), old["id"]),
        )
    monkeypatch.setattr(
        trial,
        "load_credential",
        lambda **_: pytest.fail("Existing evidence requires read-only inspection"),
    )
    with pytest.raises(ValueError):
        recover(db, package, old)


def test_saved_retry_id_queries_in_a_new_process_without_another_post(tmp_path, monkeypatch):
    db, package, _, wire, a, old = uncertain(tmp_path, monkeypatch)
    monkeypatch.setattr(trial, "load_credential", lambda **_: R["SECRET"])
    wire.responses.append(R["envelope"]("queued"))
    recover(db, package, old)
    output = encode(H["decision"](json.loads(a["input"])))
    code = r"""
import sys,runpy,urllib.request
from co_scientist_next import review_trial as t
r=runpy.run_path(sys.argv[3]);wire=r['Wire']([r['envelope']('completed',sys.argv[4])])
urllib.request.build_opener=lambda *_:wire
t.load_credential=lambda **_:r['SECRET']
t.operate(sys.argv[1],sys.argv[2],'P09',query=True)
assert [v[0] for v in wire.sent]==['GET']
print('Only GET of saved retry ID')
"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            code,
            str(db),
            str(package),
            str(Path(__file__).with_name("test_responses_background.py")),
            output,
        ],
        env={**os.environ, "PYTHONPATH": "src"},
        capture_output=True,
        text=True,
        check=True,
    )
    assert "Only GET" in result.stdout
    assert [v[0] for v in wire.sent] == ["POST", "POST"]


def test_unrelated_uncertain_call_is_not_waived_by_recovery(tmp_path, monkeypatch):
    db, package, _, wire, a, old = uncertain(tmp_path, monkeypatch)
    with Store(db) as s, s.db:
        task = s.one("SELECT * FROM tasks WHERE id=?", (a["task_id"],))
        s.db.execute(
            "INSERT INTO tasks VALUES(?,?,?,?,?,?,?)",
            ("OFFLINE-unrelated", task["run_id"], 999, "unrelated", task["input"], "blocked", None),
        )
        row = copy.deepcopy(old)
        row.update(
            id="OFFLINE-unrelated-attempt", task_id="OFFLINE-unrelated", retry_authorization=None
        )
        keys = tuple(row)
        s.db.execute(
            "INSERT INTO attempts ("
            + ",".join(keys)
            + ") VALUES ("
            + ",".join("?" for _ in keys)
            + ")",
            tuple(row[k] for k in keys),
        )
    monkeypatch.setattr(
        trial, "load_credential", lambda **_: pytest.fail("Other blocked call cannot be waived")
    )
    with pytest.raises(ValueError, match="Other unresolved"):
        recover(db, package, old)
    assert len(wire.sent) == 1


def test_recovery_reservation_rolls_back_when_m15_authorization_fails(tmp_path, monkeypatch):
    db, package, f, _, _, old = uncertain(tmp_path, monkeypatch)
    with Store(db) as s:
        _, g = trial.validate_package(s, package)

        def fail(*_):
            raise ValueError("OFFLINE authorization interruption")

        monkeypatch.setattr(s, "authorize_uncertain_retry", fail)
        with pytest.raises(ValueError):
            trial.reserve_p09_retry(g, f, old["id"])
        assert not s.rows("SELECT * FROM execution_facts WHERE kind='p09_single_retry_reserved'")
        assert (
            s.one("SELECT status FROM tasks WHERE id=?", (old["task_id"],))["status"] == "blocked"
        )


def test_completed_response_saved_before_crash_applies_locally_without_key(tmp_path, monkeypatch):
    from co_scientist_next.candidate_review import RemoteReview

    db, package, _, wire, a, old = uncertain(tmp_path, monkeypatch)
    monkeypatch.setattr(trial, "load_credential", lambda **_: R["SECRET"])
    wire.responses.append(R["envelope"]("completed", encode(H["decision"](json.loads(a["input"])))))
    finish = RemoteReview.finish

    def crash(*_):
        raise SystemExit("OFFLINE crash after persisted ID and response")

    monkeypatch.setattr(RemoteReview, "finish", crash)
    with pytest.raises(SystemExit):
        recover(db, package, old)
    monkeypatch.setattr(RemoteReview, "finish", finish)
    monkeypatch.setattr(
        trial, "load_credential", lambda **_: pytest.fail("Saved completion replays locally")
    )
    saved = recover(db, package, old)
    assert saved["sent"] is False
    assert (
        saved["review_records"]["actions"][0]["result"]["artifact"]["decision_per_approved_policy"]
        == "pass"
    )
    assert [v[0] for v in wire.sent] == ["POST", "POST"]
