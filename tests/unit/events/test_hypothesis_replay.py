from co_scientist.events.models import DomainEvent
from co_scientist.events.reducers import replay_hypothesis


def test_replay_rebuilds_coverage_without_mutating_content() -> None:
    events = [
        DomainEvent(
            sequence=1,
            run_id="r-1",
            event_type="HypothesisContentCreated",
            payload={"hypothesis_id": "h-1", "content_id": "c-1"},
        ),
        DomainEvent(
            sequence=2,
            run_id="r-1",
            event_type="ReviewCompleted",
            payload={
                "hypothesis_id": "h-1",
                "stage": "initial_review",
                "review_id": "rev-1",
            },
        ),
        DomainEvent(
            sequence=3,
            run_id="r-1",
            event_type="HypothesisTournamentReady",
            payload={"hypothesis_id": "h-1"},
        ),
    ]

    projection = replay_hypothesis("h-1", events)

    assert projection.content_id == "c-1"
    assert projection.review_coverage["initial_review"] == ("rev-1",)
    assert projection.lifecycle_state == "tournament_ready"
