"""Product boundaries, offline only."""

import pytest
from test_research_controller import controller, start

from co_scientist_next.annotation_writer import save_annotation
from co_scientist_next.policy_catalog import choices, resolve
from co_scientist_next.store import Store
from co_scientist_next.workspace_records import WorkspaceRecords


def test_annotation_independent_of_runtime_lock(tmp_path):
    path = tmp_path / "run.sqlite"
    with Store(path) as store:
        run = start(controller(store))
        target = WorkspaceRecords(store).targets(run)[0]
        data = {
            "run_id": run,
            "target_kind": "run",
            "target_ref": run,
            "target_sha256": target["sha256"],
            "category": "note",
            "note": "Independent note",
            "observations": {},
            "submission_id": "stable-note-one",
        }
        # Runtime owns its lifetime lock, as it does while waiting on a model.
        saved = save_annotation(path, data)
        assert WorkspaceRecords(store).list(run)[0]["id"] == saved["id"]
        assert save_annotation(path, data)["id"] == saved["id"]
        assert len(WorkspaceRecords(store).list(run)) == 1
        with pytest.raises(ValueError):
            save_annotation(path, {**data, "note": "changed"})
        with pytest.raises(ValueError):
            save_annotation(path, {**data, "submission_id": "other-note", "target_sha256": "wrong"})


def test_controlled_policy_selection():
    selection = choices()[0]
    assert resolve(selection)["goal"]
    for changed in (
        {**selection, "id": "unknown"},
        {**selection, "version": "2"},
        {**selection, "policies": {}},
        {**selection, "sha256": "tampered"},
    ):
        with pytest.raises(ValueError):
            resolve(changed)


def test_project_trash_restore_never_resumes(tmp_path):
    from co_scientist_next.research_projects import change, projects

    with Store(tmp_path / "lifecycle.sqlite") as store:
        c = controller(store)
        run = start(c)
        project = store.run(run)["project_id"]
        draft = store.create_project("Unstarted draft")
        store.revise_brief(draft, {"question": "Unstarted question"})
        assert any(p["id"] == draft and not p["runs"] for p in projects(store))
        change(store, project, "trash")
        assert c.row(run)["status"] == "stopped"
        change(store, project, "restore")
        assert c.row(run)["status"] == "stopped"
        change(store, draft, "rename", "Recovered draft")
        assert any(p["name"] == "Recovered draft" for p in projects(store))


def test_seed_uncertain_isolated_but_common_failure_stops(tmp_path):

    from test_research_controller import drain

    from co_scientist_next.background_ops import DevelopmentReadingAdapter

    class LocalUncertain(DevelopmentReadingAdapter):
        def __init__(self):
            super().__init__()
            self.plans = 0

        def __call__(self, request):
            if request.get("operation") == "P03":
                self.plans += 1
                if self.plans == 2:
                    raise RuntimeError("OFFLINE local transport loss")
            return super().__call__(request)

    with Store(tmp_path / "local.sqlite") as store:
        c = controller(store, reading=LocalUncertain())
        run = start(c)
        result = drain(c, run)
        assert result["status"] == "completed", result
        assert store.rows("SELECT * FROM research_seed_holds")
        assert store.rows("SELECT id FROM attempts WHERE status='uncertain'")
        assert len(c.generation.snapshot(run)["actions"]) == 1
        assert not store.rows(
            "SELECT task_id,call_key FROM attempts GROUP BY task_id,call_key HAVING COUNT(*)>1"
        )

    class CommonUncertain(DevelopmentReadingAdapter):
        def __call__(self, request):
            raise RuntimeError("OFFLINE common service loss")

    with Store(tmp_path / "common.sqlite") as store:
        c = controller(store, reading=CommonUncertain())
        run = start(c)
        assert drain(c, run)["status"] == "blocked"
        assert not store.rows("SELECT * FROM research_seed_holds")


def test_http_notes_during_external_wait_and_start_recovery(tmp_path):
    import os
    import subprocess
    import sys

    command = "import sys,runpy;from pathlib import Path;sys.path.insert(0,'tests/next');h=runpy.run_path('tests/next/test_product_boundaries.py');h['_http_notes_during_external_wait_and_start_recovery'](Path(sys.argv[1]))"
    env = {**os.environ, "PYTHONPATH": "src"}
    env.pop("OPENAI_API_KEY", None)
    result = subprocess.run(
        [sys.executable, "-c", command, str(tmp_path)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _http_notes_during_external_wait_and_start_recovery(tmp_path):
    import json
    import threading
    import time
    import urllib.request

    from test_research_controller import FixtureTransport

    from co_scientist_next.background_ops import DevelopmentReadingAdapter
    from co_scientist_next.candidate_review_ops import DevelopmentReviewAdapter
    from co_scientist_next.generation_ops import DevelopmentGenerationAdapter
    from co_scientist_next.workspace import make_server

    entered, release = threading.Event(), threading.Event()

    class Waiting(DevelopmentReadingAdapter):
        def __call__(self, request):
            entered.set()
            if not release.wait(15):
                raise RuntimeError("Offline test timeout")
            return super().__call__(request)

    with Store(tmp_path / "http.sqlite", http_threads=True) as store:
        server = make_server(
            store,
            responsive=True,
            automatic_research=True,
            offline_start_response_loss=True,
            development_test=True,
            public_literature=True,
            literature_transport=FixtureTransport(),
            reading_adapter=Waiting(),
            generation_adapter=DevelopmentGenerationAdapter(),
            review_adapter=DevelopmentReviewAdapter(),
            development_review=True,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def api(path, data=None):
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}" + path,
                data=json.dumps(data).encode() if data is not None else None,
                headers={"Content-Type": "application/json"},
            )
            with opener.open(request, timeout=5) as response:
                return json.load(response)

        try:
            brief = api(
                "/api/brief",
                {
                    "name": "OFFLINE delayed operation",
                    "brief": {"question": "How does light affect flowering?"},
                },
            )
            config = api("/api/config")
            request = {
                "revision_id": brief["revision_id"],
                "start_key": "durable-http-start",
                "config": {},
                "policy_selection": config["policy_choices"][0],
                "goal_test_mode": "deterministic_development",
                "authorize_automatic_execution": True,
            }
            import http.client

            with pytest.raises(http.client.RemoteDisconnected):
                api("/api/research/start", request)
            first = {
                "run_id": api("/api/research/start-status?start_key=durable-http-start")["run"][
                    "run_id"
                ]
            }
            # Model request is genuinely still waiting; notes cannot depend on its completion.
            assert entered.wait(5)
            recovered = api("/api/research/start-status?start_key=durable-http-start")
            assert recovered["run"]["run_id"] == first["run_id"]
            run = first["run_id"]
            target = api("/api/annotations?run_id=" + run)["targets"][0]
            note = {
                "run_id": run,
                "target_kind": target["kind"],
                "target_ref": target["ref"],
                "target_sha256": target["sha256"],
                "note": "While external call is still waiting",
                "observations": {},
                "category": "note",
                "submission_id": "delayed-save-one",
            }
            before = time.monotonic()
            saved = api("/api/annotations", note)
            assert time.monotonic() - before < 1.5
            assert not release.is_set()
            assert api("/api/annotations?run_id=" + run)["records"][0]["id"] == saved["id"]
            assert api("/api/annotations", note)["id"] == saved["id"]
            status = api("/api/research/status?run_id=" + run)
            assert "messages" not in json.dumps(status) and "source_views" not in json.dumps(status)
        finally:
            server.research_controller.stop_event.set()
            release.set()
            server.shutdown()
            server.server_close()
            thread.join(5)


def test_summary_does_not_ship_raw_material_or_messages(tmp_path):
    import json

    from test_research_controller import drain

    from co_scientist_next.research_view import summary

    with Store(tmp_path / "projection.sqlite") as store:
        c = controller(store)
        run = start(c)
        drain(c, run)
        data = summary(store, run)
        wire = json.dumps(data)
        assert "actual_request" not in wire and "messages" not in wire
        assert not any("text" in v for v in data["background"]["views"])
        assert data["generation"]["actions"]


def test_failed_start_revision_and_immutable_run(tmp_path):
    from co_scientist_next.policy_catalog import choices, resolve

    with Store(tmp_path / "draft.sqlite") as store:
        c = controller(store)
        p = store.create_project("Draft")
        revision = store.revise_brief(p, {"question": "First frozen question"})
        with pytest.raises(ValueError):
            c.start(
                revision,
                "bad-config-identity",
                {"max_directions": 1},
                resolve(choices(True)[0], True),
            )
        assert not store.rows("SELECT * FROM runs")
        next_revision = store.revise_brief(p, {"question": "Corrected question"}, revision)
        run = c.start(next_revision, "good-config-identity", {}, resolve(choices(True)[0], True))
        assert (
            c.start(next_revision, "good-config-identity", {}, resolve(choices(True)[0], True))
            == run
        )
        store.revise_brief(p, {"question": "Later draft"}, next_revision)
        assert store.run(run)["revision_id"] == next_revision
