"""OFFLINE trial preparation/provenance fixtures. No real DB, keys or provider traffic."""

import copy
import json
import os
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

from co_scientist_next import review_trial
from co_scientist_next.candidate_review import CandidateReviewService
from co_scientist_next.candidate_review_ops import (
    DEVELOPMENT_DECISIONS,
    DEVELOPMENT_POLICY,
    DEVELOPMENT_R0_POLICY,
    DevelopmentReviewAdapter,
)
from co_scientist_next.generation_migration import ReadOnlyStore
from co_scientist_next.responses_model import OpenAIResponses
from co_scientist_next.review_fixture import create_fixture
from co_scientist_next.store import Store, encode

ROOT = Path(__file__).resolve().parents[2]
R = runpy.run_path(str(Path(__file__).with_name("test_responses_background.py")))
POLICIES = ROOT / "docs/preparations/candidate-review-real-trial"
TRIAL = ROOT / "docs/trials/p08-direct-responses-real"


def source_simulator(tmp_path):
    """Test-only source shape, public candidate unchanged; not an actual model trace."""
    db = tmp_path / "OFFLINE-source.sqlite"
    create_fixture(db, TRIAL)
    # Private source simulator only; production preparation never deletes markers.
    with Store(db) as s, s.db:
        s.db.execute("DELETE FROM execution_facts WHERE kind='development_candidate_import'")
    return db


def prepared(tmp_path):
    source = source_simulator(tmp_path)
    db, package = tmp_path / "isolated.sqlite", tmp_path / "package"
    info = review_trial.prepare(source, db, POLICIES, package)
    return source, db, package, info


def decision(payload, value="pass"):
    return {
        "candidate_id": payload["fixed_candidate"]["candidate_id"],
        "decision_per_approved_policy": value,
        "applicable_clauses": [
            {"id": "NP-01", "quote": payload["approved_policy_text"].splitlines()[0]}
        ],
        "specific_risks": ["OFFLINE scope conflict"] if value == "reject" else [],
        "rationale": "OFFLINE simulated provider response; not a real ethical decision.",
        "limitations_or_missing_context": ["OFFLINE engineering fixture only"],
    }


def test_prepare_preserves_source_and_complete_material_no_review_decisions(tmp_path):
    source, db, package, info = prepared(tmp_path)
    before = review_trial.sha_file(source)
    with ReadOnlyStore(source) as old, ReadOnlyStore(db) as s:
        frozen, g = review_trial.validate_package(s, package)
        assert info["model_requests"] == 0 and not info["P10_executable"]
        assert not s.rows("SELECT * FROM candidate_review_actions")
        for table, rows in review_trial.inventory(old).items():
            if table != "execution_facts":
                assert s.rows('SELECT * FROM "' + table + '" ORDER BY rowid') == rows
        payload = review_trial.read(package / "P09.actual-input.json")
        assert payload["fixed_candidate"] == review_trial.read(TRIAL / "candidate.json")
        assert payload["intended_use"] != payload["goal_context"]["intended_use"]
        assert (
            "NP-05" in payload["approved_policy_text"]
            and payload["approved_policy_id"]["mode"] == "development"
        )
        template = review_trial.read(package / "P10.input-template.json")
        assert (
            template["input_template"]["passed_candidate_ethics_record"] is None
            and not template["executable"]
        )
        assert template["input_template"]["actual_visible_source_views"] == review_trial.read(
            TRIAL / "source-views.json"
        )
        assert g.snapshot(frozen["run_id"])["model_config"]["execution_mode"] == "real_model"
        assert g.snapshot(frozen["run_id"])["development_policies_allowed"]
    assert review_trial.sha_file(source) == before
    with pytest.raises(ValueError, match="NEW isolated"):
        review_trial.prepare(source, db, POLICIES, package)
    with pytest.raises(ValueError):
        review_trial.assemble_p10(db, package, tmp_path / "forbidden")
    assert not (tmp_path / "forbidden").exists()


@pytest.mark.parametrize(
    "which", ["policy", "production-label", "use", "request_id", "model", "fixture"]
)
def test_trial_frozen_policy_identity_profile_and_real_mode_are_required(tmp_path, which):
    _, db, package, _ = prepared(tmp_path)
    frozen = review_trial.read(package / "trial.json")
    with Store(db) as s:
        cfg = frozen["model_config"]
        if which == "model":
            cfg = {**cfg, "max_request_bytes": 270000}
        adapter = DevelopmentReviewAdapter() if which == "fixture" else OpenAIResponses(cfg)
        g = CandidateReviewService(s, adapter, development=True)
        req = copy.deepcopy(frozen["p09_request"])
        ref = frozen["request_ids"]["P09"]
        if which == "policy":
            req["policy"]["version"] = "unaudited"
        if which == "production-label":
            req["policy"]["mode"] = "production"
        if which == "use":
            req["intended_use"] = "changed use"
        if which == "request_id":
            ref = "second-post-identity"
        with pytest.raises(ValueError):
            g.submit(frozen["run_id"], ref, req)
        assert not s.rows("SELECT * FROM candidate_review_actions")


@pytest.mark.parametrize("value", ["pass", "reject", "incomplete"])
def test_real_profile_nonproduction_policy_gate_and_no_second_submission(
    tmp_path, monkeypatch, value
):
    import urllib.request

    _, db, package, _ = prepared(tmp_path)
    frozen = review_trial.read(package / "trial.json")
    wire = R["Wire"]([R["envelope"]("queued")])
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_: wire)
    with Store(db) as s:
        g = CandidateReviewService(
            s,
            OpenAIResponses(frozen["model_config"], R["SECRET"], authorized=True),
            development=True,
        )
        ref = frozen["request_ids"]["P09"]
        a = g.submit(frozen["run_id"], ref, frozen["p09_request"])
        g.execute(ref)
        wire.responses.append(
            R["envelope"]("completed", encode(decision(json.loads(a["input"]), value)))
        )
        g.query_remote(ref)
        saved = g.action(frozen["run_id"], ref)
        assert saved["result"]["policy_mode"] == "development"
        assert saved["result"]["execution_mode"] == "real_model"
        assert saved["result"]["development"] and not saved["result"]["science_validated"]
        assert "credential_configured" not in saved["config"]
        g.submit(frozen["run_id"], ref, frozen["p09_request"])
        g.execute(ref)
        assert [x[0] for x in wire.sent] == ["POST", "GET"]
        if value == "pass":
            payload, _ = g.ready_input(frozen["run_id"], frozen["p10_request"])
            assert payload["passed_candidate_ethics_record"] == saved["result"]
        else:
            with pytest.raises(ValueError):
                g.submit(frozen["run_id"], frozen["request_ids"]["P10"], frozen["p10_request"])
            assert not s.rows("SELECT * FROM candidate_review_actions WHERE operation='P10'")
    if value == "pass":
        info = review_trial.assemble_p10(db, package, tmp_path / "assembled")
        assert info["assembled"] and info["model_requests"] == 0
        text = review_trial.read(tmp_path / "assembled/P10.unsent-request.json")
        assert text["policy_mode"] == "development"


def test_fixture_pass_or_relabelled_result_cannot_become_real_pass(tmp_path):
    db = tmp_path / "fixture.sqlite"
    meta = create_fixture(db, TRIAL)
    with Store(db) as s:
        fixture = CandidateReviewService(s, DevelopmentReviewAdapter(), development=True)
        req = {
            "operation": "P09",
            "generation_ref": meta["generation_ref"],
            "intended_use": "OFFLINE test",
            "policy": DEVELOPMENT_POLICY,
            "decision_policy": DEVELOPMENT_DECISIONS,
        }
        a = fixture.submit(meta["run_id"], "offline-fake-pass", req)
        fixture.execute(a["request_id"])
        real = CandidateReviewService(s, OpenAIResponses(R["CONFIG"]), development=True)
        p10 = {
            "operation": "P10",
            "generation_ref": meta["generation_ref"],
            "ethics_ref": a["request_id"],
            "policy": DEVELOPMENT_R0_POLICY,
        }
        with pytest.raises(ValueError, match="real Responses"):
            real.submit(meta["run_id"], "offline-real-r0-blocked", p10)
        # A label alone is not evidence: still no successful remote/M15 record.
        with s.db:
            output = json.loads(
                s.one("SELECT output FROM results WHERE task_id=?", (a["task_id"],))["output"]
            )
            output["execution_mode"] = "real_model"
            s.db.execute(
                "UPDATE results SET output=? WHERE task_id=?", (encode(output), a["task_id"])
            )
            s.db.execute(
                "UPDATE candidate_review_actions SET config=? WHERE task_id=?",
                (encode(OpenAIResponses(R["CONFIG"]).public_config()), a["task_id"]),
            )
        with pytest.raises(ValueError, match="remote record"):
            real.submit(meta["run_id"], "offline-relabel-blocked", p10)
        assert not s.rows("SELECT * FROM candidate_review_actions WHERE operation='P10'")


def test_unauthorized_commands_reject_before_credentials_or_send(tmp_path):
    _, db, package, _ = prepared(tmp_path)
    for op in ("submit-p09", "submit-p10", "query-p09"):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "co_scientist_next.review_trial",
                op,
                "--db",
                str(db),
                "--package",
                str(package),
            ],
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "PYTHONPATH": "src"},
        )
        assert result.returncode == 2
    with ReadOnlyStore(db) as s:
        assert not s.rows("SELECT * FROM candidate_review_actions")
    before = review_trial.sha_file(db)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "co_scientist_next.review_trial",
            "inspect",
            "--db",
            str(db),
            "--package",
            str(package),
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": "src"},
        check=True,
    )
    assert json.loads(result.stdout)["model_requests"] == 0 and review_trial.sha_file(db) == before


def test_package_prompt_or_candidate_changes_fail_before_execution(tmp_path, monkeypatch):
    _, db, package, _ = prepared(tmp_path)
    monkeypatch.setattr(review_trial, "prompt", lambda _: "changed prompt")
    with ReadOnlyStore(db) as s, pytest.raises(ValueError, match="Prompt content changed"):
        review_trial.validate_package(s, package)


def test_uncertain_submit_no_id_stops_before_any_credential_reload(tmp_path, monkeypatch):
    import urllib.request

    _, db, package, _ = prepared(tmp_path)
    frozen = review_trial.read(package / "trial.json")
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
        assert g.action(frozen["run_id"], a["request_id"])["task_status"] == "blocked"

    def forbidden(**_):
        raise AssertionError("No credential should be loaded after existing ambiguous POST")

    monkeypatch.setattr(review_trial, "load_credential", forbidden)
    assert review_trial.operate(db, package, "P09")["sent"] is False
    assert review_trial.operate(db, package, "P09", query=True)["sent"] is False
    assert [x[0] for x in wire.sent] == ["POST"]
    with ReadOnlyStore(db) as s, pytest.raises(ValueError):
        review_trial.validate_package(s, package)[1].ready_input(
            frozen["run_id"], frozen["p10_request"]
        )


def test_pending_real_policy_trial_queries_in_new_process_without_post(tmp_path, monkeypatch):
    import urllib.request

    _, db, package, _ = prepared(tmp_path)
    frozen = review_trial.read(package / "trial.json")
    wire = R["Wire"]([R["envelope"]("queued")])
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_: wire)
    with Store(db) as s:
        g = CandidateReviewService(
            s,
            OpenAIResponses(frozen["model_config"], R["SECRET"], authorized=True),
            development=True,
        )
        a = g.submit(frozen["run_id"], frozen["request_ids"]["P09"], frozen["p09_request"])
        response = decision(json.loads(a["input"]))
        g.execute(a["request_id"])
    code = """
import sys,runpy,json,urllib.request
from unittest.mock import patch
from co_scientist_next.store import Store
from co_scientist_next.candidate_review import CandidateReviewService
from co_scientist_next.responses_model import OpenAIResponses
from co_scientist_next.review_trial import read
r=runpy.run_path(sys.argv[2]);frozen=read(sys.argv[3]);wire=r['Wire']([r['envelope']('completed',sys.argv[4])])
with patch.object(urllib.request,'build_opener',lambda *_:wire),Store(sys.argv[1]) as s:
 g=CandidateReviewService(s,OpenAIResponses(frozen['model_config'],r['SECRET'],authorized=True),development=True)
 g.query_remote(frozen['request_ids']['P09'])
 assert [x[0] for x in wire.sent]==['GET']
 assert g.ready_input(frozen['run_id'],frozen['p10_request'])[0]['passed_candidate_ethics_record']['execution_mode']=='real_model'
 print('OFFLINE new process: same ID GET, development policy with verified real-profile response')
"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            code,
            str(db),
            str(Path(__file__).with_name("test_responses_background.py")),
            str(package / "trial.json"),
            encode(response),
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": "src"},
        check=True,
    )
    assert "same ID GET" in result.stdout


def test_page_cli_real_profile_and_development_policy_are_separate(tmp_path):

    _, db, _, _ = prepared(tmp_path)
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "co_scientist_next.workspace",
            "--db",
            str(db),
            "--port",
            "0",
            "--development-test",
            "--review-responses-config",
            str(POLICIES / "model-config.json"),
            "--allow-development-review-policy",
        ],
        env={**os.environ, "PYTHONPATH": "src"},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        line = server.stdout.readline().strip()
        assert line, server.stderr.read()
        url = line.split(" | ")[0]
        before = review_trial.sha_file(db)
        code = r"""
import sys,json,urllib.request
url=sys.argv[1];run=sys.argv[2]
for _ in range(3):
 with urllib.request.urlopen(url+'/api/candidate-review?run_id='+run,timeout=15) as r:data=json.load(r)
 assert data['model_config']['execution_mode']=='real_model'
 assert not data['model_config']['credential_configured'] and not data['real_calls_authorized']
 assert data['development_policies_allowed'] and not data['actions'] and data['prepared_trial']
print('Loopback real-profile/nonproduction state read only')
"""
        completed = subprocess.run(
            [sys.executable, "-c", code, url, review_trial.RUN],
            capture_output=True,
            text=True,
            check=True,
        )
        assert "read only" in completed.stdout
        assert before == review_trial.sha_file(db)
    finally:
        server.terminate()
        server.wait(timeout=10)


def test_another_database_copy_cannot_execute_the_same_prepared_trial(tmp_path):
    import shutil

    _, db, package, _ = prepared(tmp_path)
    clone = tmp_path / "unapproved-second-copy.sqlite"
    shutil.copyfile(db, clone)
    with ReadOnlyStore(clone) as s, pytest.raises(ValueError, match="designated trial database"):
        review_trial.validate_package(s, package)


def test_operator_rejects_wrong_database_before_opening_write_connection(tmp_path, monkeypatch):
    source, _, package, _ = prepared(tmp_path)
    before = review_trial.sha_file(source)

    def forbidden(*args, **kwargs):
        raise AssertionError("No writable connection or credential load before validation")

    monkeypatch.setattr(review_trial, "Store", forbidden)
    monkeypatch.setattr(review_trial, "load_credential", forbidden)
    with pytest.raises(ValueError):
        review_trial.operate(source, package, "P09")
    assert review_trial.sha_file(source) == before
