"""Pure reducers for rebuilding projections from domain events."""

from pydantic import BaseModel, Field

from co_scientist.domain.hypothesis import HypothesisProjection
from co_scientist.events.models import DomainEvent


def reduce_hypothesis(
    projection: HypothesisProjection | None, event: DomainEvent, hypothesis_id: str
) -> HypothesisProjection | None:
    """Apply one event to a hypothesis projection without mutating either input."""
    if event.event_type == "HypothesisContentCreated":
        if event.payload["hypothesis_id"] == hypothesis_id:
            return HypothesisProjection(
                hypothesis_id=hypothesis_id,
                content_id=event.payload["content_id"],
            )
    elif event.event_type == "ReviewCompleted" and projection is not None:
        if event.payload["hypothesis_id"] == hypothesis_id:
            coverage = dict(projection.review_coverage)
            stage = event.payload["stage"]
            coverage[stage] = (*coverage.get(stage, ()), event.payload["review_id"])
            return projection.model_copy(update={"review_coverage": coverage})
    elif (
        event.event_type == "HypothesisTournamentReady"
        and projection is not None
        and event.payload["hypothesis_id"] == hypothesis_id
    ):
        return projection.model_copy(update={"lifecycle_state": "tournament_ready"})
    return projection


def replay_hypothesis(
    hypothesis_id: str, events: list[DomainEvent]
) -> HypothesisProjection:
    """Deterministically rebuild one hypothesis projection from an event stream."""
    projection: HypothesisProjection | None = None
    for event in events:
        projection = reduce_hypothesis(projection, event, hypothesis_id)
    if projection is None:
        raise KeyError(hypothesis_id)
    return projection


class TournamentProjection(BaseModel):
    """Tournament ratings and contracts, separated by frozen epoch."""

    ratings: dict[str, dict[str, float]] = Field(default_factory=dict)
    epoch_plan_versions: dict[str, int] = Field(default_factory=dict)


def replay_tournament(events: list[DomainEvent]) -> TournamentProjection:
    """Deterministically rebuild ratings while keeping epochs isolated."""
    projection = TournamentProjection()
    for event in events:
        if event.event_type == "TournamentEpochOpened":
            versions = dict(projection.epoch_plan_versions)
            versions[event.payload["epoch_id"]] = event.payload["research_plan_version"]
            projection = projection.model_copy(update={"epoch_plan_versions": versions})
        elif event.event_type in {"TournamentEntryCreated", "RatingUpdated"}:
            ratings = {
                epoch_id: dict(values)
                for epoch_id, values in projection.ratings.items()
            }
            epoch_id = event.payload["epoch_id"]
            ratings.setdefault(epoch_id, {})[event.payload["hypothesis_id"]] = event.payload[
                "rating"
            ]
            projection = projection.model_copy(update={"ratings": ratings})
    return projection
