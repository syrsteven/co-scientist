"""Offline regressions. Synthetic text reproduces the private real response's shape."""

import json
import runpy
from pathlib import Path

import pytest

from co_scientist_next.goal import (
    PREPARE,
    PREPARE_V3,
    DevelopmentAdapter,
    parse_prepare,
    parse_prepare_v3,
)
from co_scientist_next.research_config import DEFAULT_VERSION, DEFAULTS, public_start_config
from co_scientist_next.store import Store, encode

H = runpy.run_path(str(Path(__file__).with_name("test_research_controller.py")))


def payload():
    return {
        "original_question": "What causes change?",
        "explicit_constraints": ["Do not preselect a target"],
        "preferences": ["Prefer testability"],
        "supplied_background": "Distinguish models.",
        "supplied_material_manifest": ["user:reference"],
        "intended_use_if_supplied": "Conceptual use only",
    }


def semantics():
    return {
        "optional_interpretations": [],
        "unspecified_details": [],
        "clarification_required": False,
        "clarification_questions": [],
        "additional_conditions": [],
    }


def legacy():
    request = {"operation": PREPARE, "messages": [{"content": encode(payload())}]}
    return json.loads(DevelopmentAdapter()(request).output["raw_response"])


def test_saved_failure_shape_and_extra_classification_cannot_be_repaired_by_prefix():
    value = legacy()
    for field in ("hard_requirements", "preferences"):
        for item in value[field]:
            item["input_locator"] = "$." + item["input_locator"]
    value["hard_requirements"].append(
        {
            "text": "Distinguish models.",
            "input_locator": "$.supplied_background",
            "supporting_span": "Distinguish models.",
        }
    )
    with pytest.raises(ValueError, match="Unknown input locator"):
        parse_prepare(encode(value), payload())
    for field in ("hard_requirements", "preferences"):
        for item in value[field]:
            item["input_locator"] = item["input_locator"].removeprefix("$.")
    with pytest.raises(ValueError, match="Unknown input locator"):
        parse_prepare(encode(value), payload())


def test_v3_preserves_fixed_fields_without_model_echo_or_promotion():
    goal = parse_prepare_v3(encode(semantics()), payload())
    assert [i["text"] for i in goal["hard_requirements"]] == payload()["explicit_constraints"]
    assert [i["text"] for i in goal["preferences"]] == payload()["preferences"]
    assert goal["material_manifest"] == ["user:reference"]
    assert goal["supplied_background"] == "Distinguish models."
    assert goal["original_question"] == payload()["original_question"]


@pytest.mark.parametrize(
    "change",
    [
        {"additional_conditions": ["Use a particular model"]},
        {"hard_requirements": []},
        {"material_manifest": ["fabricated:source"]},
        {"clarification_required": True},
        {
            "optional_interpretations": [
                {"text": "Guess", "input_locator": "unknown", "supporting_span": "made up"}
            ]
        },
        {
            "optional_interpretations": [
                {
                    "text": "Guess",
                    "input_locator": "original_question",
                    "supporting_span": "made up",
                }
            ]
        },
    ],
)
def test_invalid_semantics_and_fabricated_sources_still_fail(change):
    with pytest.raises(ValueError):
        parse_prepare_v3(encode({**semantics(), **change}), payload())


def test_legacy_parser_and_frozen_run_replay_remain_legacy(tmp_path):
    with Store(tmp_path / "legacy.sqlite") as store:
        c = H["controller"](store)
        run = H["start"](c)
        config = c.goal.config(run)
        config["prompt_version"] = "v6-goal-focus-v2"
        with store.db:
            store.db.execute(
                "UPDATE goal_run_config SET config=? WHERE run_id=?", (encode(config), run)
            )
        c.tick(run)
        c.tick(run)
        before = store.rows("SELECT * FROM attempts")
        assert json.loads(before[0]["request"])["prompt_version"] == "v6-goal-focus-v2"
        assert c.goal.execute(run) == "awaiting_background"
        assert store.rows("SELECT * FROM attempts") == before
        assert parse_prepare(encode(legacy()), payload())["hard_requirements"]


def test_defaults_freeze_and_existing_launch_never_changes(tmp_path):
    config = public_start_config({"defaults_version": DEFAULT_VERSION})
    assert config["mode"] == "DIRECT" and config["max_directions"] == 2
    with pytest.raises(ValueError):
        public_start_config({"config": {}, "defaults_version": DEFAULT_VERSION})
    with pytest.raises(ValueError):
        public_start_config({"defaults_version": "old"})
    with Store(tmp_path / "defaults.sqlite") as store:
        c = H["controller"](store)
        run = H["start"](c, mode="Both", max_directions=4)
        frozen = c.row(run)["config"]
        assert public_start_config({}, existing=frozen) == frozen
        assert c.row(run)["config"]["mode"] == "Both"
        assert config == DEFAULTS
        assert c.goal.config(run)["prompt_version"] == PREPARE_V3


def test_blocked_invalid_run_never_auto_retries_or_advances(tmp_path):
    from co_scientist_next.contracts import CallResponse
    from co_scientist_next.goal_diagnostics import inspect_goal

    class Invalid(DevelopmentAdapter):
        def __call__(self, request):
            return CallResponse({"raw_response": "not JSON"})

    with Store(tmp_path / "blocked.sqlite") as store:
        c = H["controller"](store)
        c.goal.adapter = Invalid()
        run = H["start"](c)
        c.tick(run)
        c.tick(run)
        before = store.rows("SELECT * FROM attempts")
        assert c.row(run)["status"] == "blocked"
        for _ in range(3):
            assert inspect_goal(store, run)["stage"] == "preparation"
            assert inspect_goal(store, run)["status"] == "invalid_output"
            c.tick(run)
        with pytest.raises(ValueError):
            c.control(store.db, run, "resume")
        c = H["controller"](store)
        c.tick(run)
        assert store.rows("SELECT * FROM attempts") == before
        assert len(store.tasks(run)) == 1


@pytest.mark.parametrize(
    "scenario,expected",
    [
        ("reject", "rejected"),
        ("risk_information", "awaiting_risk_context"),
        ("technical_failure", "failed"),
        ("uncertain_send", "uncertain"),
    ],
)
def test_screening_issue_is_not_preparation_failure(tmp_path, scenario, expected):
    from co_scientist_next.goal import DEVELOPMENT_POLICY, GoalSlice
    from co_scientist_next.goal_diagnostics import inspect_goal

    with Store(tmp_path / "screen.sqlite") as store:
        revision = store.revise_brief(
            store.create_project("OFFLINE"), {"question": "What changes?"}
        )
        goal = GoalSlice(store, DevelopmentAdapter(), development_test=True)
        run = goal.create_run(revision, DEVELOPMENT_POLICY, scenario=scenario)
        goal.execute(run)
        issue = inspect_goal(store, run)
        assert issue["stage"] == "screening"
        assert issue["status"] == expected
        assert "preparation" not in issue["title"]


def test_diagnostics_server_never_starts_worker_or_accepts_start(tmp_path):
    import os
    import subprocess
    import sys

    code = r"""
import json,threading,urllib.request,urllib.error,sys
from co_scientist_next.store import Store
from co_scientist_next.workspace import make_server
with Store(sys.argv[1],http_threads=True) as store:
 server=make_server(store,port=0,responsive=True,development_test=True,automatic_research=True,suspend_controller_worker=True)
 threading.Thread(target=server.serve_forever,daemon=True).start()
 url='http://127.0.0.1:'+str(server.server_port)
 for _ in range(2):
  with urllib.request.urlopen(url+'/api/config') as response:assert json.load(response)['scheduling_suspended']
  req=urllib.request.Request(url+'/api/research/start',data=b'{"authorize_automatic_execution":true}',headers={'Content-Type':'application/json'})
  try:urllib.request.urlopen(req);raise AssertionError('Start accepted')
  except urllib.error.HTTPError as exc:assert exc.code==400
 assert not store.rows('SELECT * FROM attempts')
 assert not store.rows('SELECT * FROM runs')
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
