import pytest
from pydantic import ValidationError

from co_scientist.events.models import DomainEvent, NewEvent
from co_scientist.events.reducers import replay_hypothesis


def test_replay_rebuilds_coverage_without_mutating_content() -> None:
    content_hash = "sha256:" + "a" * 64
    events = [
        DomainEvent(
            sequence=0,
            run_id="r-1",
            event_type="TournamentEpochOpened",
            payload={
                "epoch_id": "epoch-1",
                "research_plan_version": 1,
                "rating_policy_version": "elo-32-v1",
            },
        ),
        DomainEvent(
            sequence=1,
            run_id="r-1",
            event_type="HypothesisContentCreated",
            schema_version=2,
            payload={
                "hypothesis_id": "h-1",
                "content_id": "c-1",
                "content_hash": content_hash,
                "research_plan_version": 1,
                "parent_content_ids": [],
                "supersedes_content_id": None,
            },
        ),
        DomainEvent(
            sequence=2,
            run_id="r-1",
            event_type="ReviewCompleted",
            schema_version=2,
            payload={
                "hypothesis_id": "h-1",
                "content_hash": content_hash,
                "research_plan_version": 1,
                "stage": "initial_review",
                "review_id": "rev-1",
                "recommendation": "pass",
                "safety_status": "passed",
                "critical_flaws": [],
                "evidence_ids": [],
            },
        ),
        DomainEvent(
            sequence=3,
            run_id="r-1",
            event_type="HypothesisTournamentReady",
            schema_version=2,
            payload={
                "hypothesis_id": "h-1",
                "content_hash": content_hash,
                "research_plan_version": 1,
                "epoch_id": "epoch-1",
                "rating_policy_version": "elo-32-v1",
            },
        ),
    ]

    projection = replay_hypothesis("h-1", events)

    assert projection.current_content_id == "c-1"
    assert projection.review_coverage_by_content[content_hash]["initial_review"] == (
        "rev-1",
    )
    assert projection.lifecycle_state == "tournament_ready"


# Mutation caught: freezing only model attributes while leaving projection maps
# mutable in place.
def test_projection_keyed_structures_are_deeply_immutable() -> None:
    content_hash = "sha256:" + "a" * 64
    projection = replay_hypothesis(
        "h-1",
        [
            DomainEvent(
                sequence=0,
                run_id="r-1",
                event_type="TournamentEpochOpened",
                payload={
                    "epoch_id": "epoch-1",
                    "research_plan_version": 1,
                    "rating_policy_version": "elo-32-v1",
                },
            ),
            DomainEvent(
                sequence=1,
                run_id="r-1",
                event_type="HypothesisContentCreated",
                schema_version=2,
                payload={
                    "hypothesis_id": "h-1",
                    "content_id": "c-1",
                    "content_hash": content_hash,
                    "research_plan_version": 1,
                    "parent_content_ids": [],
                    "supersedes_content_id": None,
                },
            ),
            DomainEvent(
                sequence=2,
                run_id="r-1",
                event_type="ReviewCompleted",
                schema_version=2,
                payload={
                    "hypothesis_id": "h-1",
                    "content_hash": content_hash,
                    "research_plan_version": 1,
                    "stage": "initial_review",
                    "review_id": "rev-1",
                    "recommendation": "pass",
                    "safety_status": "passed",
                },
            ),
            DomainEvent(
                sequence=3,
                run_id="r-1",
                event_type="HypothesisTournamentReady",
                schema_version=2,
                payload={
                    "hypothesis_id": "h-1",
                    "content_hash": content_hash,
                    "research_plan_version": 1,
                    "epoch_id": "epoch-1",
                    "rating_policy_version": "elo-32-v1",
                },
            ),
            DomainEvent(
                sequence=4,
                run_id="r-1",
                event_type="TournamentEntryCreated",
                payload={
                    "hypothesis_id": "h-1",
                    "content_hash": content_hash,
                    "epoch_id": "epoch-1",
                    "rating": 1200.0,
                    "matches_played": 0,
                },
            ),
            DomainEvent(
                sequence=5,
                run_id="r-1",
                event_type="InitialRatingAssigned",
                payload={
                    "hypothesis_id": "h-1",
                    "epoch_id": "epoch-1",
                    "rating": 1200.0,
                    "rating_policy_version": "elo-32-v1",
                },
            ),
        ],
    )

    with pytest.raises(TypeError):
        projection.review_coverage_by_content["new"] = {}  # type: ignore[index]
    with pytest.raises(TypeError):
        projection.review_coverage_by_content[content_hash]["full_review"] = ()  # type: ignore[index]
    with pytest.raises(TypeError):
        projection.tournament_entries_by_epoch["new"] = projection.tournament_entries_by_epoch[  # type: ignore[index]
            "epoch-1"
        ]
    with pytest.raises(TypeError):
        projection.current_ratings_by_epoch["epoch-1"] = 9999.0  # type: ignore[index]

    dumped = projection.model_dump(mode="json")
    assert dumped["review_coverage_by_content"][content_hash] == {
        "initial_review": ["rev-1"]
    }
    assert dumped["current_ratings_by_epoch"] == {"epoch-1": 1200.0}


# Mutation caught: treating run-level scientific control events as unclassified
# and therefore ignoring unknown versions during canonical replay.
def test_replay_rejects_unsupported_run_science_version() -> None:
    content_hash = "sha256:" + "a" * 64
    events = [
        DomainEvent(
            sequence=1,
            run_id="r-1",
            event_type="HypothesisContentCreated",
            schema_version=2,
            payload={
                "hypothesis_id": "h-1",
                "content_id": "c-1",
                "content_hash": content_hash,
                "research_plan_version": 1,
            },
        ),
        DomainEvent(
            sequence=2,
            run_id="r-1",
            event_type="TournamentEpochOpened",
            schema_version=2,
            payload={"epoch_id": "epoch-1", "research_plan_version": 1},
        ),
    ]

    with pytest.raises(ValueError, match="TournamentEpochOpened v2"):
        replay_hypothesis("h-1", events)


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
