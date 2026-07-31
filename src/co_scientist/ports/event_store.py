"""Port for append-only, optimistic-concurrency event persistence."""

from collections.abc import Sequence
from typing import Protocol

from co_scientist.events.models import DomainEvent, NewEvent


class ConcurrencyConflict(RuntimeError):
    """Raised when a stream has advanced beyond the expected sequence."""


class EventStore(Protocol):
    """Append and load one run's ordered event stream."""

    def load(self, run_id: str, after_sequence: int = 0) -> list[DomainEvent]: ...

    def append(
        self,
        run_id: str,
        expected_sequence: int,
        events: Sequence[NewEvent],
    ) -> list[DomainEvent]: ...
