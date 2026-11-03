"""Mock HTTP only; no credentials read from user settings, no real API calls."""

import base64
import json
import os
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

from co_scientist_next.background import BackgroundService
from co_scientist_next.background_ops import DevelopmentReadingAdapter, parse_output
from co_scientist_next.contracts import KnownCallFailure
from co_scientist_next.reading_model import (
    ENDPOINT,
    OpenAIChat,
    available_usage,
    load_credential,
    model_config,
)
from co_scientist_next.store import Store

HELPERS = runpy.run_path(str(Path(__file__).with_name("test_background.py")))
CONFIG = {
    "provider": "openai",
    "endpoint": ENDPOINT,
    "model": "explicit-offline-test-model",
    "parameters": {"max_completion_tokens": 1000, "response_format": {"type": "json_object"}},
    "max_request_bytes": 180000,
}
FAKE_SECRET = "INVENTED-TEST-" + "CREDENTIAL-NOT-A-REAL-KEY"


@pytest.mark.parametrize(
    "patch",
    [
        {"endpoint": "https://unknown.invalid/api"},
        {"model": ""},
        {"api_key": "do-not-persist"},
        {"parameters": {}},
        {"max_request_bytes": 0},
    ],
)
def test_explicit_configuration_no_defaults(patch):
    with pytest.raises(ValueError):
        model_config({**CONFIG, **patch})


def test_credential_config_is_separate_and_not_implicitly_discovered(monkeypatch, tmp_path):
    monkeypatch.setenv("ONLY_EXPLICIT_TEST_CREDENTIAL", FAKE_SECRET)
    with pytest.raises(ValueError):
        load_credential()
    assert load_credential(env_name="ONLY_EXPLICIT_TEST_CREDENTIAL") == FAKE_SECRET
    adapter = OpenAIChat(CONFIG, None)
    assert adapter.configured is False
    with pytest.raises(ValueError, match="Credential detected"):
        OpenAIChat(CONFIG, FAKE_SECRET).preflight({"messages": [{"content": FAKE_SECRET}]})
    assert FAKE_SECRET not in json.dumps(OpenAIChat(CONFIG, FAKE_SECRET).public_config())


@pytest.mark.parametrize("finish", ["stop", "length", "content_filter"])
def test_actual_http_shape_usage_and_m15_raw_before_parse(tmp_path, monkeypatch, finish):
    import urllib.request

    captured = []
    fixture = DevelopmentReadingAdapter()

    class Response:
        code = 200

        def __init__(self, body):
            self.body = body
            self.headers = {"Content-Type": "application/json", "x-request-id": "TEST-request"}

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def read(self, _):
            return self.body

    class Opener:
        def open(self, req, **_):
            captured.append(req)
            body = json.loads(req.data)
            content = fixture({"operation": "P04", "messages": body["messages"]}).output[
                "raw_response"
            ]
            return Response(
                json.dumps(
                    {
                        "id": "TEST-RESPONSE",
                        "model": "explicit-offline-test-model",
                        "choices": [{"finish_reason": finish, "message": {"content": content}}],
                        "usage": {
                            "prompt_tokens": 123,
                            "completion_tokens": 45,
                            "total_tokens": 168,
                        },
                    }
                ).encode()
            )

    monkeypatch.setattr(urllib.request, "build_opener", lambda *_: Opener())
    with Store(tmp_path / "provider.sqlite") as store:
        run, _, view, _ = HELPERS["setup_flow"](store)
        adapter = OpenAIChat(CONFIG, FAKE_SECRET, authorized=True)
        service = BackgroundService(store, adapter)
        service.submit(run, "real-path-mocked", "P04", {"view_id": view["id"]})
        record = service.execute("real-path-mocked")["actions"][-1]
        assert record["result"]["background_status"] == (
            "saved" if finish == "stop" else "invalid_output"
        )
        a = store.one("SELECT * FROM attempts WHERE task_id=?", (record["task_id"],))
        assert a["status"] == "succeeded" and json.loads(a["usage"])["input_tokens"] == 123
        assert (
            json.loads(a["usage"])["output_tokens"] == 45 and json.loads(a["usage"])["cost"] is None
        )
        assert json.loads(a["response"])["raw_response"]
        assert FAKE_SECRET not in "\n".join(store.db.iterdump())
        actual = json.loads(a["request"])["actual_request"]
        assert actual["body"] == json.loads(captured[0].data)
        assert (
            actual["body"]["stream"] is False
            and actual["body"]["store"] is False
            and actual["body"]["n"] == 1
        )
        assert "Authorization" not in a["request"] and len(captured) == 1
        assert captured[0].get_header("Authorization") == "Bearer " + FAKE_SECRET


@pytest.mark.parametrize("status", [302, 429, 503])
def test_no_hidden_http_redirect_or_retry_and_echoed_secret_redacted(monkeypatch, status):
    import urllib.request

    sends = []

    class Response:
        code = status

        def __init__(self):
            self.headers = {"Content-Type": "application/json", "Authorization": FAKE_SECRET}

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def read(self, _):
            return json.dumps({"error": {"message": "Fixture echoed " + FAKE_SECRET}}).encode()

    class Opener:
        def open(self, req, **_):
            sends.append(req)
            return Response()

    monkeypatch.setattr(urllib.request, "build_opener", lambda *_: Opener())
    adapter = OpenAIChat(CONFIG, FAKE_SECRET, authorized=True)
    messages = [{"role": "user", "content": "JSON fixture"}]
    request = {"messages": messages, "actual_request": adapter.request(messages)}
    with pytest.raises(KnownCallFailure) as caught:
        adapter(request)
    assert len(sends) == 1
    saved = caught.value.response
    assert saved["credential_redactions"] is True and FAKE_SECRET not in json.dumps(saved)
    assert FAKE_SECRET.encode() not in base64.b64decode(saved["body_base64"])
    assert caught.value.usage.cost is None


def test_timeout_is_uncertain_without_credential_exception_text(monkeypatch):
    import urllib.request

    class Opener:
        def open(self, *_, **__):
            raise TimeoutError("Sensitive exception " + FAKE_SECRET)

    monkeypatch.setattr(urllib.request, "build_opener", lambda *_: Opener())
    adapter = OpenAIChat(CONFIG, FAKE_SECRET, authorized=True)
    messages = [{"role": "user", "content": "JSON"}]
    with pytest.raises(RuntimeError) as caught:
        adapter({"messages": messages, "actual_request": adapter.request(messages)})
    assert FAKE_SECRET not in str(caught.value)


def test_real_authorization_and_missing_credential_do_not_fall_back(tmp_path):
    with Store(tmp_path / "unauthorized.sqlite") as store:
        run, _, view, _ = HELPERS["setup_flow"](store)
        for key, status in [
            (None, "model_not_configured"),
            (FAKE_SECRET, "model_call_not_authorized"),
        ]:
            service = BackgroundService(store, OpenAIChat(CONFIG, key, authorized=False))
            ref = "config-" + status
            service.submit(run, ref, "P04", {"view_id": view["id"]})
            a = service.execute(ref)["actions"][-1]
            assert a["result"]["background_status"] == status and not a["attempts"]


def test_unknown_usage_and_explicit_real_trial_flag(tmp_path):
    usage = available_usage('{"usage":{"prompt_tokens":null,"completion_tokens":-1}}')
    assert usage.input_tokens is None and usage.output_tokens is None and usage.cost is None
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "co_scientist_next.background_trial",
            "--db",
            str(tmp_path / "must-not-exist.sqlite"),
            "--run-id",
            "fake",
            "--view-id",
            "fake",
            "--config",
            "missing-config",
        ],
        env={**os.environ, "PYTHONPATH": str(root / "src")},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0 and "No call authorized" in result.stderr
    assert not (tmp_path / "must-not-exist.sqlite").exists()


def test_unselected_quote_access_and_invented_reference_rejected(tmp_path):
    with Store(tmp_path / "parse.sqlite") as store:
        run, service, view, _ = HELPERS["setup_flow"](store)
        payload = service.build_input(run, "P04", {"view_id": view["id"]})
        request = {"operation": "P04", "messages": service.messages("P04", payload)}
        fixture = json.loads(DevelopmentReadingAdapter()(request).output["raw_response"])
        fixture["finding_cards"][0]["supporting_quote"] = "Unseen invented figure text"
        with pytest.raises(ValueError):
            parse_output("P04", json.dumps(fixture), payload)
        fixture = json.loads(DevelopmentReadingAdapter()(request).output["raw_response"])
        fixture["finding_cards"][0]["images_seen"] = True
        parsed = parse_output("P04", json.dumps(fixture), payload)
        assert parsed["finding_cards"][0]["images_seen"] is False


def test_credential_cannot_be_used_as_public_model_name():
    with pytest.raises(ValueError, match="Credential detected"):
        OpenAIChat({**CONFIG, "model": FAKE_SECRET}, FAKE_SECRET, authorized=False)
