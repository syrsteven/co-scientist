"""INVENTED, explicitly offline fixtures; never evidence of real API success."""

import base64
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from co_scientist_next.calls import TaskCalls
from co_scientist_next.contracts import CallResponse, KnownCallFailure, Usage
from co_scientist_next.europe_pmc import SCOPE, EuropePMC
from co_scientist_next.goal import DEVELOPMENT_POLICY, DevelopmentAdapter, GoalSlice
from co_scientist_next.literature import SearchRequest
from co_scientist_next.literature_runtime import LiteratureService
from co_scientist_next.store import Store

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = json.loads((Path(__file__).parent / "fixtures/europepmc_development.json").read_text())


def envelope(request, body):
    raw = body.encode()
    return {
        "url": request["url"],
        "status_code": 200,
        "headers": {"X-Fixture": "INVENTED OFFLINE"},
        "body_base64": base64.b64encode(raw).decode(),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "truncated": False,
        "started_at": "2026-11-03T00:00:00+00:00",
        "received_at": "2026-11-03T00:00:01+00:00",
    }


class FixtureTransport:
    def __init__(self, mode="page"):
        self.mode, self.sends = mode, []

    def __call__(self, request):
        self.sends.append(request)
        params = parse_qs(urlsplit(request["url"]).query)
        if self.mode == "timeout":
            raise TimeoutError("OFFLINE fixture: response lost")
        if self.mode == "http_error":
            response = envelope(request, "OFFLINE fixture service failure")
            response["status_code"] = 503
            raise KnownCallFailure("OFFLINE fixture HTTP 503", response=response)
        if self.mode == "bad_json":
            return CallResponse(envelope(request, "not-json OFFLINE"))
        if request["url"].endswith("/fullTextXML"):
            xml = FIXTURE["full_text"]
            if self.mode == "empty_body":
                xml = '<article><front><article-id pub-id-type="pmc">999001</article-id></front><body /></article>'
            if self.mode == "abstract_document":
                xml = FIXTURE["full_text"].replace("<article>", '<article article-type="abstract">')
            if self.mode == "bad_fulltext":
                xml = "<response>not an article</response>"
            saved = envelope(request, xml)
            if self.mode == "truncated_fulltext":
                saved["truncated"] = True
            return CallResponse(saved, Usage(tool_units=1))
        article = dict(FIXTURE["article"])
        if self.mode == "wrong_identity":
            article["id"] = "999002"
        if self.mode == "no_oa":
            article["isOpenAccess"] = "N"
        if self.mode == "no_abstract":
            article.pop("abstractText")
        data = {"hitCount": 3, "nextCursorMark": "page-2", "resultList": {"result": [article]}}
        if params.get("resultType") == ["core"]:
            data = {"hitCount": 1, "result": article}
        elif self.mode == "empty":
            data.update(hitCount=0, nextCursorMark="*", resultList={"result": []})
        elif self.mode == "duplicate":
            data["resultList"]["result"] = [article, article]
        elif self.mode == "partial":
            data["resultList"]["result"].append({"title": "malformed OFFLINE entry"})
        elif params.get("cursorMark") == ["page-2"]:
            data.update(nextCursorMark=None, resultList={"result": []})
        return CallResponse(envelope(request, json.dumps(data)), Usage(tool_units=1))


def setup(store, scenario="pass"):
    project = store.create_project("OFFLINE fixture engineering")
    revision = store.revise_brief(
        project,
        {
            "question": "Existing Goal; no molecule preselected",
            "hard_constraints": ["Keep unknowns"],
        },
    )
    goal = GoalSlice(store, DevelopmentAdapter(), development_test=True)
    run = goal.create_run(revision, DEVELOPMENT_POLICY, scenario=scenario)
    goal.execute(run)
    return run, goal


@pytest.fixture
def saved(tmp_path):
    with Store(tmp_path / "lit.sqlite") as store:
        run, goal = setup(store)
        yield store, run, goal


def acquire(saved, mode="page", request=None, request_id="manual-001"):
    store, run, _ = saved
    transport = FixtureTransport(mode)
    service = LiteratureService(store, enabled=True, transport=transport)
    service.submit(
        run, request_id, request or {"kind": "search", "query": "ALS nuclear pore phosphorylation"}
    )
    history = service.execute(request_id)
    return service, transport, history[-1]


@pytest.mark.parametrize(
    "mode,status,empty",
    [
        ("page", "succeeded", False),
        ("empty", "succeeded", True),
        ("http_error", "failed", False),
        ("bad_json", "incomplete", False),
        ("partial", "incomplete", False),
    ],
)
def test_empty_error_partial_and_pagination(saved, mode, status, empty):
    _, _, entry = acquire(saved, mode)
    result = entry["result"]["acquisition"]
    assert result["status"] == status
    assert (result["reported_total"] == 0 and result["scope_complete"]) is empty
    if mode == "page":
        assert result["next_cursor"] == "page-2" and not result["scope_complete"]
    if mode == "http_error":
        assert result["reported_total"] is None and result["error"]
        assert entry["attempts"][0]["status"] == "failed"
    if mode == "bad_json":
        assert entry["attempts"][0]["status"] == "succeeded"  # HTTP fact != valid parsed material


def test_duplicate_results_idempotence_and_fixed_goal(saved):
    store, run, goal = saved
    before = goal.snapshot(run)["fixed_brief"]
    service, transport, entry = acquire(saved, "duplicate")
    assert len(entry["result"]["acquisition"]["items"]) == 1
    assert entry["result"]["details"]["raw_returned_count"] == 2
    service.submit(
        run, "manual-001", {"kind": "search", "query": "ALS nuclear pore phosphorylation"}
    )
    service.execute("manual-001")
    assert len(transport.sends) == 1 and len(service.history(run)) == 1
    output = store.one("SELECT output FROM results WHERE task_id=?", (entry["task_id"],))["output"]
    assert store.submit_result(entry["task_id"], json.loads(output)) is False
    with pytest.raises(ValueError, match="different"):
        service.submit(run, "manual-001", {"kind": "search", "query": "changed query"})
    service.submit(run, "manual-002", {"kind": "search", "query": "changed manual query"})
    service.execute("manual-002")
    assert len(service.history(run)) == 2 and goal.snapshot(run)["fixed_brief"] == before
    assert goal.snapshot(run)["science_validated"] is False


@pytest.mark.parametrize(
    "scenario",
    [
        "reject",
        "clarification",
        "risk_information",
        "invalid_output",
        "technical_failure",
        "uncertain_send",
    ],
)
def test_nonpass_cannot_acquire(tmp_path, scenario):
    with Store(tmp_path / "nonpass.sqlite") as store:
        run, _ = setup(store, scenario)
        transport = FixtureTransport()
        service = LiteratureService(store, enabled=True, transport=transport)
        with pytest.raises(ValueError):
            service.submit(run, "nonpass-request", {"kind": "search", "query": "manual query"})
        assert not transport.sends and not service.history(run)


def test_missing_and_uncompleted_policy_does_not_acquire(tmp_path):
    with Store(tmp_path / "missing.sqlite") as store:
        revision = store.revise_brief(store.create_project("missing"), {"question": "Goal"})
        goal = GoalSlice(store, DevelopmentAdapter(), development_test=True)
        for execute in (False, True):
            run = goal.create_run(revision)
            if execute:
                goal.execute(run)
            with pytest.raises(ValueError):
                LiteratureService(store, enabled=True).submit(
                    run, "no-pass-id", {"kind": "search", "query": "Goal"}
                )


@pytest.mark.parametrize(
    "mode,desired,actual,status",
    [
        ("page", "abstract", "abstract", "succeeded"),
        ("page", "full_text", "full_text", "succeeded"),
        ("no_oa", "full_text", "abstract", "incomplete"),
        ("no_abstract", "abstract", "metadata", "incomplete"),
        ("bad_fulltext", "full_text", "abstract", "incomplete"),
        ("empty_body", "full_text", "abstract", "incomplete"),
        ("abstract_document", "full_text", "abstract", "incomplete"),
        ("truncated_fulltext", "full_text", "abstract", "incomplete"),
        ("wrong_identity", "abstract", "none", "failed"),
        ("page", "supplementary", "abstract", "incomplete"),
    ],
)
def test_access_levels_and_actual_text(saved, mode, desired, actual, status):
    service, transport, _ = acquire(saved)
    transport.mode = mode
    service.submit(
        saved[1],
        "fetch-001",
        {"kind": "fetch", "source_ref": "epmc:MED:999001", "desired_access": desired},
    )
    entry = service.execute("fetch-001")[-1]
    result = entry["result"]["acquisition"]
    assert result["access"] == actual and result["status"] == status
    assert (
        result["text"] is None
        if actual in ("metadata", "none")
        else "fixture" in result["text"].lower()
    )
    if status == "incomplete":
        assert result["limitation"] and result["error"]
    if actual == "full_text":
        assert "not fetched" in entry["result"]["details"]["supplementary"]
        assert len(transport.sends) == 3  # search, identity metadata, XML; no hidden sends


def test_page_cursor_and_unseen_source_and_disabled(saved):
    service, transport, _ = acquire(saved)
    service.submit(
        saved[1],
        "next-page-id",
        {"kind": "search", "query": "ALS nuclear pore phosphorylation", "cursor": "page-2"},
    )
    result = service.execute("next-page-id")[-1]["result"]["acquisition"]
    assert result["next_cursor"] is None and result["scope_complete"]
    assert parse_qs(urlsplit(transport.sends[-1]["url"]).query)["cursorMark"] == ["page-2"]
    with pytest.raises(ValueError, match="history"):
        service.submit(saved[1], "unseen-source", {"kind": "fetch", "source_ref": "epmc:MED:123"})
    with pytest.raises(ValueError, match="enabled"):
        LiteratureService(saved[0]).submit(
            saved[1], "disabled-id", {"kind": "search", "query": "Goal"}
        )


def test_uncertain_send_never_silently_retries(saved):
    service, transport, entry = acquire(saved, "timeout")
    assert entry["task_status"] == "blocked" and entry["result"] is None
    service.execute("manual-001", recover=True)
    assert len(transport.sends) == 1
    with pytest.raises(ValueError, match="unfinished"):
        service.submit(saved[1], "another-request", {"kind": "search", "query": "Goal"})


def test_saved_success_replay_before_result_application(saved):
    store, run, _ = saved
    transport = FixtureTransport()
    service = LiteratureService(store, enabled=True, transport=transport)
    action = service.submit(run, "replay-request", {"kind": "search", "query": "Goal"})
    with store.db:
        store.db.execute("UPDATE tasks SET status='running' WHERE id=?", (action["task_id"],))
    calls = TaskCalls(store, action["task_id"])
    port = EuropePMC(calls, transport=transport)
    first = port.search(SearchRequest("Europe PMC", "Goal", SCOPE))
    second = port.search(SearchRequest("Europe PMC", "Goal", SCOPE))
    assert first == second and len(transport.sends) == 1
    assert store.one("SELECT response FROM attempts WHERE task_id=?", (action["task_id"],))[
        "response"
    ]
    usage = store.usage(run_id=run)
    assert usage["cost"]["unknown_attempts"] > 0


def test_atomic_task_action_rollback(saved):
    store, run, _ = saved
    before = store.run(run)
    store.db.execute(
        "CREATE TRIGGER fail_action BEFORE INSERT ON literature_actions BEGIN SELECT RAISE(ABORT,'fixture rollback'); END"
    )
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        LiteratureService(store, enabled=True).submit(
            run, "rollback-id", {"kind": "search", "query": "Goal"}
        )
    assert store.run(run) == before and len(store.tasks(run)) == 2


def test_acquisition_cross_process_replay_without_transport(tmp_path):
    db = tmp_path / "restart.sqlite"
    code = r"""
import os,sys,json,base64,hashlib
from co_scientist_next.store import Store
from co_scientist_next.goal import GoalSlice,DevelopmentAdapter,DEVELOPMENT_POLICY
from co_scientist_next.literature_runtime import LiteratureService
from co_scientist_next.contracts import CallResponse
from co_scientist_next.europe_pmc import EuropePMC,SCOPE
from co_scientist_next.calls import TaskCalls
from co_scientist_next.literature import SearchRequest
with Store(sys.argv[1]) as store:
 g=GoalSlice(store,DevelopmentAdapter(),development_test=True)
 r=g.create_run(store.revise_brief(store.create_project('OFFLINE crash fixture'),{'question':'Goal'}),DEVELOPMENT_POLICY);g.execute(r)
 service=LiteratureService(store,enabled=True)
 action=service.submit(r,'crash-request',{'kind':'search','query':'Goal'})
 with store.db:
  store.db.execute("UPDATE tasks SET status='running' WHERE id=?",(action['task_id'],))
  store.db.execute("UPDATE runs SET status='running' WHERE id=?",(r,))
 def fixture(req):
  raw=b'{"hitCount":0,"resultList":{"result":[]}}'
  return CallResponse({'url':req['url'],'body_base64':base64.b64encode(raw).decode(),'sha256':hashlib.sha256(raw).hexdigest(),'received_at':'2026-11-03T00:00:00+00:00','truncated':False})
 EuropePMC(TaskCalls(store,action['task_id']),transport=fixture).search(SearchRequest('Europe PMC','Goal',SCOPE))
 print(json.dumps({'pid':os.getpid(),'run':r}),flush=True)
 os._exit(19)
"""
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    child = subprocess.run(
        [sys.executable, "-c", code, str(db)], env=env, text=True, capture_output=True, check=False
    )
    assert child.returncode == 19, child.stderr
    created = json.loads(child.stdout)
    with Store(db) as store:

        def no_send(_):
            pytest.fail("Saved successful HTTP must replay without network")

        service = LiteratureService(store, enabled=True, transport=no_send)
        history = service.execute("crash-request", recover=True)
        assert history[0]["result"]["acquisition"]["scope_complete"]
        assert (
            len(store.rows("SELECT * FROM attempts WHERE task_id=?", (history[0]["task_id"],))) == 1
        )
        assert created["pid"] != os.getpid()
        print(
            json.dumps(
                {
                    "scenario": "literature_saved_http_replay",
                    "crashed_pid": created["pid"],
                    "resumed_pid": os.getpid(),
                    "external_fixture_sends": 1,
                }
            )
        )


@pytest.mark.parametrize("status", [200, 302, 503])
def test_real_http_transport_preserves_response_without_hidden_redirect_or_retry(
    monkeypatch, status
):
    from co_scientist_next.europe_pmc import BASE, NoRedirect, public_http

    sends = []

    class Response:
        code = status

        def __init__(self):
            self.headers = {
                "Content-Type": "application/json",
                "Location": "https://external.invalid/redirect",
            }

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def read(self, _):
            return b"OFFLINE HTTP envelope test"

    class Opener:
        def open(self, req, **_):
            sends.append(req.full_url)
            return Response()

    import urllib.request

    monkeypatch.setattr(urllib.request, "build_opener", lambda *_: Opener())
    assert (
        NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://external.invalid")
        is None
    )
    request = {"url": BASE + "search", "headers": {}}
    if status == 200:
        response = public_http(request).output
    else:
        with pytest.raises(KnownCallFailure) as caught:
            public_http(request)
        response = caught.value.response
    assert response["status_code"] == status
    assert base64.b64decode(response["body_base64"]) == b"OFFLINE HTTP envelope test"
    assert len(sends) == 1


def test_saved_live_evidence_integrity_offline_only():
    """Audit saved real receipts; this check itself does not contact Europe PMC."""
    import gzip

    evidence = ROOT / "docs/verification/w1-l1"
    for filename in ("public-acquisition.json.gz", "diagnostic-acquisition.json.gz"):
        data = json.loads(gzip.decompress((evidence / filename).read_bytes()))
        for attempt in data["attempts"]:
            response = attempt["response"]
            assert (
                hashlib.sha256(base64.b64decode(response["body_base64"])).hexdigest()
                == response["sha256"]
            )
            assert response["url"] == attempt["request"]["url"]
            assert (
                attempt["status"] == "succeeded"
            )  # HTTP success, not scientific or parse success.
        for action in data["history"]:
            assert action["result"]["model_read"] is False
            assert action["result"]["science_validated"] is False
    live = json.loads(gzip.decompress((evidence / "public-acquisition.json.gz").read_bytes()))
    materials = [
        a["result"]["acquisition"] for a in live["history"] if a["request"]["kind"] == "fetch"
    ]
    assert {m["access"] for m in materials} == {"abstract", "full_text"}
    assert all(m["text"] for m in materials)
    assert live["history"][0]["result"]["acquisition"]["scope_complete"] is False
