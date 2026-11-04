"""Offline, standard-library-only verification; never invokes a model or network."""

import base64
import gzip
import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
FORBIDDEN = {"expected", "critical_failures", "assessment", "reviewer_answers"}


def read(name):
    return json.loads((HERE / name).read_text())


def check_input(value):
    if isinstance(value, dict):
        assert not (set(value) & FORBIDDEN)
        for child in value.values():
            check_input(child)
    elif isinstance(value, list):
        for child in value:
            check_input(child)


def main():
    for line in (HERE / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ", 1)
        path = (HERE / name).resolve()
        assert path.is_relative_to(HERE) and not (HERE / name).is_symlink()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, name
    info = read("run-preparation.json")
    manifest = read("material-manifest.json")
    config = read("model-config.json")
    assert info["model_requests_executed"] == 0 and not info["model_calls_authorized"]
    assert not info["model_key_read"] and info["goal_ethics_mode"] == "development_fixture"
    assert config["model"] == "gpt-6.1-sol" and config["timeout_seconds"] == 600
    assert config["parameters"] == {
        "reasoning_effort": "high",
        "max_completion_tokens": 32768,
        "response_format": {"type": "json_object"},
    }
    snapshot = gzip.decompress((HERE / "prepared.sqlite.gz").read_bytes())
    with tempfile.TemporaryDirectory(prefix="p04-v2-audit-") as directory:
        dbpath = Path(directory) / "isolated.sqlite"
        dbpath.write_bytes(snapshot)
        with sqlite3.connect("file:" + str(dbpath) + "?mode=ro", uri=True) as db:
            db.row_factory = sqlite3.Row
            assert db.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 1
            assert db.execute("SELECT COUNT(*) FROM brief_revisions").fetchone()[0] == 1
            assert db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
            assert db.execute("SELECT COUNT(*) FROM background_actions").fetchone()[0] == 0
            assert (
                db.execute(
                    "SELECT COUNT(*) FROM tasks WHERE module LIKE 'background.%'"
                ).fetchone()[0]
                == 0
            )
            goal_config = json.loads(db.execute("SELECT config FROM goal_run_config").fetchone()[0])
            assert goal_config["development_test"] is True
            goal = read("new-goal-context.json")
            brief = read("new-brief.json")
            assert goal["original_question"] == brief["question"] == goal["prepared_question"]
            assert [x["text"] for x in goal["hard_requirements"]] == brief["hard_constraints"]
            assert "仅检索" not in json.dumps(goal, ensure_ascii=False)
            assert "不执行模型阅读" not in json.dumps(goal, ensure_ascii=False)
            for material in manifest["materials"]:
                name = material["name"]
                payload = read(f"requests/{name}.p04-input.json")
                messages = read(f"requests/{name}.p04-messages.json")
                wire = read(f"requests/{name}.planned-http.json")
                view = read(f"views/{name}.json")
                assert set(payload) == {"goal_context", "source_view", "seed_brief"}
                check_input(payload)
                assert payload["goal_context"] == goal and payload["source_view"] == view
                assert view["run_id"] == info["run_id"] and view["id"] == material["view_id"]
                actual_view = db.execute(
                    "SELECT content FROM material_views WHERE id=?", (view["id"],)
                ).fetchone()
                assert actual_view and json.loads(actual_view[0]) == view
                obtained = gzip.decompress(
                    (HERE / f"acquisition/{name}.obtained-text.txt.gz").read_bytes()
                ).decode()
                start, end = view["character_range"]
                assert (
                    obtained[start:end] == view["text"] == (HERE / f"views/{name}.txt").read_text()
                )
                assert hashlib.sha256(obtained.encode()).hexdigest() == view["original_text_sha256"]
                assert json.loads(messages[-1]["content"]) == payload
                assert wire["body"]["messages"] == messages
                assert wire["body"]["model"] == config["model"] and wire["timeout_seconds"] == 600
                assert set(wire["body"]) == {
                    "model",
                    "messages",
                    "reasoning_effort",
                    "max_completion_tokens",
                    "response_format",
                    "n",
                    "stream",
                    "store",
                }
                assert all(wire["body"][k] == v for k, v in config["parameters"].items())
                assert (
                    len(json.dumps(wire, sort_keys=True, ensure_ascii=False).encode())
                    <= config["max_request_bytes"]
                )
                assert "source-reported findings" in messages[1]["content"]
            public = db.execute(
                "SELECT a.* FROM attempts a JOIN tasks t ON t.id=a.task_id WHERE t.module LIKE 'literature.%'"
            ).fetchall()
            assert len(public) == manifest["public_request_count"] == 5
            for entry in manifest["public_attempts"]:
                event = json.loads(gzip.decompress((HERE / entry["record"]).read_bytes()))
                row = next(a for a in public if a["id"] == event["id"])
                assert json.loads(row["request"]) == event["request"]
                assert json.loads(row["response"]) == event["response"]
                raw = base64.b64decode(event["response"]["body_base64"])
                assert hashlib.sha256(raw).hexdigest() == event["response"]["sha256"]
            assert (
                db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 7
            )  # 2 local Goal fixtures + 5 real public sends
    print(
        "Verified clean new Run, two bound views, five saved public sends, P04 v2 exports; model sends=0, no readings/seeds/readiness, science_validated=false"
    )


if __name__ == "__main__":
    main()
