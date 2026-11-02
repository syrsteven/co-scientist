"""Real OS process restarts, including hard exit in the provider crash window."""

import json
import os
import subprocess
import sys
from pathlib import Path

from co_scientist_next.demo import registry
from co_scientist_next.scheduler import Scheduler
from co_scientist_next.store import Store

ROOT = Path(__file__).resolve().parents[2]


def child(args, **env):
    return subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src"), **env},
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )


def test_boundary_restart_duplicate_result_and_completed_run(tmp_path):
    db = str(tmp_path / "boundary.sqlite")
    first = child(["-m", "co_scientist_next", "--db", db, "--steps", "1"])
    assert first.returncode == 0, first.stderr
    before = json.loads(first.stdout)
    assert before["status"] == "ready"
    assert [t["status"] for t in before["tasks"]] == ["succeeded", "ready"]
    # A different process reopens the same file and executes only the successor.
    second = child(["-m", "co_scientist_next", "--db", db, "--run-id", before["run_id"]])
    assert second.returncode == 0, second.stderr
    after = json.loads(second.stdout)
    assert before["pid"] != after["pid"]
    assert after["status"] == "completed"
    assert before["tasks"][0] == after["tasks"][0]
    assert json.loads(after["results"][1]["output"])["doubled_length"] == 32
    with Store(db) as store:
        store.recover()
        assert (
            store.submit_result(
                before["tasks"][0]["id"], json.loads(before["results"][0]["output"])
            )
            is False
        )
        assert Scheduler(store, registry()).run(before["run_id"]) == "completed"
        assert len(store.rows("SELECT * FROM attempts")) == 2
        assert len(store.tasks(before["run_id"])) == 2
    print(
        json.dumps(
            {
                "scenario": "boundary_restart",
                "creator_pid": before["pid"],
                "resumer_pid": after["pid"],
                "run_id": before["run_id"],
                "result": 32,
                "attempts": 2,
            }
        )
    )


WORKER = r"""
import json, os
from co_scientist_next.store import Store
from co_scientist_next.scheduler import Scheduler, Registry
from co_scientist_next.contracts import CallResponse, ModuleResult
store = Store(os.environ['W0_DB'])
store.recover()
mode = os.environ['W0_MODE']
sends = os.environ['W0_SENDS']

def adapter(request):
    with open(sends, 'a') as stream:
        stream.write('sent\n')
        stream.flush()
        os.fsync(stream.fileno())
    if mode == 'in_flight':
        os._exit(73)
    return CallResponse({'actual_response': request['text']})

def module(inputs, calls):
    response = calls.execute('stable-call', 'fake/provider-v1', {'text': 'actual request'}, adapter)
    if mode == 'after_success':
        os._exit(74)
    return ModuleResult(response.output)

if mode in ('in_flight', 'after_success'):
    p = store.create_project('crash fixture')
    b = store.revise_brief(p, {'question': 'engineering only'})
    run = store.create_run(b, ['crash-fixture.v1'], policy_ref='fixture-v1')
else:
    run = os.environ['W0_RUN']
modules = Registry()
modules.register('crash-fixture.v1', module)
print(json.dumps({'pid': os.getpid(), 'run_id': run}), flush=True)
status = Scheduler(store, modules).run(run)
print(json.dumps({'pid': os.getpid(), 'run_id': run, 'status': status,
                  'attempts': store.rows('SELECT id,status,previous_id FROM attempts')}), flush=True)
store.close()
"""


def test_crash_after_success_replays_without_second_send(tmp_path):
    db, sends = str(tmp_path / "success.sqlite"), str(tmp_path / "sends.txt")
    crashed = child(["-c", WORKER], W0_DB=db, W0_SENDS=sends, W0_MODE="after_success")
    assert crashed.returncode == 74, crashed.stderr
    before = json.loads(crashed.stdout)
    resumed = child(
        ["-c", WORKER], W0_DB=db, W0_SENDS=sends, W0_MODE="resume", W0_RUN=before["run_id"]
    )
    assert resumed.returncode == 0, resumed.stderr
    after = json.loads(resumed.stdout.splitlines()[-1])
    assert before["pid"] != after["pid"]
    assert after["status"] == "completed"
    assert Path(sends).read_text().splitlines() == ["sent"]
    assert len(after["attempts"]) == 1
    with Store(db) as store:
        assert len(store.rows("SELECT * FROM execution_facts WHERE kind='call_replayed'")) == 1
        assert store.usage(run_id=before["run_id"])["cost"] == {
            "known_total": None,
            "unknown_attempts": 1,
        }
    print(
        json.dumps(
            {
                "scenario": "crash_after_saved_success",
                "creator_pid": before["pid"],
                "resumer_pid": after["pid"],
                "external_sends": 1,
                "attempts": 1,
                "status": after["status"],
            }
        )
    )


def test_crash_during_send_is_uncertain_and_requires_reasoned_retry(tmp_path):
    db, sends = str(tmp_path / "ambiguous.sqlite"), str(tmp_path / "sends.txt")
    crashed = child(["-c", WORKER], W0_DB=db, W0_SENDS=sends, W0_MODE="in_flight")
    assert crashed.returncode == 73, crashed.stderr
    before = json.loads(crashed.stdout)
    blocked = child(
        ["-c", WORKER], W0_DB=db, W0_SENDS=sends, W0_MODE="resume", W0_RUN=before["run_id"]
    )
    assert blocked.returncode == 0, blocked.stderr
    blocked_state = json.loads(blocked.stdout.splitlines()[-1])
    assert blocked_state["status"] == "blocked"
    assert Path(sends).read_text().splitlines() == ["sent"]
    with Store(db) as store:
        attempt = store.one("SELECT * FROM attempts")
        assert attempt["status"] == "uncertain"
        assert json.loads(attempt["error"])["type"] == "ProcessInterrupted"
        assert all(value is None for value in json.loads(attempt["usage"]).values())
        assert not store.rows("SELECT * FROM results")
        store.authorize_uncertain_retry(
            attempt["id"], "Fixture operator accepts possible duplicate send"
        )
        store.retry_task(attempt["task_id"], "Explicit retry after ambiguous provider outcome")
    resumed = child(
        ["-c", WORKER], W0_DB=db, W0_SENDS=sends, W0_MODE="resume", W0_RUN=before["run_id"]
    )
    assert resumed.returncode == 0, resumed.stderr
    after = json.loads(resumed.stdout.splitlines()[-1])
    assert after["status"] == "completed"
    assert [a["status"] for a in after["attempts"]] == ["uncertain", "succeeded"]
    assert after["attempts"][1]["previous_id"] == after["attempts"][0]["id"]
    assert Path(sends).read_text().splitlines() == ["sent", "sent"]
    print(
        json.dumps(
            {
                "scenario": "crash_during_send",
                "creator_pid": before["pid"],
                "blocked_pid": blocked_state["pid"],
                "resumer_pid": after["pid"],
                "sends_before_authorization": 1,
                "sends_after_authorization": 2,
                "attempt_states": ["uncertain", "succeeded"],
            }
        )
    )
