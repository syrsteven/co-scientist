"""Linked restart engineering acceptance, no real calls."""

import runpy
import sqlite3
from pathlib import Path

import pytest

from co_scientist_next.contracts import CallResponse
from co_scientist_next.goal import DevelopmentAdapter
from co_scientist_next.goal_restart import confirm, preview
from co_scientist_next.store import Store, encode

H = runpy.run_path(str(Path(__file__).with_name("test_research_controller.py")))


def failed(c):
    class Invalid(DevelopmentAdapter):
        def __call__(self, request):
            return CallResponse({"raw_response": "invalid JSON"})

    c.goal.adapter = Invalid()
    run = H["start"](c, mode="Both", max_directions=4)
    config = c.goal.config(run)
    config["prompt_version"] = "v6-goal-focus-v2"
    with c.store.db:
        c.store.db.execute(
            "UPDATE goal_run_config SET config=? WHERE run_id=?", (encode(config), run)
        )
    c.tick(run)
    c.tick(run)
    c.goal.adapter = DevelopmentAdapter()
    return run


def records(s, run):
    return {
        t: s.rows(f"SELECT x.* FROM {t} x JOIN tasks t ON t.id=x.task_id WHERE t.run_id=?", (run,))
        for t in ("attempts", "results", "execution_facts")
    }


def test_confirm_atomic_idempotent_lost_response_restart_and_scope(tmp_path):
    path = tmp_path / "restart.sqlite"
    with Store(path) as s:
        c = H["controller"](s)
        source = failed(c)
        before = records(s, source)
        p = preview(c, source)
        assert p["configuration_changes"]["mode"] == {"before": "Both", "after": "DIRECT"}
        with pytest.raises(ValueError):
            confirm(c, source, p["preview_hash"], False)
        with pytest.raises(ValueError):
            confirm(c, source, "stale", True)
        # Transaction interruption rolls back Start, Task and provenance together.
        s.db.execute(
            "CREATE TRIGGER interrupt_restart BEFORE INSERT ON goal_restarts BEGIN SELECT RAISE(ABORT,'offline interruption'); END"
        )
        s.db.commit()
        with pytest.raises(sqlite3.IntegrityError):
            confirm(c, source, p["preview_hash"], True)
        assert len(s.rows("SELECT * FROM runs")) == 1
        s.db.execute("DROP TRIGGER interrupt_restart")
        s.db.commit()
        successor = confirm(c, source, p["preview_hash"], True)
        assert confirm(c, source, p["preview_hash"], True) == successor
        assert s.run(successor)["revision_id"] == s.run(source)["revision_id"]
        assert c.row(successor)["config"]["mode"] == "DIRECT"
        assert records(s, source) == before
        assert len(s.rows("SELECT * FROM attempts")) == 1
    # Lost HTTP response / browser restart: GET preview finds same durable identity.
    with Store(path) as s:
        c = H["controller"](s)
        c.restart_only = True
        assert preview(c, source)["successor_run_id"] == successor
        assert confirm(c, source, p["preview_hash"], True) == successor
        assert not c.authorized_run(source) and c.authorized_run(successor)
        assert H["drain"](c, successor)["status"] == "completed"
        calls = s.rows("SELECT * FROM attempts")
        c.tick(successor)
        c.tick(source)
        assert s.rows("SELECT * FROM attempts") == calls
        assert records(s, source) == before
        with pytest.raises(ValueError):
            preview(c, successor)


def test_failed_successor_does_not_loop(tmp_path):
    with Store(tmp_path / "failed.sqlite") as s:
        c = H["controller"](s)
        source = failed(c)
        p = preview(c, source)
        successor = confirm(c, source, p["preview_hash"], True)

        class Invalid(DevelopmentAdapter):
            def __call__(self, request):
                return CallResponse({"raw_response": "invalid JSON"})

        c.goal.adapter = Invalid()
        c.restart_only = True
        H["drain"](c, successor)
        before = s.rows("SELECT * FROM attempts")
        for _ in range(3):
            c.tick(successor)
        assert c.row(successor)["status"] == "blocked"
        assert s.rows("SELECT * FROM attempts") == before
        assert preview(c, source)["successor_run_id"] == successor
        with pytest.raises(ValueError):
            preview(c, successor)


def test_http_confirmation_and_response_loss_lookup(tmp_path):
    import os
    import subprocess
    import sys

    code = r"""
import sys,runpy,json,threading,urllib.request
from pathlib import Path
from co_scientist_next.store import Store
from co_scientist_next.workspace import make_server
from co_scientist_next.research import ResearchController
from co_scientist_next.background_ops import DevelopmentReadingAdapter
from co_scientist_next.generation_ops import DevelopmentGenerationAdapter
from co_scientist_next.candidate_review_ops import DevelopmentReviewAdapter
h=runpy.run_path('tests/next/test_goal_restart.py')
with Store(sys.argv[1],http_threads=True) as s:
 c=h['H']['controller'](s);source=h['failed'](c)
 # No worker/network: tests exercise HTTP reservation/lookup independently of execution.
 ResearchController.start_worker=lambda self,lock:None
 server=make_server(s,port=0,responsive=True,development_test=True,automatic_research=True,goal_restart_only=True,public_literature=True,literature_transport=h['H']['FixtureTransport'](),reading_adapter=DevelopmentReadingAdapter(),generation_adapter=DevelopmentGenerationAdapter(),review_adapter=DevelopmentReviewAdapter(),development_review=True)
 threading.Thread(target=server.serve_forever,daemon=True).start()
 base='http://127.0.0.1:'+str(server.server_port)
 def api(path,body=None):
  request=urllib.request.Request(base+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'})
  with urllib.request.urlopen(request) as response:return json.load(response)
 path='/api/research/goal-restart?run_id='+source
 p=api(path);confirmation={'source_run_id':source,'preview_hash':p['preview_hash'],'authorize_successor_execution':True}
 # Simulate application losing the committed response: discard its body/identity.
 api('/api/research/goal-restart',confirmation)
 saved=api(path)['successor_run_id'];assert saved
 assert api('/api/research/goal-restart',confirmation)['run_id']==saved
 assert api(path)['successor_run_id']==saved
 assert len(s.rows('SELECT * FROM runs'))==2
 assert len(s.rows('SELECT * FROM attempts'))==1
 server.shutdown();server.server_close()
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path / "http.sqlite")],
        env={**os.environ, "PYTHONPATH": "src"},
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
