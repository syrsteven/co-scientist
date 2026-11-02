"""W0 engineering acceptance; these are not scientific workflow tests."""

import hashlib
import json
from pathlib import Path

import pytest

from co_scientist_next.calls import TaskCalls
from co_scientist_next.contracts import (
    CallResponse,
    KnownCallFailure,
    ModuleResult,
    TaskInput,
    UncertainCall,
    Usage,
)
from co_scientist_next.demo import create_demo, double_measurement, measure_text, registry
from co_scientist_next.scheduler import Registry, Scheduler
from co_scientist_next.store import Store


@pytest.fixture
def store(tmp_path):
    with Store(tmp_path / "runtime.sqlite") as value:
        yield value


def running_task(store, module="fixture.measure.v1"):
    project = store.create_project("P")
    revision = store.revise_brief(project, {"question": "abc"})
    run = store.create_run(revision, [module], policy_ref="test-policy-v1")
    task = store.tasks(run)[0]
    with store.db:
        store.db.execute("UPDATE tasks SET status='running' WHERE id=?", (task["id"],))
        store.db.execute("UPDATE runs SET status='running' WHERE id=?", (run,))
    return run, task["id"], TaskCalls(store, task["id"])


def test_two_steps_and_exact_actual_inputs(store):
    run = create_demo(store)
    scheduler = Scheduler(store, registry())
    assert scheduler.step(run)
    first, second = store.tasks(run)
    assert first["status"] == "succeeded"
    assert second["status"] == "ready"
    assert json.loads(second["input"])["previous_result"]["length"] == 16
    assert scheduler.run(run) == "completed"
    attempts = store.rows("SELECT * FROM attempts ORDER BY started_at")
    assert len(attempts) == 2
    assert json.loads(attempts[0]["request"]) == {"text": "engineering only"}
    assert json.loads(attempts[1]["request"]) == {"value": 16}
    assert json.loads(attempts[1]["response"]) == {"value": 32}
    assert all(a["status"] == "succeeded" and a["finished_at"] for a in attempts)
    assert store.run(run)["goal_context_ref"] is None
    assert len(store.rows("SELECT * FROM results")) == 2


def test_brief_revision_and_detached_input_snapshot(store):
    project = store.create_project("P")
    brief = {"question": "original", "materials": ["source-1"]}
    revision = store.revise_brief(project, brief)
    run = store.create_run(
        revision,
        ["fixture.measure.v1", "fixture.double.v1"],
        policy_ref="policy-original",
        goal_context_ref="M01-owned-ref",
    )
    brief["materials"].append("caller-mutation")
    new = store.revise_brief(project, {"question": "replacement"}, revision)
    scheduler = Scheduler(store, registry())
    scheduler.step(run)
    # Editing between steps must also leave the downstream input unchanged.
    store.revise_brief(project, {"question": "another-edit"}, new)
    assert scheduler.run(run) == "completed"
    for task in store.tasks(run):
        inputs = json.loads(task["input"])
        assert inputs["brief_revision_id"] == revision
        assert inputs["brief"] == {"question": "original", "materials": ["source-1"]}
        assert inputs["goal_context_ref"] == "M01-owned-ref"
        assert inputs["policy_ref"] == "policy-original"
    request = json.loads(
        store.one("SELECT request FROM attempts ORDER BY started_at LIMIT 1")["request"]
    )
    assert request == {"text": "original"}
    other = store.create_project("Other")
    with pytest.raises(ValueError, match="another Project"):
        store.revise_brief(other, {}, revision)


def test_duplicate_result_before_and_after_downstream(store):
    run = create_demo(store)
    scheduler = Scheduler(store, registry())
    assert scheduler.step(run)
    first = store.tasks(run)[0]
    result = json.loads(
        store.one("SELECT output FROM results WHERE task_id=?", (first["id"],))["output"]
    )
    for _ in range(3):
        assert store.submit_result(first["id"], result) is False
    assert len(store.tasks(run)) == 2
    assert scheduler.run(run) == "completed"
    assert store.submit_result(first["id"], result) is False
    assert scheduler.run(run) == "completed"
    assert len(store.rows("SELECT * FROM attempts")) == 2
    assert len(store.rows("SELECT * FROM execution_facts WHERE kind='result_applied'")) == 2
    with pytest.raises(ValueError, match="Conflicting"):
        store.submit_result(first["id"], {"different": True})
    assert len(store.tasks(run)) == 2


def test_module_failure_is_locatable_and_retry_preserves_history(store):
    run, task_id, _ = running_task(store, "broken.v1")
    with store.db:
        store.db.execute("UPDATE tasks SET status='ready' WHERE id=?", (task_id,))
    modules = Registry()

    def broken(inputs, calls):
        raise ValueError("fixture failure")

    modules.register("broken.v1", broken)
    assert Scheduler(store, modules).run(run) == "failed"
    task = store.tasks(run)[0]
    assert json.loads(task["error"]) == {
        "type": "ValueError",
        "message": "fixture failure",
        "module": "broken.v1",
    }
    assert not store.rows("SELECT * FROM results")
    assert len(store.tasks(run)) == 1
    store.retry_task(task_id, "fixed module implementation")
    fixed = Registry()
    fixed.register("broken.v1", lambda inputs, calls: ModuleResult({"fixed": True}))
    assert Scheduler(store, fixed).run(run) == "completed"
    facts = store.rows("SELECT * FROM execution_facts WHERE kind='task_error'")
    assert "fixture failure" in facts[0]["detail"]


def test_known_failure_retries_usage_and_local_replay(store):
    run, task_id, calls = running_task(store)
    sends = []

    def adapter(request):
        sends.append(request)
        if len(sends) == 1:
            raise KnownCallFailure("fixture overload", response={"error": "overload"})
        return CallResponse({"answer": 9}, Usage(input_tokens=5, output_tokens=2, cost=0.03))

    response = calls.execute(
        "stable", "fake/model-v1", {"prompt": "actual visible text"}, adapter, max_attempts=2
    )
    assert response.output == {"answer": 9}
    before = store.usage(run_id=run)
    assert (
        calls.execute(
            "stable",
            "fake/model-v1",
            {"prompt": "actual visible text"},
            lambda _: pytest.fail("Replay sent external request"),
        )
        == response
    )
    assert store.usage(run_id=run) == before
    assert before["input_tokens"] == {"known_total": 5, "unknown_attempts": 1}
    assert before["cost"] == {"known_total": 0.03, "unknown_attempts": 1}
    assert before["tool_units"] == {"known_total": None, "unknown_attempts": 2}
    assert store.usage(run_id=run, task_id=task_id) == before
    attempts = store.rows("SELECT * FROM attempts ORDER BY ordinal")
    assert [a["status"] for a in attempts] == ["failed", "succeeded"]
    assert attempts[1]["previous_id"] == attempts[0]["id"]
    assert json.loads(attempts[0]["response"]) == {"error": "overload"}
    assert json.loads(attempts[0]["error"])["message"] == "fixture overload"
    assert len(sends) == 2
    with pytest.raises(ValueError, match="different actual input"):
        calls.execute("stable", "fake/model-v1", {"prompt": "changed"}, adapter)


def test_known_failure_exhaustion_is_failed_not_scientific_unknown(store):
    run = create_demo(store)
    modules = Registry()

    def failing(inputs, calls):
        def adapter(_):
            raise KnownCallFailure("failed response", usage=Usage(tool_units=1))

        calls.execute("call", "fake/tool", {"query": "actual query"}, adapter, max_attempts=2)
        return ModuleResult({"should": "never reach"})

    modules.register("fixture.measure.v1", failing)
    assert Scheduler(store, modules).run(run) == "failed"
    assert len(store.tasks(run)) == 1
    assert not store.rows("SELECT * FROM results")
    assert len(store.rows("SELECT * FROM attempts")) == 2
    assert store.usage(run_id=run)["tool_units"] == {"known_total": 2, "unknown_attempts": 0}


def test_ambiguous_timeout_blocks_resend_until_explicit_decision(store):
    run, task_id, calls = running_task(store)
    sends = []

    def timeout(request):
        sends.append(request)
        raise TimeoutError("fixture response lost after send")

    with pytest.raises(UncertainCall):
        calls.execute("call", "fake/tool", {"input": 1}, timeout, max_attempts=3)
    with pytest.raises(UncertainCall):
        calls.execute("call", "fake/tool", {"input": 1}, timeout)
    assert len(sends) == 1
    with pytest.raises(UncertainCall):
        store.submit_result(task_id, {"pretend": "success"})
    attempt = store.one("SELECT * FROM attempts")
    assert attempt["status"] == "uncertain"
    assert all(v is None for v in json.loads(attempt["usage"]).values())
    with pytest.raises(ValueError):
        store.authorize_uncertain_retry(attempt["id"], "")
    store.authorize_uncertain_retry(
        attempt["id"], "Operator accepts duplicate risk after provider check"
    )
    assert calls.execute(
        "call", "fake/tool", {"input": 1}, lambda _: CallResponse({"ok": True})
    ).output == {"ok": True}
    store.submit_result(task_id, {"ok": True})
    assert store.run(run)["status"] == "completed"
    assert store.one("SELECT * FROM attempts WHERE ordinal=2")["previous_id"] == attempt["id"]
    assert store.one("SELECT * FROM attempts WHERE ordinal=1")["status"] == "uncertain"


def test_task_result_and_next_task_are_one_transaction(store):
    run = create_demo(store)
    first = store.tasks(run)[0]
    with store.db:
        store.db.execute("UPDATE tasks SET status='running' WHERE id=?", (first["id"],))
        store.db.execute("""CREATE TRIGGER fixture_crash BEFORE INSERT ON tasks
                            WHEN NEW.step=1 BEGIN SELECT RAISE(ABORT,'fixture write failure'); END""")
    with pytest.raises(Exception, match="fixture write failure"):
        store.submit_result(first["id"], {"length": 16})
    assert not store.rows("SELECT * FROM results")
    assert store.tasks(run)[0]["status"] == "running"
    with store.db:
        store.db.execute("DROP TRIGGER fixture_crash")
    store.recover()
    assert Scheduler(store, registry()).run(run) == "completed"
    assert len(store.tasks(run)) == 2


def test_single_runtime_lock(store):
    path = store.db.execute("PRAGMA database_list").fetchone()[2]
    with pytest.raises(RuntimeError, match="active runtime"):
        Store(path)


def test_registry_and_independently_callable_modules():
    modules = registry()
    with pytest.raises(ValueError, match="already registered"):
        modules.register("fixture.measure.v1", measure_text)

    class DirectCalls:
        def execute(self, key, target, request, invoke, **kwargs):
            return invoke(request)

    inputs = TaskInput("t", "r", "b", {"question": "abc"}, "fixture", None, None)
    result = measure_text(inputs, DirectCalls())
    assert result.output["length"] == 3
    second = TaskInput("t2", "r", "b", {"question": "abc"}, "fixture", None, result.output)
    assert double_measurement(second, DirectCalls()).output["doubled_length"] == 6


def test_design_original_bytes_match_archived_sources():
    root = Path(__file__).resolve().parents[2] / "docs/design"
    manifest = json.loads((root / "source-integrity.json").read_text())
    actual = set()
    for package in manifest.values():
        for name, digest in package["files"].items():
            assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
            actual.add(name)
    assert actual == {
        str(p.relative_to(root))
        for folder in ("m00-accepted-v1.0", "w0-proposed-v0.1")
        for p in (root / folder).rglob("*")
        if p.is_file()
    }


def test_rejects_old_or_unrelated_database(tmp_path):
    import sqlite3

    path = tmp_path / "unrelated.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE historical_run (id TEXT)")
    with pytest.raises(ValueError, match="Not a Co-Scientist Next"):
        Store(path)
    with sqlite3.connect(path) as db:
        assert [
            row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        ] == [
            "historical_run",
        ]
