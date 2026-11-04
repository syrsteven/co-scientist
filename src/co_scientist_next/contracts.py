"""Small execution contracts. Scientific modules own their payload schemas."""

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, ClassVar, Protocol

JSON = dict[str, Any]


@dataclass(frozen=True)
class Usage:
    # None means unavailable, including after a request with no response.
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost: float | None = None
    tool_units: int | None = None


@dataclass(frozen=True)
class CallResponse:
    output: JSON
    usage: Usage = field(default_factory=Usage)


class KnownCallFailure(Exception):
    """Adapter confirms a failed response; safe technical retry is allowed.

    Adapters must not use this for a lost response or an ambiguous side effect.
    Error text and optional response are persisted, never printed by the CLI.
    """

    def __init__(self, message: str, *, usage: Usage | None = None, response: JSON | None = None):
        super().__init__(message)
        self.usage = usage if usage is not None else Usage()
        self.response = response


class UncertainCall(RuntimeError):
    """Provider may have executed; requires explicit recovery decision."""


class TransportUncertain(RuntimeError):
    """Only fixed, allowlisted metadata may cross a credential-bearing transport."""

    MESSAGE = "Model send outcome uncertain; credential details withheld"
    ALLOWED: ClassVar[dict[str, set[str]]] = {
        "category": {"timeout", "connection", "tls", "dns", "http_protocol", "transport"},
        "phase": {
            "request_open",
            "connect",
            "request_send",
            "waiting_headers",
            "response_read",
            "response_metadata",
            "response_close",
            "unknown",
        },
        "code": {
            "ETIMEDOUT",
            "ECONNRESET",
            "ECONNABORTED",
            "ECONNREFUSED",
            "EPIPE",
            "ENETUNREACH",
            "EHOSTUNREACH",
            "EAI_AGAIN",
            "EAI_NONAME",
            "DNS_ERROR",
            "CERTIFICATE_VERIFY_FAILED",
            "TLS_ERROR",
            "REMOTE_DISCONNECTED",
            "INCOMPLETE_READ",
            "BAD_STATUS_LINE",
            "HTTP_PROTOCOL_ERROR",
            "TRANSPORT_ERROR",
        },
    }

    def __init__(self, category, phase, code, *, elapsed_seconds=None):
        super().__init__(self.MESSAGE)
        self.diagnostic = {"category": category, "phase": phase, "code": code}
        self.elapsed_seconds = elapsed_seconds

    def error_record(self):
        defaults = {"category": "transport", "phase": "unknown", "code": "TRANSPORT_ERROR"}
        diagnostic = {}
        for key, allowed in self.ALLOWED.items():
            value = self.diagnostic.get(key)
            diagnostic[key] = value if type(value) is str and value in allowed else defaults[key]
        record = {"type": "TransportUncertain", "message": self.MESSAGE, "diagnostic": diagnostic}
        elapsed = self.elapsed_seconds
        if type(elapsed) in (int, float) and math.isfinite(elapsed) and elapsed >= 0:
            record["elapsed_seconds"] = elapsed
        return record


class SubmissionUncertain(TransportUncertain):
    """A received submission response cannot identify the remote job; retain it."""

    def __init__(self, response, usage):
        super().__init__("http_protocol", "response_metadata", "HTTP_PROTOCOL_ERROR")
        self.response, self.usage = response, usage


@dataclass(frozen=True)
class ModuleResult:
    output: JSON


@dataclass(frozen=True)
class TaskInput:
    task_id: str
    run_id: str
    brief_revision_id: str
    brief: JSON
    policy_ref: str
    goal_context_ref: str | None  # Only M01 may prepare scientific GoalContext.
    previous_result: JSON | None


class Calls(Protocol):
    def execute(
        self,
        key: str,
        target: str,
        request: JSON,
        invoke: Callable[[JSON], CallResponse],
        *,
        max_attempts: int = 1,
    ) -> CallResponse: ...


class Module(Protocol):
    def __call__(self, inputs: TaskInput, calls: Calls) -> ModuleResult: ...
