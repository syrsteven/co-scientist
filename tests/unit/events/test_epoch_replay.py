from co_scientist.events.models import DomainEvent
from co_scientist.events.reducers import replay_tournament


def test_new_epoch_restarts_rating_at_1200() -> None:
    projection = replay_tournament(
        [
            DomainEvent(
                sequence=1,
                run_id="r-1",
                event_type="TournamentEpochOpened",
                payload={"epoch_id": "e-1", "research_plan_version": 1},
            ),
            DomainEvent(
                sequence=2,
                run_id="r-1",
                event_type="TournamentEntryCreated",
                payload={"epoch_id": "e-1", "hypothesis_id": "h-1", "rating": 1200.0},
            ),
            DomainEvent(
                sequence=3,
                run_id="r-1",
                event_type="RatingUpdated",
                payload={"epoch_id": "e-1", "hypothesis_id": "h-1", "rating": 1280.0},
            ),
            DomainEvent(
                sequence=4,
                run_id="r-1",
                event_type="TournamentEpochClosed",
                payload={"epoch_id": "e-1"},
            ),
            DomainEvent(
                sequence=5,
                run_id="r-1",
                event_type="TournamentEpochOpened",
                payload={"epoch_id": "e-2", "research_plan_version": 2},
            ),
            DomainEvent(
                sequence=6,
                run_id="r-1",
                event_type="TournamentEntryCreated",
                payload={"epoch_id": "e-2", "hypothesis_id": "h-1", "rating": 1200.0},
            ),
        ]
    )

    assert projection.ratings["e-1"]["h-1"] == 1280.0
    assert projection.ratings["e-2"]["h-1"] == 1200.0
