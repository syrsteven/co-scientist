"""Bounded, secret-safe diagnostics for external transport failures."""

from __future__ import annotations

import contextvars
import json
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import PurePath
from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from co_scientist.domain.task import TaskLeaseFence

FailureDiagnosticCode = Literal[
    "connect_error",
    "timeout_error",
    "value_error",
    "exception_group",
    "os_error",
    "unclassified_exception",
]
SafeDiagnosticMessage = Literal[
    "network connection failed",
    "network request timed out",
    "local value validation failed",
    "multiple nested failures",
    "operating system operation failed",
    "operation failed; message omitted",
]
TransportMilestone = Literal[
    "request_constructed",
    "request_serialized",
    "bounded_transport_reserved",
    "inner_transport_entered",
    "response_headers_received",
    "response_body_complete",
    "raw_persisted",
    "usage_parsed",
]

DIAGNOSTIC_SCHEMA_ID = "ExternalCallFailureDiagnosticV1"
DIAGNOSTIC_SCHEMA_VERSION = 1
TRANSPORT_MILESTONE_VERSION = 1
MAX_TREE_DEPTH = 6
MAX_TREE_NODES = 24
MAX_DIAGNOSTIC_BYTES = 8192
MAX_CHILDREN_PER_NODE = 8


class ExceptionDiagnosticNodeV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    exception_class: str = Field(max_length=96)
    safe_code: FailureDiagnosticCode
    safe_message: SafeDiagnosticMessage
    source_module: str | None = Field(default=None, max_length=120)
    source_file: str | None = Field(default=None, max_length=80)
    source_function: str | None = Field(default=None, max_length=96)
    source_line: int | None = None
    children: tuple[ExceptionDiagnosticNodeV1, ...] = ()


class ExternalCallFailureDiagnosticV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_id: Literal["ExternalCallFailureDiagnosticV1"] = "ExternalCallFailureDiagnosticV1"
    schema_version: Literal[1] = 1
    root: ExceptionDiagnosticNodeV1
    truncated: bool = False


@dataclass(frozen=True)
class ExternalCallObservationContext:
    run_id: str
    task_id: str
    external_call_id: str
    reservation_id: str
    fence: TaskLeaseFence
    record_milestone: Callable[..., None]


_active_observation: contextvars.ContextVar[ExternalCallObservationContext | None] = (
    contextvars.ContextVar("co_scientist_external_call_observation", default=None)
)


@contextmanager
def observe_external_call(context: ExternalCallObservationContext) -> Iterator[None]:
    token = _active_observation.set(context)
    try:
        yield
    finally:
        _active_observation.reset(token)


def current_external_call_observation() -> ExternalCallObservationContext | None:
    return _active_observation.get()


def record_transport_milestone(
    milestone: TransportMilestone,
    *,
    source: Literal["bounded_transport", "external_call_runner"] = "bounded_transport",
) -> None:
    """Best-effort append; observation I/O must not mask provider outcomes."""

    context = _active_observation.get()
    if context is None:
        return
    try:
        context.record_milestone(
            context.external_call_id,
            milestone,
            source=source,
            reservation_id=context.reservation_id,
            fence=context.fence,
        )
    except Exception:  # noqa: BLE001 - observation I/O cannot mask provider semantics
        # The normal provider/raw lifecycle remains authoritative. An observation
        # write failure must not turn a real provider response into a false call
        # failure or change its terminal state.
        return


_SAFE_EXCEPTION_RULES: tuple[
    tuple[str, FailureDiagnosticCode, SafeDiagnosticMessage], ...
] = (
    ("ConnectError", "connect_error", "network connection failed"),
    ("TimeoutException", "timeout_error", "network request timed out"),
    ("Timeout", "timeout_error", "network request timed out"),
    ("ValueError", "value_error", "local value validation failed"),
    ("OSError", "os_error", "operating system operation failed"),
)
_SAFE_IDENTIFIER = re.compile(r"[^A-Za-z0-9_.-]")
_CREDENTIAL_SHAPED = re.compile(
    r"(?i)(?:sk|rk|ghp|gho|xox[baprs]?|AIza)[-_A-Za-z0-9]{8,}"
)


class _SourceOrigin(TypedDict):
    source_module: str | None
    source_file: str | None
    source_function: str | None
    source_line: int | None


@dataclass
class _BuildState:
    nodes: int = 0
    truncated: bool = False


def _safe_identifier(value: str, limit: int, default: str = "unknown") -> str:
    value = _CREDENTIAL_SHAPED.sub("redacted", value)
    cleaned = _SAFE_IDENTIFIER.sub("_", value)[:limit]
    return cleaned or default


def _safe_exception_fields(
    error: BaseException,
) -> tuple[str, FailureDiagnosticCode, SafeDiagnosticMessage]:
    cls = type(error)
    name = _safe_identifier(cls.__name__, 96, "Exception")
    if isinstance(error, BaseExceptionGroup):
        return name, "exception_group", "multiple nested failures"
    for suffix, code, message in _SAFE_EXCEPTION_RULES:
        if any(base.__name__ == suffix for base in cls.__mro__):
            return name, code, message
    return name, "unclassified_exception", "operation failed; message omitted"


def _origin(error: BaseException) -> _SourceOrigin:
    tb = error.__traceback__
    if tb is None:
        return {
            "source_module": None,
            "source_file": None,
            "source_function": None,
            "source_line": None,
        }
    while tb.tb_next is not None:
        tb = tb.tb_next
    frame = tb.tb_frame
    basename = PurePath(frame.f_code.co_filename).name
    module = _safe_identifier(str(frame.f_globals.get("__name__", "unknown")), 120)
    return {
        "source_module": module,
        "source_file": _safe_identifier(basename, 80),
        "source_function": _safe_identifier(frame.f_code.co_name, 96),
        "source_line": tb.tb_lineno if tb.tb_lineno >= 0 else None,
    }


def failure_diagnostic_for_exception(error: BaseException) -> ExternalCallFailureDiagnosticV1:
    """Create a recursive diagnostic without serializing exception text/repr."""

    state = _BuildState()

    def build(item: BaseException, depth: int) -> ExceptionDiagnosticNodeV1:
        state.nodes += 1
        exception_class, safe_code, safe_message = _safe_exception_fields(item)
        children: tuple[ExceptionDiagnosticNodeV1, ...] = ()
        if isinstance(item, BaseExceptionGroup) and item.exceptions:
            if depth >= MAX_TREE_DEPTH or state.nodes >= MAX_TREE_NODES:
                state.truncated = True
            else:
                selected = item.exceptions[:MAX_CHILDREN_PER_NODE]
                if len(selected) != len(item.exceptions):
                    state.truncated = True
                built: list[ExceptionDiagnosticNodeV1] = []
                for child in selected:
                    if state.nodes >= MAX_TREE_NODES:
                        state.truncated = True
                        break
                    built.append(build(child, depth + 1))
                children = tuple(built)
        node = ExceptionDiagnosticNodeV1(
            exception_class=exception_class,
            safe_code=safe_code,
            safe_message=safe_message,
            **_origin(item),
            children=children,
        )
        return node

    root = build(error, 0)
    result = ExternalCallFailureDiagnosticV1(root=root, truncated=state.truncated)
    encoded = json.dumps(result.model_dump(mode="json"), separators=(",", ":")).encode()
    if len(encoded) > MAX_DIAGNOSTIC_BYTES:
        exception_class, safe_code, safe_message = _safe_exception_fields(error)
        result = ExternalCallFailureDiagnosticV1(
            root=ExceptionDiagnosticNodeV1(
                exception_class=exception_class,
                safe_code=safe_code,
                safe_message=safe_message,
                **_origin(error),
            ),
            truncated=True,
        )
    return result


def bounded_diagnostic_json(diagnostic: ExternalCallFailureDiagnosticV1) -> str:
    encoded = json.dumps(
        diagnostic.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    if len(encoded.encode("utf-8")) > MAX_DIAGNOSTIC_BYTES:
        raise ValueError("failure diagnostic exceeds frozen size limit")
    return encoded
