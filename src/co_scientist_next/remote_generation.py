"""P08-only remote continuation over M15; no automatic polling or migration."""

import json
from datetime import UTC, datetime

from .calls import TaskCalls
from .contracts import KnownCallFailure, UncertainCall
from .generation_ops import parse_candidate
from .responses_model import PENDING, OpenAIResponses
from .store import encode, now


def remote_snapshot(store, task_id):
    rows = store.rows("SELECT * FROM remote_generations WHERE task_id=?", (task_id,))
    if not rows:
        return None
    row = rows[0]
    row["latest_query"] = json.loads(row["latest_query"]) if row["latest_query"] else None
    row.pop("response")  # Full original remains in Attempts and DB, not the main page.
    end = (
        datetime.now(UTC)
        if row["status"] in PENDING
        else datetime.fromisoformat(row["observed_at"])
    )
    row["elapsed_seconds"] = max(
        0, (end - datetime.fromisoformat(row["submitted_at"])).total_seconds()
    )
    return row


class RemoteP08:
    def __init__(self, generation):
        self.g = generation
        self.store, self.adapter = generation.store, generation.adapter

    def execute(self, action, *, query=False, recover=False):
        s, a = self.store, action
        task = s.one("SELECT * FROM tasks WHERE id=?", (a["task_id"],))
        if task["status"] == "succeeded":
            return self.g.snapshot(a["run_id"])
        if not self.g.config_matches(a):
            raise ValueError("Recovery requires frozen Responses execution configuration")
        payload, binding = self.g.ready_input(a["run_id"], json.loads(a["request"]))
        if payload != json.loads(a["input"]) or binding != json.loads(a["binding"]):
            raise ValueError("Frozen generation input/provenance changed")
        self.g.clear_calls(a["run_id"], a["task_id"])
        from .generation_migration import authorize_execution

        authorize_execution(self.g, a, False)
        jobs = s.rows("SELECT * FROM remote_generations WHERE task_id=?", (a["task_id"],))
        job = jobs[0] if jobs else None
        if query and not job:
            raise ValueError(
                "No saved response ID; submission uncertainty requires explicit recovery"
            )
        if job and job["status"] not in PENDING:
            self.finish(a, job)
            return self.g.snapshot(a["run_id"])
        if not query and job:
            return self.g.snapshot(a["run_id"])
        if not self.adapter.configured or not self.adapter.authorized:
            raise ValueError("Responses credential and explicit execution authorization required")
        if not job and task["status"] not in ("ready", "running"):
            return self.g.snapshot(a["run_id"])
        if not job and task["status"] == "running" and not recover:
            raise ValueError("Explicit recovery required after interrupted submission")
        messages = self.g.messages(payload, a["prompt_version"])
        actual = (
            self.adapter.query_request(job["response_id"])
            if query
            else self.adapter.request(messages)
        )
        request = {
            "operation": (a.get("operation", "P08") + ".remote_query")
            if query
            else a.get("operation", "P08"),
            "actual_request": actual,
            "model_config": json.loads(a["config"]),
            "binding": {**binding, **json.loads(a["request"])},
            "prompt_version": a["prompt_version"],
        }
        if query:
            request["response_id"] = job["response_id"]
        else:
            request["messages"] = messages
        self.adapter.preflight(request)
        if len(encode(actual).encode()) > self.adapter.config["max_request_bytes"]:
            raise ValueError("Responses capacity exceeded; complete input retained, nothing sent")
        # Never automatically resend even a known failed submission after a crash.
        old = s.rows(
            "SELECT * FROM attempts WHERE task_id=? AND call_key='responses.submit' ORDER BY ordinal DESC",
            (a["task_id"],),
        )
        if not job and old and old[0]["status"] != "succeeded":
            if old[0]["status"] == "in_flight" and recover:
                s.recover(run_id=a["run_id"])
            return self.g.snapshot(a["run_id"])
        query_key = None
        if query:
            interrupted = s.rows(
                "SELECT * FROM attempts WHERE task_id=? AND target=? AND status IN ('in_flight','uncertain') AND NOT EXISTS (SELECT 1 FROM attempts n WHERE n.task_id=attempts.task_id AND n.call_key=attempts.call_key AND n.ordinal>attempts.ordinal)",
                (a["task_id"], self.adapter.target + "/retrieve"),
            )
            if interrupted:
                if len(interrupted) != 1 or interrupted[0]["request"] != encode(request):
                    raise ValueError("Interrupted query identity needs explicit inspection")
                previous = interrupted[0]
                if previous["status"] == "in_flight":
                    s.recover(run_id=a["run_id"])
                if not previous["retry_authorization"]:
                    s.authorize_uncertain_retry(
                        previous["id"],
                        "Explicit read-only query of the same saved response ID after interruption; never authorize a generation POST",
                    )
                query_key = previous["call_key"]
        with s.db:
            s.db.execute("UPDATE tasks SET status='running' WHERE id=?", (a["task_id"],))
            s.db.execute("UPDATE runs SET status='running' WHERE id=?", (a["run_id"],))
            s.fact(
                a["task_id"], "remote_query_requested" if query else "remote_submit_requested", {}
            )
        calls = TaskCalls(s, a["task_id"])
        index = len(
            s.rows(
                "SELECT id FROM attempts WHERE task_id=? AND call_key LIKE 'responses.query.%'",
                (a["task_id"],),
            )
        )
        key = (query_key or f"responses.query.{index + 1}") if query else "responses.submit"

        def commit(output, attempt_id):
            data = OpenAIResponses.envelope(output)
            if job:
                if data["id"] != job["response_id"]:
                    raise ValueError("Remote query identity mismatch")
                s.db.execute(
                    "UPDATE remote_generations SET status=?,latest_attempt_id=?,response=?,observed_at=?,latest_query=? WHERE task_id=?",
                    (
                        data["status"],
                        attempt_id,
                        encode(output),
                        now(),
                        encode(
                            {
                                "outcome": "received",
                                "status": data["status"],
                                "at": now(),
                                "attempt_id": attempt_id,
                            }
                        ),
                        a["task_id"],
                    ),
                )
            else:
                s.db.execute(
                    "INSERT OR IGNORE INTO remote_generations VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        a["task_id"],
                        data["id"],
                        data["status"],
                        attempt_id,
                        attempt_id,
                        encode(output),
                        now(),
                        now(),
                        None,
                    ),
                )
                saved = s.one(
                    "SELECT response_id FROM remote_generations WHERE task_id=?", (a["task_id"],)
                )
                if saved["response_id"] != data["id"]:
                    raise ValueError("Remote submission identity mismatch")
            s.fact(
                a["task_id"],
                "remote_response_saved",
                {"response_id": data["id"], "status": data["status"], "attempt_id": attempt_id},
            )

        try:
            calls.execute(
                key,
                self.adapter.target + ("/retrieve" if query else "/create"),
                request,
                self.adapter,
                commit_response=commit,
            )
        except KnownCallFailure:
            if query:
                with s.db:
                    s.db.execute(
                        "UPDATE remote_generations SET latest_query=? WHERE task_id=?",
                        (
                            encode(
                                {
                                    "outcome": "query_failed",
                                    "at": now(),
                                    "remote_status_unchanged": True,
                                }
                            ),
                            a["task_id"],
                        ),
                    )
                self.wait(a)
            else:
                self.stop(a, "failed", "Submission returned a technical error; no automatic resend")
            return self.g.snapshot(a["run_id"])
        except UncertainCall:
            self.stop(
                a,
                "blocked",
                "Submission outcome uncertain; no saved ID, explicit recovery required",
            )
            return self.g.snapshot(a["run_id"])
        except Exception:  # noqa: BLE001 -- persistence/identity error never permits another POST
            self.stop(
                a,
                "blocked",
                "Remote response persistence/identity needs explicit inspection; no resend",
            )
            return self.g.snapshot(a["run_id"])
        saved = s.one("SELECT * FROM remote_generations WHERE task_id=?", (a["task_id"],))
        if saved["status"] in PENDING:
            self.wait(a)
        else:
            self.finish(a, saved)
        return self.g.snapshot(a["run_id"])

    def wait(self, a):
        with self.store.db:
            self.store.db.execute(
                "UPDATE tasks SET status='waiting_remote' WHERE id=?", (a["task_id"],)
            )
            self.store.db.execute(
                "UPDATE runs SET status='waiting_remote' WHERE id=?", (a["run_id"],)
            )

    def stop(self, a, status, message):
        with self.store.db:
            self.store.db.execute(
                "UPDATE tasks SET status=?,error=? WHERE id=?",
                (status, encode({"type": "RemoteExecution", "message": message}), a["task_id"]),
            )
            self.store.db.execute("UPDATE runs SET status=? WHERE id=?", (status, a["run_id"]))

    def finish(self, a, job):
        config, payload = json.loads(a["config"]), json.loads(a["input"])
        result = {
            "binding": {**json.loads(a["binding"]), **json.loads(a["request"])},
            "prompt_version": a["prompt_version"],
            "model_config": config,
            "execution_mode": config["execution_mode"],
            "science_validated": False,
            "remote_response_id": job["response_id"],
            "remote_status": job["status"],
            "call_provenance": {
                "task_id": a["task_id"],
                "request_id": a["request_id"],
                "submission_attempt_id": job["submission_attempt_id"],
                "attempt_id": job["latest_attempt_id"],
            },
        }
        try:
            candidate = parse_candidate(OpenAIResponses.text(json.loads(job["response"])), payload)
        except (ValueError, TypeError, KeyError, IndexError):
            result.update(
                generation_status="invalid_output",
                parse_error="Remote response incomplete or candidate contract invalid; inspect saved response",
            )
        else:
            result.update(
                generation_status="generated",
                candidate=candidate,
                candidate_status="generated_pending_candidate_ethics_r0",
            )
        from .generation import generation_route
        from .generation_migration import existing

        migration = existing(self.store, successor=a["task_id"])
        if migration:
            result["migration_provenance"] = {
                "migration_id": migration["id"],
                "source_task_id": migration["source_task_id"],
                "preview_hash": migration["preview_hash"],
            }

        with self.store.db:
            self.store.db.execute(
                "UPDATE tasks SET status='running',error=NULL WHERE id=?", (a["task_id"],)
            )
        self.store.submit_result(a["task_id"], result, stop_status=generation_route(result))
