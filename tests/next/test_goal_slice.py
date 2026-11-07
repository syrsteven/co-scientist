"""W0-T4 engineering gates only; fixtures do not validate scientific Ethics."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from co_scientist_next.contracts import CallResponse
from co_scientist_next.goal import (
    DEVELOPMENT_POLICY,
    PREPARE,
    SCREEN,
    DevelopmentAdapter,
    GoalSlice,
    goal_route,
)
from co_scientist_next.store import Store

ROOT = Path(__file__).resolve().parents[2]
BRIEF = {
    "question": "研究核孔蛋白磷酸化与ALS，机制尚未知。",
    "hard_constraints": ["保留磷酸化问题", "不指定具体分子"],
    "preferences": ["优先可检验性"],
    "background": "用户给出的未知机制背景。",
    "materials": ["user:reference"],
    "intended_use": "非临床概念研究",
}


@pytest.fixture
def store(tmp_path):
    with Store(tmp_path / "goal.sqlite") as value:
        yield value


def setup_run(store, *, scenario="pass", policy=DEVELOPMENT_POLICY, brief=None, adapter=None):
    project = store.create_project("Goal engineering acceptance")
    revision = store.revise_brief(project, BRIEF if brief is None else brief)
    service = GoalSlice(store, adapter or DevelopmentAdapter(), development_test=True)
    return service, service.create_run(revision, policy, scenario=scenario), project


@pytest.mark.parametrize(
    ("scenario", "status", "task_count"),
    [
        ("pass", "awaiting_background", 2),
        ("reject", "goal_rejected", 2),
        ("clarification", "awaiting_clarification", 1),
        ("risk_information", "awaiting_risk_context", 2),
        ("invalid_output", "invalid_output", 2),
        ("technical_failure", "failed", 2),
        ("uncertain_send", "blocked", 2),
    ],
)
def test_only_completed_pass_reaches_real_background_boundary(store, scenario, status, task_count):
    service, run, _ = setup_run(store, scenario=scenario)
    assert service.execute(run) == status
    snapshot = service.snapshot(run)
    assert len(snapshot["tasks"]) == task_count
    assert all(t["module"] in (PREPARE, SCREEN) for t in snapshot["tasks"])
    assert snapshot["science_validated"] is False
    completed = [
        r["output"]["ethics"]
        for r in snapshot["results"]
        if r["output"].get("ethics", {}).get("completed") is True
    ]
    assert [r["decision"] for r in completed] == (
        [scenario] if scenario in ("pass", "reject") else []
    )
    if scenario == "risk_information":
        pending = snapshot["results"][-1]["output"]["ethics"]
        assert pending["completed"] is False and "decision" not in pending
    if scenario == "invalid_output":
        assert store.rows("SELECT * FROM execution_facts WHERE kind='parse_error'")
        assert store.one(
            "SELECT response FROM attempts WHERE task_id=?", (snapshot["tasks"][-1]["id"],)
        )["response"]


def test_goal_preserves_sources_and_existing_run_after_draft_edit(store):
    policy = dict(DEVELOPMENT_POLICY)
    service, run, project = setup_run(store, policy=policy)
    original_revision = store.run(run)["revision_id"]
    second_revision = store.revise_brief(
        project, {**BRIEF, "question": "执行前已编辑的草稿"}, original_revision
    )
    policy["text"] = "UI policy changed after Run creation"
    assert service.execute(run) == "awaiting_background"
    context_ref = store.run(run)["goal_context_ref"]
    before = store.one("SELECT * FROM goal_contexts WHERE id=?", (context_ref,))
    goal = json.loads(before["content"])
    assert goal["original_question"] == goal["prepared_question"] == BRIEF["question"]
    assert goal["brief_revision_id"] == original_revision
    assert goal["supplied_background"] == BRIEF["background"]
    assert [x["text"] for x in goal["hard_requirements"]] == BRIEF["hard_constraints"]
    assert [x["text"] for x in goal["preferences"]] == BRIEF["preferences"]
    assert goal["hard_requirements"][0]["input_locator"] == "explicit_constraints[0]"
    assert goal["optional_interpretations"] == []
    assert goal["unspecified_details"]
    store.revise_brief(project, {**BRIEF, "question": "编辑后的不同问题"}, second_revision)
    assert service.snapshot(run)["policy"]["text"] == DEVELOPMENT_POLICY["text"]
    assert service.snapshot(run)["fixed_brief"] == BRIEF
    assert store.one("SELECT * FROM goal_contexts WHERE id=?", (context_ref,)) == before
    assert service.execute(run) == "awaiting_background"
    assert len(store.rows("SELECT * FROM attempts")) == 2
    for result in service.snapshot(run)["results"]:
        assert store.submit_result(result["task_id"], result["output"]) is False
    assert len(store.tasks(run)) == 2


@pytest.mark.parametrize("policy", [None, {"id": "p", "version": "", "text": "policy"}])
def test_missing_policy_is_no_decision_and_no_screen_call(store, policy):
    service, run, _ = setup_run(store, policy=policy)
    assert service.execute(run) == "missing_policy"
    assert len(store.rows("SELECT * FROM attempts")) == 1
    assert "ethics" not in service.snapshot(run)["results"][-1]["output"]


def test_required_risk_context_stops_before_external_screen(store):
    policy = {**DEVELOPMENT_POLICY, "required_information": ["intended_use"]}
    service, run, _ = setup_run(store, policy=policy, brief={**BRIEF, "intended_use": None})
    assert service.execute(run) == "awaiting_risk_context"
    assert len(store.rows("SELECT * FROM attempts")) == 1


def test_invalid_input_never_calls_adapter(store):
    service, run, _ = setup_run(store, brief={"question": ""})
    assert service.execute(run) == "invalid_input"
    assert store.rows("SELECT * FROM attempts") == []
    assert len(store.tasks(run)) == 1


class ChangedOutput(DevelopmentAdapter):
    def __init__(self, mutate, operation=PREPARE):
        self.mutate, self.operation = mutate, operation

    def __call__(self, request):
        response = super().__call__(request)
        if request["operation"] != self.operation:
            return response
        value = json.loads(response.output["raw_response"])
        self.mutate(value)
        return CallResponse({"raw_response": json.dumps(value)})


@pytest.mark.parametrize(
    "mutate",
    [
        lambda v: v.update(original_question="被改写的问题"),
        lambda v: v.update(hard_requirements=[]),
        lambda v: v.update(optional_interpretations=["改用未提供的人类iPSC模型"]),
        lambda v: v.update(additional_conditions=[
            {"text": "iPSC", "input_locator": "original_question", "supporting_span": "iPSC"}
        ]),
        lambda v: v.update(clarification_required=True),
        lambda v: v.update(
            clarification_questions=[{"question": "非关键未知", "essential": False}],
            clarification_required=True,
        ),
    ],
)
def test_unsupported_conditions_omissions_and_unfounded_clarifications_are_invalid(store, mutate):
    service, run, _ = setup_run(store, adapter=ChangedOutput(mutate))
    assert service.execute(run) == "invalid_output"
    assert len(store.tasks(run)) == 1
    assert store.run(run)["goal_context_ref"] is None


@pytest.mark.parametrize(
    "mutate",
    [
        lambda v: v.update(decision="unknown"),
        lambda v: v.update(policy_refs=["wrong-policy@v0"]),
        lambda v: v.update(rationale=""),
    ],
)
def test_third_verdict_wrong_policy_and_empty_reasons_never_complete(store, mutate):
    service, run, _ = setup_run(store, adapter=ChangedOutput(mutate, SCREEN))
    assert service.execute(run) == "invalid_output"
    assert "ethics" not in service.snapshot(run)["results"][-1]["output"]
    rows = store.rows("SELECT * FROM attempts ORDER BY started_at")
    request = json.loads(rows[1]["request"])
    assert request["prompt_version"]
    assert [m["role"] for m in request["messages"]] == ["system", "developer", "user"]
    assert json.loads(request["messages"][-1]["content"])["safety_policy"] == DEVELOPMENT_POLICY
    assert all(value is None for value in json.loads(rows[1]["usage"]).values())


def test_development_policy_and_adapter_are_not_production_defaults(store):
    with pytest.raises(ValueError, match="explicit development"):
        GoalSlice(store, DevelopmentAdapter())
    project = store.create_project("No real adapter")
    revision = store.revise_brief(project, BRIEF)
    service = GoalSlice(store)
    run = service.create_run(revision)
    assert service.execute(run) == "adapter_not_configured"
    assert store.rows("SELECT * FROM attempts") == []

    # Even an injected non-test adapter cannot use the demonstration policy in nondevelopment mode.
    class Boundary:
        target = "unconnected-real-boundary"

        def __call__(self, request):
            return DevelopmentAdapter()(request)

    nondevelopment = GoalSlice(store, Boundary())
    run2 = nondevelopment.create_run(revision, {**DEVELOPMENT_POLICY, "development_only": False})
    assert nondevelopment.execute(run2) == "invalid_policy"


def test_config_and_task_creation_roll_back_together(store):
    project = store.create_project("Atomic config")
    revision = store.revise_brief(project, BRIEF)
    with store.db:
        store.db.execute(
            "CREATE TRIGGER fail_config BEFORE INSERT ON goal_run_config BEGIN SELECT RAISE(ABORT,'config failed'); END"
        )
    with pytest.raises(Exception, match="config failed"):
        GoalSlice(store).create_run(revision)
    assert store.rows("SELECT * FROM runs") == []
    assert store.rows("SELECT * FROM tasks") == []


def test_proposal_originals_and_adopted_p08_render_are_consistent():
    import hashlib

    manifest = json.loads((ROOT / "docs/design/w1-v04-source-integrity.json").read_text())
    for name, digest in manifest["files"].items():
        assert (
            hashlib.sha256(
                (ROOT / "docs/design/w1-method-v0.4-proposed" / name).read_bytes()
            ).hexdigest()
            == digest
        )
    example = json.loads((ROOT / "docs/examples/w1-v04-adopted-worked-input.json").read_text())
    rendering = example["TransportSeedModelInputRendering"]
    payload = json.loads(rendering["example_rendered_user_message"])
    assert (
        set(payload)
        == set(rendering["assembly_fields"])
        == {
            "goal_context",
            "seed_brief",
            "readiness_record",
            "actual_frozen_seed_background_packet",
            "mode",
            "candidate_id_from_caller",
        }
    )
    assert payload["goal_context"] == example["TransportSeedBackgroundPacket"]["goal_context"]
    assert payload["seed_brief"] == example["TransportSeedBackgroundPacket"]["seed_brief"]
    assert (
        payload["readiness_record"]
        == example["TransportSeedBackgroundPacket"]["readiness_decision"]
    )
    assert payload["mode"] == "ASSUMPTION_STRUCTURED"
    assert (
        payload["actual_frozen_seed_background_packet"] == example["TransportSeedBackgroundPacket"]
    )
    assert rendering["execution_status"] == "NOT_SENT_TO_ANY_MODEL"


WORKER = r"""
import json,os
from co_scientist_next.store import Store
from co_scientist_next.goal import GoalSlice,DevelopmentAdapter,DEVELOPMENT_POLICY
import co_scientist_next.goal as goal
class Adapter(DevelopmentAdapter):
 def __call__(self,request):
  with open(os.environ['SENDS'],'a') as f:
   f.write(request['operation']+'\n');f.flush();os.fsync(f.fileno())
  return super().__call__(request)
with Store(os.environ['DB']) as store:
 service=GoalSlice(store,Adapter(),development_test=True)
 if os.environ['MODE']=='crash':
  p=store.create_project('Crash goal');b=store.revise_brief(p,{'question':'原始科研问题','hard_constraints':['只保留给定条件']})
  run=service.create_run(b,DEVELOPMENT_POLICY)
  print(json.dumps({'pid':os.getpid(),'run':run}),flush=True)
  goal.parse_prepare_v3=lambda *args:os._exit(76)
  service.execute(run)
 else:
  run=os.environ['RUN'];status=service.execute(run,recover=True)
  print(json.dumps({'pid':os.getpid(),'status':status,'goal_ref':store.run(run)['goal_context_ref']}),flush=True)
"""


def test_goal_call_replay_after_real_process_crash_before_parse(tmp_path):
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "src"),
        "DB": str(tmp_path / "crash.sqlite"),
        "SENDS": str(tmp_path / "sends"),
    }
    first = subprocess.run(
        [sys.executable, "-c", WORKER],
        env={**env, "MODE": "crash"},
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )
    assert first.returncode == 76, first.stderr
    before = json.loads(first.stdout)
    second = subprocess.run(
        [sys.executable, "-c", WORKER],
        env={**env, "MODE": "resume", "RUN": before["run"]},
        text=True,
        capture_output=True,
        check=True,
        timeout=20,
    )
    after = json.loads(second.stdout)
    assert before["pid"] != after["pid"]
    assert after["status"] == "awaiting_background" and after["goal_ref"]
    assert Path(env["SENDS"]).read_text().splitlines() == [PREPARE, SCREEN]
    print(
        json.dumps(
            {
                "scenario": "goal_saved_response_replay",
                "crashed_pid": before["pid"],
                "resumed_pid": after["pid"],
                "prepare_sends": 1,
                "screen_sends": 1,
            }
        )
    )


@pytest.mark.parametrize(
    "ethics", [{"completed": False, "decision": "pass"}, {"completed": True, "decision": "unknown"}]
)
def test_m12_requires_completed_binary_screening_result(ethics):
    with pytest.raises(ValueError, match="completed binary"):
        goal_route(SCREEN, {"execution_status": "screened", "ethics": ethics})
