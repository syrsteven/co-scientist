"""One explicit OpenAI Chat Completions send; no SDK, retries or G3 imports."""

import base64
import errno
import hashlib
import http.client
import json
import math
import os
import socket
import ssl
import urllib.error
import urllib.request
from pathlib import Path

from .contracts import CallResponse, KnownCallFailure, TransportUncertain, Usage
from .europe_pmc import NoRedirect
from .store import encode, now

ENDPOINT = "https://api.openai.com/v1/chat/completions"


def transport_error(exc, phase):
    """Classify by known types/numeric codes; never format provider error text."""
    if isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, BaseException):
        exc = exc.reason
    if isinstance(exc, TimeoutError):
        category, code = "timeout", "ETIMEDOUT"
    elif isinstance(exc, ssl.SSLCertVerificationError):
        category, code = "tls", "CERTIFICATE_VERIFY_FAILED"
    elif isinstance(exc, ssl.SSLError):
        category, code = "tls", "TLS_ERROR"
    elif isinstance(exc, socket.gaierror):
        category = "dns"
        code = {socket.EAI_AGAIN: "EAI_AGAIN", socket.EAI_NONAME: "EAI_NONAME"}.get(
            exc.errno, "DNS_ERROR"
        )
    elif isinstance(exc, http.client.HTTPException):
        category = "http_protocol"
        code = next(
            (
                name
                for kind, name in (
                    (http.client.RemoteDisconnected, "REMOTE_DISCONNECTED"),
                    (http.client.IncompleteRead, "INCOMPLETE_READ"),
                    (http.client.BadStatusLine, "BAD_STATUS_LINE"),
                )
                if isinstance(exc, kind)
            ),
            "HTTP_PROTOCOL_ERROR",
        )
    elif isinstance(exc, OSError) and exc.errno in {
        errno.ECONNRESET,
        errno.ECONNABORTED,
        errno.ECONNREFUSED,
        errno.EPIPE,
        errno.ENETUNREACH,
        errno.EHOSTUNREACH,
    }:
        category, code = "connection", errno.errorcode[exc.errno]
    else:
        category, code = "transport", "TRANSPORT_ERROR"
    return TransportUncertain(category, phase, code)


def model_config(value):
    if not isinstance(value, dict) or set(value) - {"timeout_seconds"} != {
        "provider",
        "endpoint",
        "model",
        "parameters",
        "max_request_bytes",
    }:
        raise ValueError(
            "Explicit provider, endpoint, model, parameters and max_request_bytes required; no secret fields"
        )
    if value["provider"] != "openai" or value["endpoint"] != ENDPOINT:
        raise ValueError("This slice supports only the explicit official OpenAI chat endpoint")
    if not isinstance(value["model"], str) or not value["model"].strip():
        raise ValueError("Explicit model required; no default or substitution")
    params = value["parameters"]
    if not isinstance(params, dict) or set(params) - {
        "max_completion_tokens",
        "temperature",
        "reasoning_effort",
        "response_format",
    }:
        raise ValueError("Unsupported or missing explicit generation parameters")
    maximum = params.get("max_completion_tokens")
    if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum < 1:
        raise ValueError("Explicit positive max_completion_tokens required")
    if params.get("response_format") != {"type": "json_object"}:
        raise ValueError(
            "Explicit JSON response_format required; domain output is separately validated"
        )
    if "temperature" in params and (
        isinstance(params["temperature"], bool)
        or not isinstance(params["temperature"], (int, float))
        or not math.isfinite(params["temperature"])
        or not 0 <= params["temperature"] <= 2
    ):
        raise ValueError("Invalid temperature")
    if "reasoning_effort" in params and params["reasoning_effort"] not in (
        "none",
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    ):
        raise ValueError("Unsupported explicit reasoning_effort")
    cap = value["max_request_bytes"]
    if isinstance(cap, bool) or not isinstance(cap, int) or not 1000 <= cap <= 2_000_000:
        raise ValueError(
            "Explicit request byte limit required (1000..2000000); not a token estimate"
        )
    timeout = value.get("timeout_seconds", 90)
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(timeout)
        or not 1 <= timeout <= 3600
    ):
        raise ValueError("timeout_seconds must be finite and between 1 and 3600")
    return json.loads(encode(value))


def load_credential(*, env_name=None, credential_file=None):
    if bool(env_name) == bool(credential_file):
        raise ValueError("Select exactly one separate credential environment or file")
    if env_name:
        secret = os.environ.get(env_name)
    else:
        data = json.loads(Path(credential_file).read_text())
        secret = data.get("api_key")
    if not isinstance(secret, str) or not secret.strip():
        raise ValueError("Credential is not configured")
    return secret.strip()


def available_usage(raw):
    try:
        usage = json.loads(raw).get("usage") or {}

        def count(key):
            v = usage.get(key)
            return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None

        return Usage(input_tokens=count("prompt_tokens"), output_tokens=count("completion_tokens"))
    except (ValueError, TypeError, AttributeError):
        return Usage()


class OpenAIChat:
    execution_mode = "real_model"

    def __init__(self, config, api_key, *, authorized=False):
        self.config = model_config(config)
        if api_key is not None and (not isinstance(api_key, str) or not api_key):
            raise ValueError("Separate credential required")
        self.configured = api_key is not None
        if api_key and api_key in encode(self.config):
            raise ValueError("Credential detected in public model configuration")
        self._api_key = api_key
        self.authorized = authorized
        self.target = "openai/chat/" + self.config["model"]

    def public_config(self):
        return {
            **self.config,
            "execution_mode": self.execution_mode,
            "credential_configured": self.configured,
        }

    def request(self, messages):
        return {
            "endpoint": self.config["endpoint"],
            **(
                {"timeout_seconds": self.config["timeout_seconds"]}
                if "timeout_seconds" in self.config
                else {}
            ),
            "body": {
                "model": self.config["model"],
                "messages": messages,
                **self.config["parameters"],
                "n": 1,
                "stream": False,
                "store": False,
            },
        }

    def preflight(self, request):
        if self._api_key and self._api_key in encode(request):
            raise ValueError(
                "Credential detected in proposed model input; nothing persisted or sent"
            )

    def __call__(self, request):
        if not self.configured:
            raise KnownCallFailure("Model credential is not configured")
        if not self.authorized:
            raise KnownCallFailure("Real model calls have not been explicitly authorized")
        self.preflight(request)
        actual = request["actual_request"]
        if actual != self.request(request["messages"]):
            raise KnownCallFailure("Actual request/config mismatch")
        payload = encode(actual["body"]).encode()
        headers = {"Authorization": "Bearer " + self._api_key, "Content-Type": "application/json"}
        req = urllib.request.Request(
            actual["endpoint"], data=payload, headers=headers, method="POST"
        )
        phase = "request_open"
        try:
            try:
                response = urllib.request.build_opener(NoRedirect()).open(
                    req, timeout=actual.get("timeout_seconds", 90)
                )
            except urllib.error.HTTPError as exc:
                response = exc
            with response:
                phase = "response_read"
                raw = response.read(4_000_001)
                phase = "response_metadata"
                truncated = len(raw) > 4_000_000
                text = raw[:4_000_000].decode("utf8", errors="replace")
                redacted = self._api_key in text
                text = text.replace(self._api_key, "[CREDENTIAL REDACTED]")
                retained = text.encode() if redacted else raw[:4_000_000]
                saved = {
                    "body_base64": base64.b64encode(retained).decode(),
                    "body_sha256": hashlib.sha256(retained).hexdigest(),
                    "raw_response": text,
                    "http_status": response.code,
                    "received_at": now(),
                    "truncated": truncated,
                    "credential_redactions": redacted,
                    "response_headers": {
                        k: v.replace(self._api_key, "[CREDENTIAL REDACTED]")
                        for k, v in response.headers.items()
                        if k.lower() in ("content-type", "x-request-id")
                    },
                }
                phase = "response_close"
        except Exception as exc:  # noqa: BLE001 -- only an allowlisted projection crosses M15
            # Never leak urllib/provider exceptions or credential-bearing objects to M15.
            raise transport_error(exc, phase) from None
        # Preserve every provider usage detail, including reasoning/cache counters,
        # independently of the narrow shared Usage summary and domain parsing.
        try:
            envelope = json.loads(text)
            saved["provider_usage"] = envelope.get("usage")
            choices = envelope.get("choices") or []
            saved["finish_reason"] = choices[0].get("finish_reason") if choices else None
        except (ValueError, TypeError, AttributeError, KeyError):
            saved["provider_usage"] = None
            saved["finish_reason"] = None
        usage = available_usage(text)
        if not 200 <= saved["http_status"] < 300:
            raise KnownCallFailure(
                f"Model HTTP {saved['http_status']}", response=saved, usage=usage
            )
        return CallResponse(saved, usage)

    @staticmethod
    def text(output):
        if output.get("truncated"):
            raise ValueError("Provider response truncated at technical byte limit")
        data = json.loads(output["raw_response"])
        choice = data["choices"][0]
        if choice["finish_reason"] != "stop" or choice["message"].get("refusal"):
            raise ValueError(
                f"Incomplete/refused model response (finish_reason={choice['finish_reason']}); no scientific decision applied"
            )
        content = choice["message"]["content"]
        if not isinstance(content, str):
            raise TypeError("Text JSON response required")
        if not content.strip():
            raise ValueError("Empty model response; no scientific reading applied")
        return content
