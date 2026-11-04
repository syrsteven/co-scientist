"""Narrow M15 execution boundary, with durable per-request attempts."""

import json
import math
from dataclasses import asdict

from .contracts import CallResponse, KnownCallFailure, TransportUncertain, UncertainCall, Usage
from .store import encode, identity, now


def checked_usage(usage):
    values = asdict(usage)
    for key, value in values.items():
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("Usage must be numeric or unknown")
            if value < 0 or not math.isfinite(value):
                raise ValueError("Usage must be finite and nonnegative")
            if key != "cost" and not isinstance(value, int):
                raise ValueError("Token/tool counts must be integers")
    return encode(values)


class TaskCalls:
    def __init__(self, store, task_id):
        self.store = store
        self.task_id = task_id

    def execute(self, key, target, request, invoke, *, max_attempts=1):
        if (
            not key
            or not target
            or isinstance(max_attempts, bool)
            or not isinstance(max_attempts, int)
            or max_attempts < 1
        ):
            raise ValueError("Call key, target and positive attempt limit required")
        request_json = encode(request)  # Detach from caller/provider mutable state.
        store = self.store
        task = store.one("SELECT status FROM tasks WHERE id=?", (self.task_id,))
        if task["status"] != "running":
            raise ValueError("Calls require an executing Task")
        attempts = store.rows(
            """SELECT * FROM attempts WHERE task_id=? AND call_key=?
                                 ORDER BY ordinal""",
            (self.task_id, key),
        )
        for attempt in attempts:
            if attempt["target"] != target or attempt["request"] != request_json:
                raise ValueError("Stable call key reused with different actual input/target")
        previous = attempts[-1] if attempts else None
        if previous and previous["status"] == "succeeded":
            with store.db:
                store.fact(self.task_id, "call_replayed", {"attempt_id": previous["id"]})
            return CallResponse(
                json.loads(previous["response"]), Usage(**json.loads(previous["usage"]))
            )
        if (
            previous
            and previous["status"] in ("uncertain", "in_flight")
            and (previous["status"] == "in_flight" or not previous["retry_authorization"])
        ):
            raise UncertainCall(f"Unresolved Attempt {previous['id']}")
        # This is a per-invocation bound, not a user resource budget. Every send
        # is an Attempt; known failures can be retried, ambiguity cannot.
        for _ in range(max_attempts):
            attempt_id = identity()
            with store.db:
                store.db.execute(
                    """INSERT INTO attempts
                    (id,task_id,call_key,target,request,ordinal,previous_id,status,usage,started_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (
                        attempt_id,
                        self.task_id,
                        key,
                        target,
                        request_json,
                        previous["ordinal"] + 1 if previous else 1,
                        previous["id"] if previous else None,
                        "in_flight",
                        checked_usage(Usage()),
                        now(),
                    ),
                )
            try:
                response = invoke(json.loads(request_json))
                if not isinstance(response, CallResponse):
                    raise TypeError("Adapter must return CallResponse")
                response_json = encode(response.output)
                usage_json = checked_usage(response.usage)
            except Exception as exc:
                known = isinstance(exc, KnownCallFailure)
                error = encode(
                    exc.error_record()
                    if isinstance(exc, TransportUncertain)
                    else {"type": type(exc).__name__, "message": str(exc)}
                )
                # A malformed adapter response also leaves effects uncertain.
                try:
                    usage_json = checked_usage(exc.usage) if known else checked_usage(Usage())
                    response_json = encode(exc.response) if known else None
                except (ValueError, TypeError):
                    known = False
                    usage_json, response_json = checked_usage(Usage()), None
                with store.db:
                    store.db.execute(
                        """UPDATE attempts SET status=?,response=?,error=?,usage=?,
                                        finished_at=? WHERE id=?""",
                        (
                            "failed" if known else "uncertain",
                            response_json,
                            error,
                            usage_json,
                            now(),
                            attempt_id,
                        ),
                    )
                if not known:
                    raise UncertainCall(f"Unresolved Attempt {attempt_id}") from exc
                previous = store.one("SELECT * FROM attempts WHERE id=?", (attempt_id,))
                last_error = exc
            else:
                # If persistence fails after the send, the in-flight fact remains;
                # recovery treats it as uncertain, never as safe to resend.
                with store.db:
                    store.db.execute(
                        """UPDATE attempts SET status='succeeded',response=?,usage=?,
                                        finished_at=? WHERE id=?""",
                        (response_json, usage_json, now(), attempt_id),
                    )
                return CallResponse(json.loads(response_json), response.usage)
        raise last_error
