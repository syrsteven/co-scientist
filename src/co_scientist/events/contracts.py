"""Closed schema-version matrix for scientific domain events."""

from collections.abc import Mapping
from types import MappingProxyType

from co_scientist.events.models import DomainEvent

EVENT_SCHEMA_VERSIONS: Mapping[str, frozenset[int]] = MappingProxyType(
    {
        "HypothesisContentCreated": frozenset({2}),
        "ReviewCompleted": frozenset({2}),
        "NoveltyAssessmentRecorded": frozenset({1}),
        "ProximityAssessed": frozenset({2}),
        "MetaReviewCompleted": frozenset({2}),
        "HypothesisTournamentReady": frozenset({2}),
        "TournamentEntryCreated": frozenset({1}),
        "InitialRatingAssigned": frozenset({1}),
        "MatchEvaluated": frozenset({2}),
        "RatingUpdated": frozenset({1}),
        "ResearchPlanAccepted": frozenset({1}),
        "TournamentEpochOpened": frozenset({1}),
        "TournamentEpochClosed": frozenset({1}),
        "RunForkRequired": frozenset({1}),
    }
)


def assert_supported_event_version(event: DomainEvent) -> None:
    """Fail closed when a known scientific event uses an unknown schema."""

    supported = EVENT_SCHEMA_VERSIONS.get(event.event_type)
    if supported is not None and event.schema_version not in supported:
        raise ValueError(
            "unsupported scientific event version: "
            f"{event.event_type} v{event.schema_version}"
        )
