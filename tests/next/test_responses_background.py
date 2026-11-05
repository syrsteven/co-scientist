"""OFFLINE transport/continuation fixtures, never a scientific or paid-model trial."""

import json
import os
import runpy
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

from co_scientist_next.contracts import TransportUncertain, Usage
from co_scientist_next.generation import GenerationService
from co_scientist_next.generation_ops import USER_FIELDS, DevelopmentGenerationAdapter
from co_scientist_next.responses_model import ENDPOINT, RETENTION, OpenAIResponses
from co_scientist_next.store import Store, encode

H = runpy.run_path(str(Path(__file__).with_name("test_generation.py")))
CONFIG = {
    "provider": "openai",
    "endpoint": ENDPOINT,
    "model": "gpt-6.1-sol",
    "parameters": {
        "reasoning_effort": "high",
        "max_completion_tokens": 32768,
        "response_format": {"type": "json_object"},
    },
    "timeout_seconds": 600,
    "total_wait_seconds": 600,
    "max_request_bytes": 262144,
    "store": True,
    "retention_ack": RETENTION,
}
SECRET = "OFFLINE-INVENTED-RESPONSES-KEY"


def envelope(status="queued", text=None, rid="resp_OFFLINE1"):
    return {
        "id": rid,
        "status": status,
        "output": (
            [
                {
                    "type": "message",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": text}],
                }
            ]
            if text is not None
            else []
        ),
        "usage": {
            "input_tokens": 101,
            "output_tokens": 70,
            "total_tokens": 171,
            "output_tokens_details": {"reasoning_tokens": 55},
        }
        if status == "completed"
        else None,
    }


class Wire:
    def __init__(self, responses):
        self.responses = list(responses)
        self.sent = []

    def open(self, req, *, timeout):
        self.sent.append((req.method, req.full_url, json.loads(req.data) if req.data else None))
        assert timeout == 600
        if not self.responses:
            raise AssertionError("Unexpected extra HTTP request")
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result

        class Response:
            code = 200

            def __enter__(self):
                self.raw = json.dumps(result).encode()
                return self

            def __exit__(self, *_):
                pass

            def read1(self, size):
                raw, self.raw = self.raw[:size], self.raw[size:]
                return raw

        return Response()


def setup(tmp_path, monkeypatch, responses):
    wire = Wire(responses)
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_: wire)
    s = Store(tmp_path / "remote.sqlite")
    run, _, request = H["prepared"](s)
    adapter = OpenAIResponses(CONFIG, SECRET, authorized=True)
    service = GenerationService(s, adapter)
    a = service.submit(run, "offline-remote-p08", request)
    return s, service, a, wire


def test_full_mapping_immediate_id_query_and_idempotence(tmp_path, monkeypatch):
    s, service, a, wire = setup(tmp_path, monkeypatch, [envelope()])
    with s:
        data = service.execute(a["request_id"])
        action = data["actions"][0]
        assert (
            action["task_status"] == "waiting_remote"
            and action["remote"]["response_id"] == "resp_OFFLINE1"
        )
        assert not action["result"] and len(wire.sent) == 1
        body = wire.sent[0][2]
        assert body == {
            "model": "gpt-6.1-sol",
            "input": service.messages(json.loads(a["input"])),
            "reasoning": {"effort": "high"},
            "max_output_tokens": 32768,
            "text": {"format": {"type": "json_object"}},
            "background": True,
            "store": True,
            "stream": False,
            "truncation": "disabled",
        }
        assert set(json.loads(body["input"][-1]["content"])) == USER_FIELDS
        text = DevelopmentGenerationAdapter()({"messages": body["input"]}).output["raw_response"]
        wire.responses += [envelope("in_progress"), envelope("completed", text)]
        service.execute(a["request_id"], recover=True)  # Not even an implicit GET.
        assert len(wire.sent) == 1
        service.query_remote(a["request_id"])
        result = service.query_remote(a["request_id"])["actions"][0]["result"]
        assert result["generation_status"] == "generated" and not result["science_validated"]
        assert result["remote_response_id"] == "resp_OFFLINE1"
        assert [x[0] for x in wire.sent] == ["POST", "GET", "GET"]
        assert all(x[1] == ENDPOINT + "/resp_OFFLINE1" for x in wire.sent[1:])
        service.query_remote(a["request_id"])
        service.execute(a["request_id"], recover=True)
        assert len(wire.sent) == 3
        attempts = s.rows(
            "SELECT * FROM attempts WHERE task_id=? ORDER BY started_at", (a["task_id"],)
        )
        assert len(attempts) == 3
        response = json.loads(attempts[-1]["response"])
        assert response["provider_usage"]["output_tokens_details"]["reasoning_tokens"] == 55
        assert json.loads(attempts[0]["usage"]) == {
            "input_tokens": None,
            "output_tokens": None,
            "cost": None,
            "tool_units": None,
        }
        assert SECRET not in "\n".join(s.db.iterdump())


@pytest.mark.parametrize("status", ["failed", "incomplete", "cancelled", "completed"])
@pytest.mark.parametrize("text", [None, "", '{"incomplete":'])
def test_terminal_incomplete_or_bad_contract_never_saves_candidate(
    tmp_path, monkeypatch, status, text
):
    s, gen, a, wire = setup(tmp_path, monkeypatch, [envelope(status, text)])
    with s:
        result = gen.execute(a["request_id"])["actions"][0]["result"]
        assert result["generation_status"] == "invalid_output" and "candidate" not in result
        gen.execute(a["request_id"], recover=True)
        assert len(wire.sent) == 1


@pytest.mark.parametrize(
    "failure",
    [TimeoutError(SECRET), {"status": "completed"}],
)
def test_ambiguous_submission_preserves_unknown_and_never_recreates(tmp_path, monkeypatch, failure):
    s, gen, a, wire = setup(tmp_path, monkeypatch, [failure])
    with s:
        record = gen.execute(a["request_id"])["actions"][0]
        assert record["task_status"] == "blocked" and record["remote"] is None
        attempt = s.one(
            "SELECT * FROM attempts WHERE task_id=? ORDER BY started_at", (a["task_id"],)
        )
        assert attempt["status"] == "uncertain" and json.loads(attempt["usage"])["cost"] is None
        if isinstance(failure, dict):
            assert json.loads(attempt["response"])["raw_response"]
        else:
            assert json.loads(attempt["error"])["elapsed_seconds"] >= 0
        gen.execute(a["request_id"], recover=True)
        with pytest.raises(ValueError, match="No saved response ID"):
            gen.query_remote(a["request_id"])
        assert len(wire.sent) == 1 and SECRET not in "\n".join(s.db.iterdump())
        with pytest.raises(ValueError):
            # New API/task identity cannot bypass an unresolved send in this Run.
            gen.submit(
                a["run_id"],
                "attempt-bypass-remote",
                {**json.loads(a["request"]), "candidate_id": "another-id"},
            )


def test_query_disconnect_keeps_id_and_allows_only_explicit_same_id_read(tmp_path, monkeypatch):
    s, gen, a, wire = setup(
        tmp_path, monkeypatch, [envelope(), TimeoutError(SECRET), envelope("in_progress")]
    )
    with s:
        gen.execute(a["request_id"])
        record = gen.query_remote(a["request_id"])["actions"][0]
        assert record["task_status"] == "waiting_remote" and record["remote"]["status"] == "queued"
        assert record["remote"]["latest_query"]["outcome"] == "query_failed"
        gen.execute(a["request_id"], recover=True)
        assert len(wire.sent) == 2
        gen.query_remote(a["request_id"])
        assert [x[0] for x in wire.sent] == ["POST", "GET", "GET"]
        assert SECRET not in "\n".join(s.db.iterdump())


def test_id_and_attempt_are_committed_atomically_before_any_query(tmp_path, monkeypatch):
    s, gen, a, wire = setup(tmp_path, monkeypatch, [envelope()])
    with s:

        def crash(_self, _action):
            assert s.one(
                "SELECT response_id FROM remote_generations WHERE task_id=?", (a["task_id"],)
            )["response_id"]
            assert (
                s.one("SELECT status FROM attempts WHERE task_id=?", (a["task_id"],))["status"]
                == "succeeded"
            )
            raise RuntimeError("OFFLINE process interrupted after ID commit")

        monkeypatch.setattr("co_scientist_next.remote_generation.RemoteP08.wait", crash)
        with pytest.raises(RuntimeError):
            gen.execute(a["request_id"])
        assert len(wire.sent) == 1


def test_cross_process_continuation_never_posts_again(tmp_path, monkeypatch):
    s, gen, a, _wire = setup(tmp_path, monkeypatch, [envelope()])
    with s:
        gen.execute(a["request_id"])
    child = r"""
import runpy,sys,urllib.request
from co_scientist_next.responses_model import OpenAIResponses
from co_scientist_next.generation import GenerationService
from co_scientist_next.store import Store
h=runpy.run_path(sys.argv[2]); wire=h['Wire']([h['envelope']('in_progress')])
urllib.request.build_opener=lambda *_:wire
with Store(sys.argv[1]) as s:
 gen=GenerationService(s,OpenAIResponses(h['CONFIG'],h['SECRET'],authorized=True))
 gen.execute('offline-remote-p08',recover=True)
 assert not wire.sent
 record=gen.query_remote('offline-remote-p08')['actions'][0]
 assert record['remote']['status']=='in_progress'
 assert [x[0] for x in wire.sent]==['GET']
 assert len(s.rows("SELECT * FROM attempts WHERE call_key='responses.submit'"))==1
"""
    subprocess.run(
        [
            sys.executable,
            "-c",
            child,
            str(tmp_path / "remote.sqlite"),
            str(Path(__file__).resolve()),
        ],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")},
        check=True,
    )


def test_missing_config_no_fallback_and_secret_rejection():
    for patch in (
        {"store": False},
        {"retention_ack": ""},
        {"model": "other"},
        {"parameters": {**CONFIG["parameters"], "temperature": 1}},
        {"total_wait_seconds": float("nan")},
    ):
        with pytest.raises(ValueError):
            OpenAIResponses({**CONFIG, **patch}, SECRET)
    adapter = OpenAIResponses(CONFIG, SECRET, authorized=True)
    with pytest.raises(ValueError):
        adapter.preflight({"arbitrary": SECRET})
    bad = TransportUncertain(SECRET, SECRET, SECRET, elapsed_seconds=SECRET)
    assert SECRET not in encode(bad.error_record())
    assert Usage().cost is None


def test_safe_proxy_inspection(monkeypatch):
    from co_scientist_next.responses_model import proxy_facts

    monkeypatch.setattr(
        urllib.request,
        "getproxies",
        lambda: {
            "https": "http://user:PRIVATE@localhost:8080/path?secret=yes",
            "no": "private.test",
        },
    )
    monkeypatch.setattr(urllib.request, "proxy_bypass", lambda _: False)
    facts = proxy_facts()
    assert facts["effective_proxies"]["https"]["credentials_present"]
    assert (
        not facts["route_confirmed"]
        and "PRIVATE" not in encode(facts)
        and "secret" not in encode(facts)
    )


@pytest.mark.parametrize("phase", ["connect", "waiting_headers", "response_read"])
def test_transport_phases_monotonic_and_secret_protection(monkeypatch, phase):
    from co_scientist_next.responses_model import TrackedHandler

    adapter = OpenAIResponses(CONFIG, SECRET, authorized=True)
    messages = [{"role": "user", "content": "OFFLINE transport JSON fixture"}]

    def opener(*handlers):
        trace = next(h.trace for h in handlers if isinstance(h, TrackedHandler))

        class Opener:
            def open(self, *_a, **_kw):
                trace["phase"] = phase
                raise TimeoutError("Authorization: Bearer " + SECRET)

        return Opener()

    monkeypatch.setattr(urllib.request, "build_opener", opener)
    with pytest.raises(TransportUncertain) as caught:
        adapter({"messages": messages, "actual_request": adapter.request(messages)})
    error = caught.value.error_record()
    assert error["diagnostic"]["phase"] == phase
    assert error["elapsed_seconds"] >= 0 and SECRET not in encode(error)


def test_deadline_stops_dripping_body_without_repeated_socket_timeout(monkeypatch):
    import co_scientist_next.responses_model as module

    adapter = OpenAIResponses(CONFIG, SECRET, authorized=True)
    clock = [0.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])

    class Response:
        code = 200

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def read1(self, _):
            clock[0] += 301  # Each individual read is faster than socket's 600s.
            return b" "

    class Opener:
        def open(self, *_a, **_kw):
            return Response()

    monkeypatch.setattr(urllib.request, "build_opener", lambda *_: Opener())
    messages = [{"role": "user", "content": "OFFLINE JSON"}]
    with pytest.raises(TransportUncertain) as caught:
        adapter({"messages": messages, "actual_request": adapter.request(messages)})
    assert clock[0] == 602 and caught.value.error_record()["diagnostic"]["phase"] == "response_read"


def test_incomplete_reasoning_budget_usage_retained(tmp_path, monkeypatch):
    result = envelope("incomplete", "{}")
    result["incomplete_details"] = {"reason": "max_output_tokens"}
    result["usage"] = {
        "input_tokens": 50,
        "output_tokens": 32768,
        "output_tokens_details": {"reasoning_tokens": 32760},
    }
    s, gen, a, _wire = setup(tmp_path, monkeypatch, [result])
    with s:
        record = gen.execute(a["request_id"])["actions"][0]
        assert record["result"]["generation_status"] == "invalid_output"
        raw = json.loads(
            s.one("SELECT response FROM attempts WHERE task_id=?", (a["task_id"],))["response"]
        )
        assert raw["provider_usage"] == result["usage"]
        assert (
            json.loads(raw["raw_response"])["incomplete_details"]["reason"] == "max_output_tokens"
        )


def test_query_identity_mismatch_never_rebinds(tmp_path, monkeypatch):
    s, gen, a, wire = setup(
        tmp_path, monkeypatch, [envelope(), envelope("completed", "{}", "resp_FOREIGN")]
    )
    with s:
        gen.execute(a["request_id"])
        remote = gen.query_remote(a["request_id"])["actions"][0]["remote"]
        assert remote["response_id"] == "resp_OFFLINE1" and remote["status"] == "queued"
        assert remote["latest_query"]["outcome"] == "query_failed" and len(wire.sent) == 2


def test_cross_process_crash_after_id_commit_before_wait(tmp_path):
    db = tmp_path / "crash-id.sqlite"
    child = r"""
import os,runpy,sys,urllib.request
from co_scientist_next.store import Store
from co_scientist_next.generation import GenerationService
from co_scientist_next.responses_model import OpenAIResponses
from co_scientist_next.remote_generation import RemoteP08
h=runpy.run_path(sys.argv[2]); w=h['Wire']([h['envelope']()]); urllib.request.build_opener=lambda *_:w
with Store(sys.argv[1]) as s:
 run,_,request=h['H']['prepared'](s)
 g=GenerationService(s,OpenAIResponses(h['CONFIG'],h['SECRET'],authorized=True))
 g.submit(run,'offline-remote-p08',request)
 RemoteP08.wait=lambda *_:os._exit(0)
 g.execute('offline-remote-p08')
"""
    subprocess.run(
        [sys.executable, "-c", child, str(db), str(Path(__file__).resolve())],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")},
        check=True,
    )
    wire = Wire([envelope("in_progress")])
    from unittest.mock import patch

    with Store(db) as s, patch("urllib.request.build_opener", lambda *_: wire):
        gen = GenerationService(s, OpenAIResponses(CONFIG, SECRET, authorized=True))
        gen.execute("offline-remote-p08", recover=True)
        assert not wire.sent
        gen.query_remote("offline-remote-p08")
        assert [x[0] for x in wire.sent] == ["GET"]
        assert (
            s.one("SELECT COUNT(*) AS n FROM attempts WHERE call_key='responses.submit'")["n"] == 1
        )


def test_interrupted_query_recovers_same_read_attempt_lineage_not_create(tmp_path, monkeypatch):
    s, gen, a, wire = setup(tmp_path, monkeypatch, [envelope()])
    with s:
        gen.execute(a["request_id"])
        original = gen.adapter.__class__.__call__

        def interrupt(self, request):
            raise SystemExit("OFFLINE process interruption during GET")

        monkeypatch.setattr(OpenAIResponses, "__call__", interrupt)
        with pytest.raises(SystemExit):
            gen.query_remote(a["request_id"])
        old = s.one(
            "SELECT * FROM attempts WHERE task_id=? AND call_key LIKE 'responses.query.%'",
            (a["task_id"],),
        )
        assert old["status"] == "in_flight"
        monkeypatch.setattr(OpenAIResponses, "__call__", original)
        payload = json.loads(a["input"])
        text = DevelopmentGenerationAdapter()({"messages": gen.messages(payload)}).output[
            "raw_response"
        ]
        wire.responses += [envelope("completed", text)]
        record = gen.query_remote(a["request_id"])["actions"][0]
        assert record["result"]["generation_status"] == "generated"
        attempts = s.rows(
            "SELECT * FROM attempts WHERE task_id=? AND call_key=? ORDER BY ordinal",
            (a["task_id"], old["call_key"]),
        )
        assert [p["status"] for p in attempts] == ["uncertain", "succeeded"]
        assert (
            attempts[1]["previous_id"] == old["id"]
            and attempts[0]["request"] == attempts[1]["request"]
        )
        assert [x[0] for x in wire.sent] == ["POST", "GET"]


def test_unknown_remote_status_keeps_received_id(tmp_path, monkeypatch):
    s, gen, a, wire = setup(
        tmp_path, monkeypatch, [{"id": "resp_OFFLINE1", "status": "future_status"}]
    )
    with s:
        record = gen.execute(a["request_id"])["actions"][0]
        assert (
            record["remote"]["response_id"] == "resp_OFFLINE1"
            and record["remote"]["status"] == "unknown"
        )
        assert not record["result"]
        gen.execute(a["request_id"], recover=True)
        assert len(wire.sent) == 1


def test_http_error_without_submission_id_remains_uncertain(monkeypatch):
    import io
    import urllib.error

    adapter = OpenAIResponses(CONFIG, SECRET, authorized=True)

    class Opener:
        def open(self, req, **_kwargs):
            raise urllib.error.HTTPError(
                req.full_url, 502, SECRET, {}, io.BytesIO(b'{"error":"gateway"}')
            )

    monkeypatch.setattr(urllib.request, "build_opener", lambda *_: Opener())
    messages = [{"role": "user", "content": "OFFLINE JSON"}]
    with pytest.raises(TransportUncertain) as caught:
        adapter({"messages": messages, "actual_request": adapter.request(messages)})
    assert caught.value.response["http_status"] == 502 and caught.value.usage.cost is None
    assert SECRET not in encode(caught.value.response)


def test_cross_process_completed_response_replay_applies_without_any_http(tmp_path):
    db = tmp_path / "completed-crash.sqlite"
    child = r"""
import os,runpy,sys,urllib.request,json
from co_scientist_next.store import Store
from co_scientist_next.generation import GenerationService
from co_scientist_next.responses_model import OpenAIResponses
h=runpy.run_path(sys.argv[2]);w=h['Wire']([h['envelope']()]);urllib.request.build_opener=lambda *_:w
with Store(sys.argv[1]) as s:
 run,_,request=h['H']['prepared'](s)
 g=GenerationService(s,OpenAIResponses(h['CONFIG'],h['SECRET'],authorized=True))
 a=g.submit(run,'offline-remote-p08',request);g.execute(a['request_id'])
 text=h['DevelopmentGenerationAdapter']()({'messages':g.messages(json.loads(a['input']))}).output['raw_response']
 w.responses.append(h['envelope']('completed',text))
 s.submit_result=lambda *_a,**_kw:os._exit(0)
 g.query_remote(a['request_id'])
"""
    subprocess.run(
        [sys.executable, "-c", child, str(db), str(Path(__file__).resolve())],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")},
        check=True,
    )
    from unittest.mock import patch

    wire = Wire([])
    with Store(db) as s, patch("urllib.request.build_opener", lambda *_: wire):
        gen = GenerationService(s, OpenAIResponses(CONFIG, SECRET, authorized=True))
        record = gen.execute("offline-remote-p08", recover=True)["actions"][0]
        assert record["result"]["generation_status"] == "generated" and not wire.sent
        assert (
            s.one("SELECT COUNT(*) AS n FROM attempts WHERE task_id=?", (record["task_id"],))["n"]
            == 2
        )


def test_terminal_wait_duration_stops_at_observation(tmp_path, monkeypatch):
    from datetime import datetime

    s, gen, a, _wire = setup(tmp_path, monkeypatch, [envelope("incomplete", "{}")])
    with s:
        gen.execute(a["request_id"])
        job = gen.snapshot(a["run_id"])["actions"][0]["remote"]
        expected = (
            datetime.fromisoformat(job["observed_at"]) - datetime.fromisoformat(job["submitted_at"])
        ).total_seconds()
        assert job["elapsed_seconds"] == expected


def test_https_handler_uses_cross_version_context_interface(monkeypatch):
    from co_scientist_next.responses_model import TrackedHandler

    handler = TrackedHandler({})

    def open_connection(factory, request, **kwargs):
        # Python3.12 removes check_hostname from HTTPSConnection; TLS verification
        # comes from its default/explicit context, never disable it for compatibility.
        assert set(kwargs) == {"context"}
        connection = factory("api.openai.com", timeout=600, **kwargs)
        assert connection._context.verify_mode != 0
        assert connection._context.check_hostname
        return "OFFLINE no socket connected"

    monkeypatch.setattr(handler, "do_open", open_connection)
    assert handler.https_open(object()) == "OFFLINE no socket connected"


@pytest.mark.parametrize("http_status", [200, 401])
@pytest.mark.parametrize("framing", ["content-length", "chunked", "connection-close"])
def test_real_http_response_socket_release_keeps_complete_response(
    monkeypatch, framing, http_status
):
    """Real stdlib HTTPResponse/socket ownership, no provider or model key."""
    import http.client
    import socket

    from co_scientist_next.contracts import SubmissionUncertain
    from co_scientist_next.responses_model import TrackedHandler

    value = envelope() if http_status == 200 else {"error": {"type": "OFFLINE_auth_error"}}
    body = json.dumps(value).encode()
    reader, writer = socket.socketpair()
    if framing == "content-length":
        headers = b"Content-Length: " + str(len(body)).encode() + b"\r\n"
        framed = body
    elif framing == "chunked":
        headers = b"Transfer-Encoding: chunked\r\n"
        framed = hex(len(body))[2:].encode() + b"\r\n" + body + b"\r\n0\r\n\r\n"
    else:
        headers, framed = b"", body
    writer.sendall(
        ("HTTP/1.1 " + str(http_status) + " OFFLINE\r\nConnection: close\r\n").encode()
        + headers
        + b"\r\n"
        + framed
    )
    writer.close()
    response = http.client.HTTPResponse(reader)
    response.begin()
    reader.close()  # urllib closes its reference; response.makefile still owns the fd.
    assert reader.fileno() >= 0

    class Opener:
        def open(self, *_args, **_kwargs):
            return response

    def build(*handlers):
        trace = next(h.trace for h in handlers if isinstance(h, TrackedHandler))
        trace["socket"] = reader
        return Opener()

    monkeypatch.setattr(urllib.request, "build_opener", build)
    adapter = OpenAIResponses(CONFIG, SECRET, authorized=True)
    messages = [{"role": "user", "content": "OFFLINE JSON socket ownership fixture"}]
    try:
        if http_status == 200:
            result = adapter({"messages": messages, "actual_request": adapter.request(messages)})
            saved = result.output
            assert result.usage.input_tokens is None
        else:
            with pytest.raises(SubmissionUncertain) as caught:
                adapter({"messages": messages, "actual_request": adapter.request(messages)})
            saved = caught.value.response
            assert caught.value.usage.input_tokens is None
        assert json.loads(saved["raw_response"]) == value
        assert saved["http_status"] == http_status and saved["truncated"] is False
        assert reader.fileno() == -1
    finally:
        response.close()
        reader.close()


def test_closed_socket_does_not_hide_content_length_truncation():
    import http.client
    import socket
    import time

    from co_scientist_next.responses_model import read_response_body

    reader, writer = socket.socketpair()
    writer.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 99\r\nConnection: close\r\n\r\n{}")
    writer.close()
    response = http.client.HTTPResponse(reader)
    response.begin()
    reader.close()
    trace = {"socket": reader, "deadline": time.monotonic() + 5}
    try:
        with pytest.raises(http.client.IncompleteRead):
            read_response_body(response, trace, 5)
    finally:
        response.close()
        reader.close()


def test_bad_descriptor_diagnostic_is_safe_and_stays_uncertain():
    import errno

    from co_scientist_next.reading_model import transport_error

    error = transport_error(OSError(errno.EBADF, SECRET), "response_read")
    assert isinstance(error, TransportUncertain)
    record = error.error_record()
    assert record["diagnostic"] == {
        "category": "connection",
        "phase": "response_read",
        "code": "EBADF",
    }
    assert SECRET not in encode(record)


def test_timeout_on_live_socket_is_not_silently_ignored():
    import errno
    import time

    from co_scientist_next.responses_model import read_response_body

    class LiveSocket:
        def fileno(self):
            return 10

        def settimeout(self, _):
            raise OSError(errno.ECONNRESET, SECRET)

    class UnreadResponse:
        def read1(self, _):
            raise AssertionError("Must not ignore real live socket errors")

    with pytest.raises(OSError) as caught:
        read_response_body(
            UnreadResponse(), {"socket": LiveSocket(), "deadline": time.monotonic() + 5}, 5
        )
    assert caught.value.errno == errno.ECONNRESET
