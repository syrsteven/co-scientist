import pytest
from pydantic import ValidationError

from co_scientist.events.models import DomainEvent, NewEvent
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


@pytest.mark.parametrize(
    ("event_class", "event_kwargs"),
    [
        (
            DomainEvent,
            {
                "sequence": 1,
                "run_id": "r-1",
                "event_type": "Example",
            },
        ),
        (NewEvent, {"event_type": "Example"}),
    ],
)
def test_event_payload_is_deeply_immutable_and_json_serializable(
    event_class: type[DomainEvent] | type[NewEvent], event_kwargs: dict[str, object]
) -> None:
    event = event_class(
        **event_kwargs,
        payload={"nested": {"items": ["original"]}},
    )

    with pytest.raises(TypeError):
        event.payload["new"] = "value"
    with pytest.raises(TypeError):
        event.payload["nested"]["new"] = "value"
    with pytest.raises(TypeError):
        event.payload["nested"]["items"][0] = "changed"

    assert event.model_dump(mode="json")["payload"] == {
        "nested": {"items": ["original"]}
    }


@pytest.mark.parametrize(
    ("event_class", "event_kwargs", "payload"),
    [
        (
            DomainEvent,
            {"sequence": 1, "run_id": "r-1", "event_type": "Example"},
            {"labels": {"first"}},
        ),
        (
            DomainEvent,
            {"sequence": 1, "run_id": "r-1", "event_type": "Example"},
            {"nested": {"labels": frozenset({"first"})}},
        ),
        (NewEvent, {"event_type": "Example"}, {"labels": {"first"}}),
        (
            NewEvent,
            {"event_type": "Example"},
            {"nested": {"labels": frozenset({"first"})}},
        ),
    ],
)
def test_event_payload_rejects_sets_outside_the_json_domain(
    event_class: type[DomainEvent] | type[NewEvent],
    event_kwargs: dict[str, object],
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError, match="payload values must be JSON-compatible"):
        event_class(**event_kwargs, payload=payload)
