"""OFFLINE migration fixtures only; never migrate the real Run or load credentials."""

import hashlib
import json
import os
import runpy
import sqlite3
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

from co_scientist_next.contracts import TransportUncertain
from co_scientist_next.generation import GenerationService
from co_scientist_next.generation_migration import (
    ACKS,
    MigrationService,
    ReadOnlyStore,
    digest,
    existing,
)
from co_scientist_next.reading_model import OpenAIChat
from co_scientist_next.responses_model import OpenAIResponses
from co_scientist_next.store import Store, encode

H = runpy.run_path(str(Path(__file__).with_name("test_responses_background.py")))
CONFIG = H["CONFIG"]
CHAT = {
    k: v for k, v in CONFIG.items() if k not in ("store", "retention_ack", "total_wait_seconds")
}
CHAT["endpoint"] = "https://api.openai.com/v1/chat/completions"
ACK = dict.fromkeys(ACKS, True)


def source_fixture(s):
    from unittest.mock import patch

    run, bg, req = H["H"]["prepared"](s)
    req["candidate_id"] = "planned-p08-direct"
    adapter = OpenAIChat(CHAT, "OFFLINE-SOURCE-NOT-A-REAL-KEY", authorized=True)
    g = GenerationService(s, adapter)
    a = g.submit(run, "offline-original-direct", req)

    def lost(*_):
        raise TransportUncertain("http_protocol", "waiting_headers", "REMOTE_DISCONNECTED")

    with patch.object(OpenAIChat, "__call__", lost):
        g.execute(a["request_id"])
        first = s.one("SELECT id FROM attempts WHERE task_id=?", (a["task_id"],))["id"]
        s.authorize_uncertain_retry(
            first, "OFFLINE fixture explicitly accepts second ambiguous call"
        )
        s.retry_task(a["task_id"], "OFFLINE second original Attempt")
        g.execute(a["request_id"])
    attempts = s.rows("SELECT * FROM attempts WHERE task_id=? ORDER BY ordinal", (a["task_id"],))
    request = {
        "source_task_id": a["task_id"],
        "source_attempt_ids": [r["id"] for r in attempts],
        "seed_id": req["seed_id"],
        "readiness_ref": req["readiness_ref"],
        "packet_ref": req["packet_ref"],
        "request_id": "offline-migrated-direct",
        "candidate_id": "planned-p08-direct-responses",
    }
    return run, bg, a, request


def historical(s, task):
    return {
        "task": s.one("SELECT * FROM tasks WHERE id=?", (task,)),
        "action": s.one("SELECT * FROM generation_actions WHERE task_id=?", (task,)),
        "attempts": s.rows("SELECT * FROM attempts WHERE task_id=? ORDER BY ordinal", (task,)),
    }


def confirm(m, run, request):
    preview = m.preview(run, request)
    return m.confirm(run, request, preview["preview_hash"], ACK)


def test_readonly_preview_exact_science_and_atomic_idempotent_confirmation(tmp_path):
    db = tmp_path / "fixture.sqlite"
    with Store(db) as s:
        run, _, a, req = source_fixture(s)
        before = historical(s, a["task_id"])
        m = MigrationService(s, CONFIG)
        dump = "\n".join(s.db.iterdump())
        preview = m.preview(run, req)
        assert "\n".join(s.db.iterdump()) == dump
        assert preview["risk"]["old_calls_may_have_executed_and_charged"]
        assert (
            preview["risk"]["new_store"]
            and not preview["risk"]["paid_execution_authorized_by_migration"]
        )
        assert preview["new_config_sha256"] == digest(preview["new_config"])
        assert "credential_configured" not in preview["new_config"]
        original = json.loads(a["input"])
        assert preview["successor_action"]["input"] == {
            **original,
            "candidate_id_from_caller": req["candidate_id"],
        }
        assert (
            preview["actual_submission"]["messages"][:2] == GenerationService.messages(original)[:2]
        )
        created = m.confirm(run, req, preview["preview_hash"], ACK)
        assert not created["execution_authorization"]
        assert (
            created["source_task_id"] == a["task_id"]
            and created["successor_task_id"] != a["task_id"]
        )
        new = s.one("SELECT * FROM tasks WHERE id=?", (created["successor_task_id"],))
        assert new["run_id"] == run and new["status"] == "ready"
        assert not s.rows("SELECT id FROM attempts WHERE task_id=?", (new["id"],))
        dump = "\n".join(s.db.iterdump())
        assert m.confirm(run, req, preview["preview_hash"], ACK) == created
        assert "\n".join(s.db.iterdump()) == dump
        assert historical(s, a["task_id"]) == before
        with pytest.raises(ValueError, match="already has a different"):
            confirm(m, run, {**req, "candidate_id": "second-successor-prohibited"})
        assert len(s.rows("SELECT * FROM generation_migrations")) == 1
        old_db = hashlib.sha256(db.read_bytes()).hexdigest()
    with ReadOnlyStore(db) as reader:
        assert MigrationService(reader, CONFIG).preview(run, req) == preview
        with pytest.raises(sqlite3.OperationalError):
            reader.db.execute("CREATE TABLE forbidden (id TEXT)")
    assert hashlib.sha256(db.read_bytes()).hexdigest() == old_db


@pytest.mark.parametrize(
    "field", ["seed_id", "packet_ref", "readiness_ref", "source_task_id", "source_attempt_ids"]
)
def test_cross_scope_rejected(tmp_path, field):
    with Store(tmp_path / "foreign.sqlite") as s:
        run, bg, _, req = source_fixture(s)
        m = MigrationService(s, CONFIG)
        with Store(tmp_path / "other-run.sqlite") as other_store:
            foreign, _, _, other = source_fixture(other_store)
        if field == "seed_id":
            other[field] = bg.seeds(run)[-1]["id"]
        if field in ("packet_ref", "readiness_ref"):
            other[field] = "foreign-seed-" + other[field]
        with pytest.raises(ValueError):
            m.preview(foreign, req)
        with pytest.raises((ValueError, KeyError)):
            confirm(m, run, {**req, field: other[field]})
        assert not s.rows("SELECT * FROM generation_migrations")


@pytest.mark.parametrize(
    "field",
    [
        "goal_context",
        "seed_brief",
        "actual_frozen_seed_background_packet",
        "readiness_record",
        "mode",
    ],
)
def test_frozen_science_difference_rejected_without_writes(tmp_path, field):
    with Store(tmp_path / "changed.sqlite") as s:
        run, _, a, req = source_fixture(s)
        payload = json.loads(a["input"])
        payload[field] = "OFFLINE tampered scientific input"
        with s.db:
            s.db.execute(
                "UPDATE generation_actions SET input=? WHERE task_id=?",
                (encode(payload), a["task_id"]),
            )
        m = MigrationService(s, CONFIG)
        with pytest.raises(ValueError, match="scientific input"):
            confirm(m, run, req)
        assert not s.rows("SELECT * FROM generation_migrations")


def test_prompt_request_difference_and_stale_preview_rejected(tmp_path):
    with Store(tmp_path / "stale.sqlite") as s:
        run, _, a, req = source_fixture(s)
        m = MigrationService(s, CONFIG)
        preview = m.preview(run, req)
        with pytest.raises(ValueError, match="Stale"):
            m.confirm(
                run,
                {**req, "candidate_id": "another-candidate-identity"},
                preview["preview_hash"],
                ACK,
            )
        attempt = s.one("SELECT * FROM attempts WHERE task_id=? AND ordinal=2", (a["task_id"],))
        wire = json.loads(attempt["request"])
        wire["messages"][1]["content"] += " OFFLINE changed Prompt"
        with s.db:
            s.db.execute("UPDATE attempts SET request=? WHERE id=?", (encode(wire), attempt["id"]))
        with pytest.raises(ValueError, match="Prompt"):
            m.confirm(run, req, preview["preview_hash"], ACK)
        assert not s.rows("SELECT * FROM generation_migrations")


@pytest.mark.parametrize("key", sorted(ACKS))
def test_explicit_confirmation_is_required(tmp_path, key):
    with Store(tmp_path / "ack.sqlite") as s:
        run, _, _, req = source_fixture(s)
        m = MigrationService(s, CONFIG)
        p = m.preview(run, req)
        with pytest.raises(ValueError, match="acknowledgements"):
            m.confirm(run, req, p["preview_hash"], {**ACK, key: False})
        assert not s.rows("SELECT * FROM generation_migrations")


def test_transaction_failure_rolls_back_every_reservation(tmp_path, monkeypatch):
    with Store(tmp_path / "atomic.sqlite") as s:
        run, _, a, req = source_fixture(s)
        m = MigrationService(s, CONFIG)
        before = "\n".join(s.db.iterdump())
        original = s.fact

        def fail(*args):
            if args[1] == "migration_reserved_without_send":
                raise RuntimeError("OFFLINE interrupt before transaction commit")
            return original(*args)

        monkeypatch.setattr(s, "fact", fail)
        with pytest.raises(RuntimeError):
            confirm(m, run, req)
        assert "\n".join(s.db.iterdump()) == before
        assert s.run(run)["status"] == "blocked" and s.tasks(run)[-1]["id"] == a["task_id"]
        monkeypatch.setattr(s, "fact", original)
        confirm(m, run, req)
        assert len(s.rows("SELECT * FROM generation_migrations")) == 1


def test_execution_requires_new_consent_and_scope_is_not_global(tmp_path, monkeypatch):
    with Store(tmp_path / "execute.sqlite") as s:
        run, _, a, req = source_fixture(s)
        before = historical(s, a["task_id"])
        m = MigrationService(s, CONFIG)
        created = confirm(m, run, req)
        adapter = OpenAIResponses(CONFIG, H["SECRET"], authorized=True)
        g = GenerationService(s, adapter)
        with pytest.raises(ValueError, match="separately authorize"):
            g.execute(req["request_id"])
        with pytest.raises(ValueError, match="Unresolved external"):
            g.clear_calls(run)
        g.clear_calls(run, created["successor_task_id"])
        with pytest.raises(ValueError):
            g.submit(
                run,
                "ordinary-request-not-allowed",
                {**json.loads(a["request"]), "candidate_id": "not-this-successor"},
            )
        wire = H["Wire"]([H["envelope"]()])
        monkeypatch.setattr(urllib.request, "build_opener", lambda *_: wire)
        record = g.execute(req["request_id"], authorize_migrated_execution=True)["actions"][-1]
        assert record["remote"]["response_id"] == "resp_OFFLINE1"
        assert (
            record["migration"]["execution_authorization"]["task_id"]
            == created["successor_task_id"]
        )
        attempt = s.one(
            "SELECT request FROM attempts WHERE task_id=?", (created["successor_task_id"],)
        )
        assert json.loads(attempt["request"]) == created["preview"]["actual_submission"]
        g.execute(req["request_id"], recover=True)
        assert [x[0] for x in wire.sent] == ["POST"]
        assert historical(s, a["task_id"]) == before


def test_other_unresolved_calls_never_exempt_and_history_mutation_stops_successor(tmp_path):
    with Store(tmp_path / "scope.sqlite") as s:
        run, _, a, req = source_fixture(s)
        m = MigrationService(s, CONFIG)
        created = confirm(m, run, req)
        g = GenerationService(s, OpenAIResponses(CONFIG, H["SECRET"], authorized=True))
        # Additional unresolved call on the source is not in the authorized snapshot.
        original = s.one("SELECT * FROM attempts WHERE task_id=? AND ordinal=2", (a["task_id"],))
        with s.db:
            s.db.execute(
                "INSERT INTO attempts(id,task_id,call_key,target,request,ordinal,status,usage,started_at) VALUES(?,?,?,?,?,1,'uncertain',?,?)",
                (
                    "foreign-unresolved-call",
                    a["task_id"],
                    "other-side-effect",
                    "unrelated",
                    "{}",
                    original["usage"],
                    original["started_at"],
                ),
            )
        with pytest.raises(ValueError, match="Unresolved external"):
            g.execute(req["request_id"], authorize_migrated_execution=True)
        assert not s.rows(
            "SELECT id FROM attempts WHERE task_id=?", (created["successor_task_id"],)
        )
        with s.db:
            s.db.execute("DELETE FROM attempts WHERE id='foreign-unresolved-call'")
            s.db.execute("UPDATE attempts SET error='{}' WHERE id=?", (original["id"],))
        with pytest.raises(ValueError, match="Historical Attempt"):
            g.execute(req["request_id"], authorize_migrated_execution=True)


@pytest.mark.parametrize("state", ["uncertain", "failed", "incomplete"])
def test_successor_failure_does_not_resubmit_or_allow_remigration(tmp_path, monkeypatch, state):
    with Store(tmp_path / "failure.sqlite") as s:
        run, _, a, req = source_fixture(s)
        m = MigrationService(s, CONFIG)
        created = confirm(m, run, req)
        outcome = TimeoutError(H["SECRET"]) if state == "uncertain" else H["envelope"](state, "{}")
        wire = H["Wire"]([outcome])
        monkeypatch.setattr(urllib.request, "build_opener", lambda *_: wire)
        g = GenerationService(s, OpenAIResponses(CONFIG, H["SECRET"], authorized=True))
        record = g.execute(req["request_id"], authorize_migrated_execution=True)["actions"][-1]
        assert not (record["result"] or {}).get("candidate")
        g.execute(req["request_id"], recover=True)
        assert len(wire.sent) == 1
        assert confirm(m, run, req)["successor_task_id"] == created["successor_task_id"]
        assert historical(s, a["task_id"])["attempts"][1]["status"] == "uncertain"


def test_cross_process_resume_same_id_and_complete_without_recreate(tmp_path):
    db = tmp_path / "resume.sqlite"
    script = r"""
import os,runpy,sys,urllib.request
h=runpy.run_path(sys.argv[2])
with h['Store'](sys.argv[1]) as s:
 run,bg,a,req=h['source_fixture'](s)
 m=h['MigrationService'](s,h['CONFIG']);h['confirm'](m,run,req)
 wire=h['H']['Wire']([h['H']['envelope']()]);urllib.request.build_opener=lambda *_:wire
 g=h['GenerationService'](s,h['OpenAIResponses'](h['CONFIG'],h['H']['SECRET'],authorized=True))
 from co_scientist_next.remote_generation import RemoteP08
 RemoteP08.wait=lambda *_:os._exit(0)
 g.execute(req['request_id'],authorize_migrated_execution=True)
"""
    subprocess.run(
        [sys.executable, "-c", script, str(db), str(Path(__file__).resolve())],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")},
        check=True,
    )
    from unittest.mock import patch

    wire = H["Wire"]([])
    with Store(db) as s, patch("urllib.request.build_opener", lambda *_: wire):
        g = GenerationService(s, OpenAIResponses(CONFIG, H["SECRET"], authorized=True))
        action = s.one(
            "SELECT * FROM generation_actions WHERE request_id='offline-migrated-direct'"
        )
        before = historical(s, existing(s, successor=action["task_id"])["source_task_id"])
        g.execute(action["request_id"], recover=True)
        assert not wire.sent
        text = H["DevelopmentGenerationAdapter"]()(
            {"messages": g.messages(json.loads(action["input"]))}
        ).output["raw_response"]
        wire.responses.append(H["envelope"]("completed", text))
        record = g.query_remote(action["request_id"])["actions"][-1]
        assert record["result"]["generation_status"] == "generated"
        assert record["result"]["migration_provenance"]["source_task_id"] == before["task"]["id"]
        assert [x[0] for x in wire.sent] == ["GET"]
        assert not g.snapshot(action["run_id"])["can_submit"]
        assert historical(s, before["task"]["id"]) == before


@pytest.mark.parametrize("moment", ["before_commit", "after_commit"])
def test_process_interruption_reservation_is_atomic_and_retry_is_idempotent(tmp_path, moment):
    db, info = tmp_path / "atomic-process.sqlite", tmp_path / "info.json"
    child = r"""
import json,os,runpy,sys
h=runpy.run_path(sys.argv[2])
with h['Store'](sys.argv[1]) as s:
 run,bg,a,req=h['source_fixture'](s)
 before=h['historical'](s,a['task_id'])
 open(sys.argv[3],'w').write(json.dumps({'run':run,'request':req,'before':before}))
 m=h['MigrationService'](s,h['CONFIG'])
 if sys.argv[4]=='before_commit':
  fact=s.fact
  def crash(task,kind,detail):
   if kind=='migration_reserved_without_send':os._exit(0)
   fact(task,kind,detail)
  s.fact=crash
 h['confirm'](m,run,req)
 os._exit(0)
"""
    subprocess.run(
        [sys.executable, "-c", child, str(db), str(Path(__file__).resolve()), str(info), moment],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")},
        check=True,
    )
    saved = json.loads(info.read_text())
    with Store(db) as s:
        assert historical(s, saved["request"]["source_task_id"]) == saved["before"]
        assert len(s.rows("SELECT * FROM generation_migrations")) == (moment == "after_commit")
        m = MigrationService(s, CONFIG)
        first = confirm(m, saved["run"], saved["request"])
        assert confirm(m, saved["run"], saved["request"]) == first
        assert len(s.rows("SELECT * FROM generation_actions")) == 2
        assert not s.rows("SELECT * FROM attempts WHERE task_id=?", (first["successor_task_id"],))


def test_unrelated_unresolved_call_blocks_confirmation_without_global_release(tmp_path):
    with Store(tmp_path / "before-scope.sqlite") as s:
        run, _, a, req = source_fixture(s)
        original = s.one("SELECT * FROM attempts WHERE task_id=? AND ordinal=2", (a["task_id"],))
        with s.db:
            s.db.execute(
                "INSERT INTO attempts(id,task_id,call_key,target,request,ordinal,status,usage,started_at) VALUES(?,?,?,?,?,1,'uncertain',?,?)",
                (
                    "unrelated-before-migration",
                    a["task_id"],
                    "other-effect",
                    "unrelated",
                    "{}",
                    original["usage"],
                    original["started_at"],
                ),
            )
        with pytest.raises(ValueError):
            confirm(MigrationService(s, CONFIG), run, req)
        assert not s.rows("SELECT * FROM generation_migrations")
        assert len(s.rows("SELECT * FROM generation_actions")) == 1
