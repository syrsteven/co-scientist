"""Small execution contracts. Scientific modules own their payload schemas."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

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
