"""Prompt identity/recovery checks only; no claim of real model compliance."""

import json
import runpy
import sqlite3
from pathlib import Path

import pytest

from co_scientist_next import background as background_module
from co_scientist_next.background import BackgroundService
from co_scientist_next.background_ops import (
    LEGACY_P04_PROMPT,
    P04_PROMPT_VERSION,
    PROMPT_VERSION,
    DevelopmentReadingAdapter,
    operation_prompt,
    operation_prompt_version,
)
from co_scientist_next.reading_model import OpenAIChat
from co_scientist_next.store import Store

ROOT = Path(__file__).resolve().parents[2]
HELPERS = runpy.run_path(str(Path(__file__).with_name("test_background.py")))
ARCHIVE = ROOT / "docs/trials/w1-l2-first-real-p04-review"


def test_first_real_request_is_still_reconstructable_without_rewriting_archive():
    payload = json.loads((ARCHIVE / "p04-input.json").read_text())
    saved_messages = json.loads((ARCHIVE / "p04-messages.json").read_text())
    service = BackgroundService(None)
    assert service.messages("P04", payload, version=PROMPT_VERSION) == saved_messages
    assert saved_messages[1]["content"] == LEGACY_P04_PROMPT
    config = json.loads((ARCHIVE / "model-config.confirmed.json").read_text())
    assert OpenAIChat(config, None).request(saved_messages) == json.loads(
        (ARCHIVE / "actual-http-request.confirmed.json").read_text()
    )
    assert service.messages("P04", payload)[1]["content"] != LEGACY_P04_PROMPT
    assert operation_prompt_version("P04") == P04_PROMPT_VERSION
    assert operation_prompt_version("P05") == PROMPT_VERSION
    with pytest.raises(ValueError):
        operation_prompt("P04", "unregistered-version")


def test_new_task_freezes_version_and_ui_snapshot_reports_it(tmp_path):
    with Store(tmp_path / "fresh.sqlite") as store:
        run, service, view, _ = HELPERS["setup_flow"](store)
        service.submit(run, "new-version-reading", "P04", {"view_id": view["id"]})
        action = service.actions(run)[0]
        assert action["prompt_version"] == P04_PROMPT_VERSION
        # Changing a default prompt alias must not mutate an already registered version.
        from co_scientist_next.background_ops import PROMPTS

        original = PROMPTS["P04"]
        try:
            PROMPTS["P04"] = "Simulated future default; never used for frozen version"
            service.execute("new-version-reading")
        finally:
            PROMPTS["P04"] = original
        action = service.actions(run)[0]
        attempt = store.one("SELECT request FROM attempts WHERE task_id=?", (action["task_id"],))
        actual = json.loads(attempt["request"])
        assert actual["prompt_version"] == P04_PROMPT_VERSION
        assert actual["messages"][1]["content"] == operation_prompt("P04", P04_PROMPT_VERSION)
        snapshot = service.snapshot(run)
        assert snapshot["current_prompt_versions"]["P04"] == P04_PROMPT_VERSION
        assert snapshot["actions"][0]["result"]["prompt_version"] == P04_PROMPT_VERSION
        assert snapshot["views"][0]["character_range"] == view["character_range"]


def test_pre_upgrade_pending_v1_action_migrates_and_executes_old_messages(tmp_path, monkeypatch):
    path = tmp_path / "legacy.sqlite"
    with Store(path) as store:
        run, service, view, _ = HELPERS["setup_flow"](store)
        monkeypatch.setattr(background_module, "operation_prompt_version", lambda _: PROMPT_VERSION)
        service.submit(run, "legacy-pending-reading", "P04", {"view_id": view["id"]})
        before = store.one("SELECT request,input,config FROM background_actions")
        store.db.execute("ALTER TABLE background_actions DROP COLUMN prompt_version")
        store.db.commit()
    monkeypatch.undo()
    with Store(path) as store:
        assert store.one("SELECT request,input,config FROM background_actions") == before
        service = BackgroundService(store, DevelopmentReadingAdapter())
        assert service.actions(run)[0]["prompt_version"] == PROMPT_VERSION
        service.execute("legacy-pending-reading")
        action = service.actions(run)[0]
        attempt = store.one(
            "SELECT request,response FROM attempts WHERE task_id=?", (action["task_id"],)
        )
        actual = json.loads(attempt["request"])
        assert actual["prompt_version"] == PROMPT_VERSION
        assert actual["messages"][1]["content"] == LEGACY_P04_PROMPT
        result = store.one("SELECT output FROM results WHERE task_id=?", (action["task_id"],))
    with Store(path) as store:
        service = BackgroundService(store, DevelopmentReadingAdapter())
        service.execute("legacy-pending-reading", recover=True)
        assert (
            store.one("SELECT request,response FROM attempts WHERE task_id=?", (action["task_id"],))
            == attempt
        )
        assert (
            store.one("SELECT output FROM results WHERE task_id=?", (action["task_id"],)) == result
        )
        assert len(store.rows("SELECT * FROM attempts WHERE task_id=?", (action["task_id"],))) == 1
    # These are persisted process-safe facts, not a rewritten legacy model result.
    with sqlite3.connect(path) as db:
        assert (
            db.execute("SELECT prompt_version FROM background_actions").fetchone()[0]
            == PROMPT_VERSION
        )


def test_v1_saved_call_recovers_in_new_process_without_resend(tmp_path, monkeypatch):
    import os
    import subprocess
    import sys

    path = tmp_path / "crashed-v1.sqlite"
    with Store(path) as store:
        run, service, view, _ = HELPERS["setup_flow"](store)
        monkeypatch.setattr(background_module, "operation_prompt_version", lambda _: PROMPT_VERSION)
        service.submit(run, "legacy-saved-call", "P04", {"view_id": view["id"]})
        service.execute("legacy-saved-call")
        action = service.actions(run)[0]
        before = store.one(
            "SELECT request,response FROM attempts WHERE task_id=?", (action["task_id"],)
        )
        # Engineering fixture: emulate loss of application after durable call success.
        with store.db:
            store.db.execute("DELETE FROM results WHERE task_id=?", (action["task_id"],))
            store.db.execute("UPDATE tasks SET status='running' WHERE id=?", (action["task_id"],))
            store.db.execute("UPDATE runs SET status='running' WHERE id=?", (run,))
            store.db.execute("ALTER TABLE background_actions DROP COLUMN prompt_version")
    monkeypatch.undo()
    code = """
import sys
from co_scientist_next.store import Store
from co_scientist_next.background import BackgroundService
from co_scientist_next.background_ops import DevelopmentReadingAdapter
class NeverSend(DevelopmentReadingAdapter):
    def __call__(self, request):
        raise AssertionError("Saved success must replay; no adapter send permitted")
with Store(sys.argv[1]) as store:
    BackgroundService(store, NeverSend()).execute("legacy-saved-call", recover=True)
"""
    subprocess.run(
        [sys.executable, "-c", code, str(path)],
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        check=True,
        capture_output=True,
        text=True,
    )
    with Store(path) as store:
        assert (
            store.one("SELECT request,response FROM attempts WHERE task_id=?", (action["task_id"],))
            == before
        )
        assert len(store.rows("SELECT * FROM attempts WHERE task_id=?", (action["task_id"],))) == 1
        assert (
            json.loads(
                store.one("SELECT output FROM results WHERE task_id=?", (action["task_id"],))[
                    "output"
                ]
            )["background_status"]
            == "saved"
        )
