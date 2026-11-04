"""Offline transport fixtures only: no credentials discovered, paid calls or science claims."""

import errno
import http.client
import json
import runpy
import socket
import ssl
import traceback
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from co_scientist_next.background import BackgroundService
from co_scientist_next.background_ops import DevelopmentReadingAdapter
from co_scientist_next.contracts import TransportUncertain
from co_scientist_next.reading_model import OpenAIChat
from co_scientist_next.store import Store

HELPERS = runpy.run_path(str(Path(__file__).with_name("test_background.py")))
SECRET = "INVENTED-TEST-SECRET-DO-NOT-RETAIN"
PRIVATE_BODY = "INVENTED-PRIVATE-REQUEST-CONTENT"
CONFIG = {
    "provider": "openai",
    "endpoint": "https://api.openai.com/v1/chat/completions",
    "model": "explicit-offline-test-model",
    "parameters": {
        "reasoning_effort": "high",
        "max_completion_tokens": 32768,
        "response_format": {"type": "json_object"},
    },
    "max_request_bytes": 262144,
    "timeout_seconds": 600,
}


@pytest.mark.parametrize(
    "phase", ["request_open", "response_read", "response_metadata", "response_close"]
)
@pytest.mark.parametrize(
    "exception,category,code",
    [
        (TimeoutError(SECRET + PRIVATE_BODY), "timeout", "ETIMEDOUT"),
        (urllib.error.URLError(TimeoutError(SECRET)), "timeout", "ETIMEDOUT"),
        (ConnectionResetError(errno.ECONNRESET, SECRET), "connection", "ECONNRESET"),
        (ssl.SSLCertVerificationError(1, SECRET), "tls", "CERTIFICATE_VERIFY_FAILED"),
        (socket.gaierror(socket.EAI_AGAIN, SECRET), "dns", "EAI_AGAIN"),
        (http.client.RemoteDisconnected(SECRET), "http_protocol", "REMOTE_DISCONNECTED"),
        (
            http.client.IncompleteRead((SECRET + PRIVATE_BODY).encode(), 999),
            "http_protocol",
            "INCOMPLETE_READ",
        ),
        (urllib.error.URLError(SECRET), "transport", "TRANSPORT_ERROR"),
    ],
)
def test_allowlisted_transport_diagnostics_without_exception_or_body(
    monkeypatch, phase, exception, category, code
):
    sends = []

    class Response:
        code = 200

        @property
        def headers(self):
            if phase == "response_metadata":
                raise exception
            return {}

        def __enter__(self):
            return self

        def __exit__(self, *_):
            if phase == "response_close":
                raise exception

        def read(self, _):
            if phase == "response_read":
                raise exception
            return b'{"choices":[],"usage":{}}'

    class Opener:
        def open(self, req, *, timeout):
            sends.append((req, timeout))
            if phase == "request_open":
                raise exception
            return Response()

    monkeypatch.setattr(urllib.request, "build_opener", lambda *_: Opener())
    adapter = OpenAIChat(CONFIG, SECRET, authorized=True)
    messages = [{"role": "user", "content": PRIVATE_BODY}]
    with pytest.raises(TransportUncertain) as caught:
        adapter({"messages": messages, "actual_request": adapter.request(messages)})
    error = caught.value.error_record()
    assert error["diagnostic"] == {"category": category, "phase": phase, "code": code}
    text = json.dumps(error) + "".join(traceback.format_exception(caught.value))
    assert SECRET not in text and PRIVATE_BODY not in text
    assert len(sends) == 1 and sends[0][1] == 600


def test_error_projection_rejects_untrusted_extra_fields_or_codes():
    error = TransportUncertain(SECRET, PRIVATE_BODY, SECRET)
    error.diagnostic["headers"] = {"Authorization": SECRET}
    error.args = (SECRET,)
    record = error.error_record()
    assert record["diagnostic"] == {
        "category": "transport",
        "phase": "unknown",
        "code": "TRANSPORT_ERROR",
    }
    assert SECRET not in json.dumps(record) and PRIVATE_BODY not in json.dumps(record)


@pytest.mark.parametrize("retry_outcome", ["stop", "length", "uncertain"])
def test_p07_retry_same_task_request_lineage_and_original_uncertainty(
    tmp_path, monkeypatch, retry_outcome
):
    fixture = DevelopmentReadingAdapter()
    sends = []

    class Response:
        code = 200

        def __init__(self, body):
            self.body = body
            self.headers = {"Content-Type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def read(self, _):
            return self.body

    class Opener:
        def open(self, req, *, timeout):
            sends.append(req.data)
            assert timeout == 600
            if len(sends) == 1 or retry_outcome == "uncertain":
                raise urllib.error.URLError(TimeoutError(SECRET + PRIVATE_BODY))
            body = json.loads(req.data)
            content = fixture({"operation": "P07", "messages": body["messages"]}).output[
                "raw_response"
            ]
            return Response(
                json.dumps(
                    {
                        "choices": [
                            {"finish_reason": retry_outcome, "message": {"content": content}}
                        ],
                        "usage": {
                            "prompt_tokens": 200,
                            "completion_tokens": 50,
                            "total_tokens": 250,
                            "completion_tokens_details": {"reasoning_tokens": 12},
                        },
                    }
                ).encode()
            )

    monkeypatch.setattr(urllib.request, "build_opener", lambda *_: Opener())
    db = tmp_path / "offline-p07-recovery.sqlite"
    with Store(db) as store:
        run, service, view, lit = HELPERS["setup_flow"](store)
        flow = (store, run, service, view, lit)
        seed = HELPERS["seeds"](flow)[0]
        packet = HELPERS["packet"](flow, seed)
        service = BackgroundService(store, OpenAIChat(CONFIG, SECRET, authorized=True))
        service.submit(
            run,
            "offline-uncertain-p07",
            "P07",
            {
                "seed_id": seed["id"],
                "packet_ref": packet["request_id"],
                "requested_specificity": "exploratory relation, causal bridge not already proven",
            },
        )
        first = service.execute("offline-uncertain-p07")["actions"][-1]
        assert first["task_status"] == "blocked" and first["result"] is None
        old = store.one("SELECT * FROM attempts WHERE task_id=?", (first["task_id"],))
        task_count = len(store.tasks(run))
        frozen_action = store.one(
            "SELECT * FROM background_actions WHERE task_id=?", (first["task_id"],)
        )
    # A new runtime does not itself authorize another send.
    with Store(db) as store:
        service = BackgroundService(store, OpenAIChat(CONFIG, SECRET, authorized=True))
        service.execute("offline-uncertain-p07", recover=True)
        assert len(sends) == 1
        store.authorize_uncertain_retry(
            old["id"], "Explicit fixture approval accepting duplicate execution and billing"
        )
        store.retry_task(first["task_id"], "Explicit one-attempt fixture recovery")
        recovered = service.execute("offline-uncertain-p07")["actions"][-1]
        attempts = store.rows(
            "SELECT * FROM attempts WHERE task_id=? ORDER BY ordinal", (first["task_id"],)
        )
        assert len(attempts) == 2 and len(store.tasks(run)) == task_count
        assert attempts[1]["previous_id"] == old["id"] and attempts[1]["ordinal"] == 2
        assert (
            attempts[1]["call_key"] == old["call_key"] and attempts[1]["request"] == old["request"]
        )
        assert (
            store.one("SELECT * FROM background_actions WHERE task_id=?", (first["task_id"],))
            == frozen_action
        )
        assert {k: v for k, v in attempts[0].items() if k != "retry_authorization"} == {
            k: v for k, v in old.items() if k != "retry_authorization"
        }
        assert attempts[0]["status"] == "uncertain" and all(
            v is None for v in json.loads(attempts[0]["usage"]).values()
        )
        assert attempts[1]["retry_authorization"] is None
        if retry_outcome == "uncertain":
            assert attempts[1]["status"] == "uncertain" and recovered["result"] is None
            assert all(v is None for v in json.loads(attempts[1]["usage"]).values())
        else:
            assert attempts[1]["status"] == "succeeded"
            result = recovered["result"]
            assert result["background_status"] == (
                "saved" if retry_outcome == "stop" else "invalid_output"
            )
            response = json.loads(attempts[1]["response"])
            assert response["provider_usage"]["completion_tokens_details"]["reasoning_tokens"] == 12
        service.execute("offline-uncertain-p07", recover=True)
        assert len(sends) == 2 and sends[0] == sends[1]
        dump = "\n".join(store.db.iterdump())
        assert SECRET not in dump and PRIVATE_BODY not in dump
        diagnostic = json.loads(attempts[0]["error"])["diagnostic"]
        assert diagnostic == {"category": "timeout", "phase": "request_open", "code": "ETIMEDOUT"}
