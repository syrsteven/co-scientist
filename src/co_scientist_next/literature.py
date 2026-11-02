"""Shared narrow acquisition contract. M01/M04 own strategies, M05 appraisal.

A returned empty page is not necessarily an exhausted search. Access levels
record obtained material, never the level hoped for or scientific evidence quality.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from ._validation import require_refs


class ExecutionStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INCOMPLETE = "incomplete"


class AccessLevel(StrEnum):
    NONE = "none"
    METADATA = "metadata"
    ABSTRACT = "abstract"
    FULL_TEXT = "full_text"
    SUPPLEMENTARY = "supplementary"


def check_execution(status, error):
    if not isinstance(status, ExecutionStatus):
        raise TypeError("Explicit execution status required")
    if status == ExecutionStatus.SUCCEEDED:
        if error is not None:
            raise ValueError("A successful execution cannot carry a technical error")
    else:
        require_refs(error)


@dataclass(frozen=True)
class SourceRecord:
    source_ref: str
    citation: str
    title: str | None = None

    def __post_init__(self):
        require_refs(self.source_ref, self.citation)
        if self.title is not None:
            require_refs(self.title)


@dataclass(frozen=True)
class SearchRequest:
    source: str
    query: str
    scope: str
    cursor: str | None = None

    def __post_init__(self):
        require_refs(self.source, self.query, self.scope)
        if self.cursor is not None:
            require_refs(self.cursor)


@dataclass(frozen=True)
class SearchResult:
    request: SearchRequest
    status: ExecutionStatus
    executed_at: str
    items: tuple[SourceRecord, ...] = ()
    reported_total: int | None = None
    next_cursor: str | None = None
    scope_complete: bool = False
    error: str | None = None

    def __post_init__(self):
        if not isinstance(self.request, SearchRequest):
            raise TypeError("Actual search request required")
        check_execution(self.status, self.error)
        require_refs(self.executed_at)
        if not isinstance(self.items, tuple) or any(
            not isinstance(i, SourceRecord) for i in self.items
        ):
            raise ValueError("Search items require immutable source records")
        if self.reported_total is not None and (
            isinstance(self.reported_total, bool)
            or not isinstance(self.reported_total, int)
            or self.reported_total < len(self.items)
        ):
            raise ValueError("Reported total cannot be smaller than returned items")
        if not isinstance(self.scope_complete, bool):
            raise TypeError("Explicit search scope completion required")
        if self.next_cursor is not None:
            require_refs(self.next_cursor)
        if self.scope_complete and (
            self.status != ExecutionStatus.SUCCEEDED or self.next_cursor is not None
        ):
            raise ValueError("Incomplete/failed/paginated search cannot claim scope completion")
        if self.status == ExecutionStatus.FAILED and (
            self.items or self.reported_total is not None
        ):
            raise ValueError(
                "Failed search is not a zero-result search; use incomplete for partial data"
            )
        if (
            self.scope_complete
            and self.request.cursor is None
            and not self.items
            and self.reported_total not in (None, 0)
        ):
            raise ValueError("An empty completed search conflicts with the reported total")

    @property
    def searched_empty_within_scope(self) -> bool:
        return (
            self.status == ExecutionStatus.SUCCEEDED
            and self.scope_complete
            and self.request.cursor is None
            and not self.items
        )


@dataclass(frozen=True)
class FetchRequest:
    source_ref: str
    desired_access: AccessLevel = AccessLevel.FULL_TEXT

    def __post_init__(self):
        require_refs(self.source_ref)
        if (
            not isinstance(self.desired_access, AccessLevel)
            or self.desired_access == AccessLevel.NONE
        ):
            raise ValueError("Requested material access level required")


@dataclass(frozen=True)
class FetchResult:
    request: FetchRequest
    status: ExecutionStatus
    executed_at: str
    access: AccessLevel
    source: SourceRecord | None = None
    text: str | None = None
    limitation: str | None = None
    error: str | None = None

    def __post_init__(self):
        if not isinstance(self.request, FetchRequest) or not isinstance(self.access, AccessLevel):
            raise TypeError("Actual fetch request and access level required")
        require_refs(self.executed_at)
        check_execution(self.status, self.error)
        if self.source is not None and (
            not isinstance(self.source, SourceRecord)
            or self.source.source_ref != self.request.source_ref
        ):
            raise ValueError("Fetched source does not match request")
        if self.access == AccessLevel.NONE:
            if (
                self.source is not None
                or self.text is not None
                or self.status == ExecutionStatus.SUCCEEDED
            ):
                raise ValueError("No obtained material cannot be a successful fetch")
        else:
            if self.source is None or self.status == ExecutionStatus.FAILED:
                raise ValueError("Obtained material requires a source and nonfailed execution")
            if self.access == AccessLevel.METADATA:
                if self.text is not None:
                    raise ValueError("Metadata-only access must not claim obtained text")
            else:
                require_refs(self.text)
            if self.access != self.request.desired_access:
                require_refs(self.limitation)
        if self.limitation is not None:
            require_refs(self.limitation)


class LiteraturePort(Protocol):
    """Acquisition only. Production adapters must use M15 for every actual send.

    Returned request/status/time/scope/access data are actual execution facts;
    neither search success nor full-text access supplies a scientific appraisal.
    """

    def search(self, request: SearchRequest) -> SearchResult: ...

    def fetch(self, request: FetchRequest) -> FetchResult: ...
