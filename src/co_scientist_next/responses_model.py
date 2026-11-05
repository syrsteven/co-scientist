"""Explicit non-streaming Responses background transport. No retries or credentials in exports."""

import base64
import hashlib
import http.client
import json
import math
import re
import socket
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from .contracts import CallResponse, KnownCallFailure, SubmissionUncertain, Usage
from .europe_pmc import NoRedirect
from .reading_model import transport_error
from .store import encode, now

ENDPOINT = "https://api.openai.com/v1/responses"
STATES = {"queued", "in_progress", "completed", "failed", "incomplete", "cancelled"}
PENDING = {"queued", "in_progress", "unknown"}
RETENTION = "explicit-store-true-provider-retention-acknowledged-v1"


def responses_config(value):
    required = {
        "provider",
        "endpoint",
        "model",
        "parameters",
        "max_request_bytes",
        "timeout_seconds",
        "total_wait_seconds",
        "store",
        "retention_ack",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("Explicit Responses configuration and retention acknowledgement required")
    if (
        value["provider"] != "openai"
        or value["endpoint"] != ENDPOINT
        or value["model"] != "gpt-6.1-sol"
        or value["store"] is not True
        or value["retention_ack"] != RETENTION
    ):
        raise ValueError(
            "This narrow profile requires Sol, official Responses and acknowledged store=true"
        )
    if value["parameters"] != {
        "reasoning_effort": "high",
        "max_completion_tokens": 32768,
        "response_format": {"type": "json_object"},
    }:
        raise ValueError("Explicit high/32768/JSON only; temperature is not supported")
    for key in ("timeout_seconds", "total_wait_seconds"):
        v = value[key]
        if type(v) not in (int, float) or not math.isfinite(v) or not 1 <= v <= 3600:
            raise ValueError("Explicit finite socket timeout and per-HTTP total deadline required")
    if (
        type(value["max_request_bytes"]) is not int
        or not 1000 <= value["max_request_bytes"] <= 2_000_000
    ):
        raise ValueError("Explicit capacity limit required")
    return json.loads(encode(value))


def proxy_facts():
    """Current effective urllib configuration only; not proof of a historical route."""
    proxies = urllib.request.getproxies()
    entries = {}
    for kind in ("http", "https", "all"):
        value = proxies.get(kind)
        if value:
            try:
                parsed = urlsplit(value if "://" in value else "http://" + value)
                entries[kind] = {
                    "scheme": parsed.scheme,
                    "host": parsed.hostname,
                    "port": parsed.port,
                    "credentials_present": bool(parsed.username or parsed.password),
                }
            except ValueError:
                entries[kind] = {"invalid_proxy_configuration": True}
    return {
        "effective_proxies": entries,
        "openai_proxy_bypass": urllib.request.proxy_bypass("api.openai.com"),
        "route_confirmed": False,
        "source": "current urllib environment/OS discovery",
    }


class TrackedHTTPS(http.client.HTTPSConnection):
    def __init__(self, *args, trace, **kwargs):
        self.trace = trace
        super().__init__(*args, **kwargs)
        trace["connection"] = self

    def connect(self):
        self.trace["phase"] = "connect"  # Includes proxy CONNECT and TLS, if applicable.
        self.trace["connecting"] = True
        super().connect()
        self.trace["connecting"] = False
        self.trace["socket"] = self.sock
        self.trace["connected_seconds"] = time.monotonic() - self.trace["start"]
        if time.monotonic() >= self.trace["deadline"]:
            self.close()
            raise TimeoutError()

    def send(self, data):
        self.trace["phase"] = "connect" if self.trace.get("connecting") else "request_send"
        super().send(data)
        self.trace["phase"] = "connect" if self.trace.get("connecting") else "request_send"

    def getresponse(self):
        self.trace["phase"] = "waiting_headers"
        result = super().getresponse()
        self.trace["headers_seconds"] = time.monotonic() - self.trace["start"]
        return result


class TrackedHandler(urllib.request.HTTPSHandler):
    def __init__(self, trace):
        super().__init__()
        self.trace = trace

    def https_open(self, req):
        return self.do_open(
            lambda *a, **kw: TrackedHTTPS(*a, trace=self.trace, **kw),
            req,
            context=self._context,
        )


def read_response_body(response, trace, socket_timeout):
    """Keep stdlib EOF semantics; response.makefile owns the socket after urlopen.

    Content-Length completion may close the last socket reference inside read1.
    The next iteration must read EOF without setting a timeout on fd=-1.
    A socket marked _closed may still back a live makefile: use fileno, not _closed.
    """
    chunks, length = [], 0
    while True:
        if time.monotonic() >= trace["deadline"]:
            raise TimeoutError()
        sock = trace.get("socket")
        if sock is not None and sock.fileno() >= 0:
            sock.settimeout(
                min(
                    socket_timeout,
                    max(0.001, trace["deadline"] - time.monotonic()),
                )
            )
        chunk = response.read1(min(65536, 16_000_001 - length))
        if time.monotonic() >= trace["deadline"]:
            raise TimeoutError()
        if not chunk:
            if getattr(response, "length", None) not in (None, 0):
                raise http.client.IncompleteRead(b"")
            break
        chunks.append(chunk)
        length += len(chunk)
        if length > 16_000_000:
            break
    return b"".join(chunks), length > 16_000_000


class OpenAIResponses:
    execution_mode = "real_model"
    background_responses = True

    def __init__(self, config, api_key=None, *, authorized=False):
        self.config = responses_config(config)
        if api_key is not None and (not isinstance(api_key, str) or not api_key):
            raise ValueError("Separate credential required")
        self._api_key, self.configured, self.authorized = api_key, api_key is not None, authorized
        self.target = "openai/responses/" + self.config["model"]
        self.preflight(self.config)

    def public_config(self):
        return {
            **self.config,
            "execution_mode": self.execution_mode,
            "api_mode": "responses_background_v1",
            "credential_configured": self.configured,
        }

    def preflight(self, value):
        if self._api_key and self._api_key in encode(value):
            raise ValueError("Credential detected in public input; nothing sent")

    def request(self, messages):
        return {
            "endpoint": ENDPOINT,
            "method": "POST",
            "timeout_seconds": self.config["timeout_seconds"],
            "total_wait_seconds": self.config["total_wait_seconds"],
            "body": {
                "model": self.config["model"],
                "input": messages,
                "reasoning": {"effort": "high"},
                "max_output_tokens": 32768,
                "text": {"format": {"type": "json_object"}},
                "background": True,
                "store": True,
                "stream": False,
                "truncation": "disabled",
            },
        }

    def query_request(self, response_id):
        if not isinstance(response_id, str) or not re.fullmatch(
            r"resp_[A-Za-z0-9_-]{1,200}", response_id
        ):
            raise ValueError("Invalid response ID")
        return {
            "endpoint": ENDPOINT + "/" + response_id,
            "method": "GET",
            "timeout_seconds": self.config["timeout_seconds"],
            "total_wait_seconds": self.config["total_wait_seconds"],
        }

    def __call__(self, request):
        if not self.configured or not self.authorized:
            raise KnownCallFailure("Responses credential/explicit authorization unavailable")
        actual = request["actual_request"]
        expected = (
            self.query_request(request["response_id"])
            if "response_id" in request
            else self.request(request["messages"])
        )
        if actual != expected:
            raise KnownCallFailure("Responses actual request/config mismatch")
        self.preflight(request)
        start = time.monotonic()
        trace = {
            "phase": "request_open",
            "start": start,
            "deadline": start + actual["total_wait_seconds"],
        }

        def expire():
            # DNS resolution itself is not interruptible by stdlib; checked on return.
            sock = trace.get("socket")
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

        timer = threading.Timer(actual["total_wait_seconds"], expire)
        timer.daemon = True
        timer.start()
        try:
            req = urllib.request.Request(
                actual["endpoint"],
                data=encode(actual["body"]).encode() if "body" in actual else None,
                headers={
                    "Authorization": "Bearer " + self._api_key,
                    "Content-Type": "application/json",
                },
                method=actual["method"],
            )
            try:
                response = urllib.request.build_opener(NoRedirect(), TrackedHandler(trace)).open(
                    req, timeout=min(actual["timeout_seconds"], actual["total_wait_seconds"])
                )
            except urllib.error.HTTPError as exc:
                response = exc
            with response:
                trace["phase"] = "response_read"
                raw, truncated = read_response_body(response, trace, actual["timeout_seconds"])
                text = raw.decode("utf8", errors="replace")
                redacted = self._api_key in text
                text = text.replace(self._api_key, "[CREDENTIAL REDACTED]")
                retained = text.encode() if redacted else raw
                saved = {
                    "raw_response": text,
                    "body_base64": base64.b64encode(retained).decode(),
                    "body_sha256": hashlib.sha256(retained).hexdigest(),
                    "http_status": response.code,
                    "received_at": now(),
                    "truncated": truncated,
                    "credential_redactions": redacted,
                    "transport": {
                        "elapsed_seconds": time.monotonic() - start,
                        **{
                            k: trace[k]
                            for k in ("connected_seconds", "headers_seconds")
                            if k in trace
                        },
                        "phase": "response_read",
                    },
                }
        except Exception as exc:  # noqa: BLE001 -- only allowlisted diagnostics cross M15
            safe = transport_error(exc, trace["phase"])
            safe.elapsed_seconds = time.monotonic() - start
            if actual["method"] == "GET":
                # A failed read of an existing ID cannot ambiguously create a generation.
                raise KnownCallFailure(
                    "Remote status query failed; saved ID unchanged",
                    response={"query_error": safe.error_record()},
                ) from None
            raise safe from None
        finally:
            timer.cancel()
        try:
            data = json.loads(text)
            saved["provider_usage"] = data.get("usage")
        except (ValueError, AttributeError):
            data, saved["provider_usage"] = {}, None
        u = saved["provider_usage"] or {}

        def count(key):
            v = u.get(key) if isinstance(u, dict) else None
            return v if type(v) is int and v >= 0 else None

        usage = Usage(input_tokens=count("input_tokens"), output_tokens=count("output_tokens"))
        if not 200 <= saved["http_status"] < 300:
            if actual["method"] == "POST":
                raise SubmissionUncertain(saved, usage)
            raise KnownCallFailure("Responses HTTP error", response=saved, usage=usage)
        try:
            envelope = self.envelope(saved)
            if "response_id" in request and envelope["id"] != request["response_id"]:
                raise ValueError("Response identity mismatch")
        except (ValueError, TypeError, KeyError):
            if actual["method"] == "GET":
                raise KnownCallFailure(
                    "Invalid query response; saved ID unchanged", response=saved, usage=usage
                ) from None
            raise SubmissionUncertain(saved, usage) from None
        return CallResponse(saved, usage)

    @staticmethod
    def envelope(output):
        data = json.loads(output["raw_response"])
        if (
            output.get("truncated")
            or output.get("credential_redactions")
            or not isinstance(data, dict)
        ):
            raise ValueError("Unusable remote envelope")
        rid = data.get("id")
        if not isinstance(rid, str) or not re.fullmatch(r"resp_[A-Za-z0-9_-]{1,200}", rid):
            raise ValueError("Missing remote response ID")
        if data.get("status") not in STATES:
            # A usable ID must survive even a new/missing status. Never create again.
            return {**data, "status": "unknown"}
        return data

    @classmethod
    def text(cls, output):
        data = cls.envelope(output)
        if data["status"] != "completed" or data.get("error") or data.get("incomplete_details"):
            raise ValueError("Remote response is not complete")
        texts = []
        for item in data.get("output", []):
            if item.get("type") not in ("message", "reasoning"):
                raise ValueError("Unsupported remote output item")
            if item.get("type") == "message":
                if item.get("status") != "completed":
                    raise ValueError("Incomplete message")
                for part in item.get("content", []):
                    if part.get("type") != "output_text":
                        raise ValueError("Refusal or unsupported message content")
                    texts.append(part["text"])
        text = "".join(texts)
        if not text.strip():
            raise ValueError("Empty output")
        return text
