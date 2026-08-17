import json

import pytest
from pydantic import ValidationError

from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork
from co_scientist.events.models import DomainEvent, NewEvent
from co_scientist.events.reducers import replay_hypothesis
from co_scientist.export.run_export import SqliteRunReadModel

CONTENT_V1 = "sha256:" + "a" * 64
CONTENT_V2 = "sha256:" + "b" * 64
OTHER_CONTENT = "sha256:" + "c" * 64
CONTENT_V3 = "sha256:" + "d" * 64


def _event(
    sequence: int,
    event_type: str,
    payload: dict[str, object],
    *,
    schema_version: int,
) -> DomainEvent:
    return DomainEvent(
        sequence=sequence,
        run_id="run-1",
        event_type=event_type,
        schema_version=schema_version,
        payload=payload,
    )


def _content(
    *, content_id: str, content_hash: str, plan_version: int, supersedes: str | None = None
) -> dict[str, object]:
    return {
        "hypothesis_id": "h-1",
        "content_id": content_id,
        "content_hash": content_hash,
        "research_plan_version": plan_version,
        "title": f"Title {content_id}",
        "claim": f"Claim {content_id}",
        "mechanism_chain": ["cause", "effect"],
        "assumptions": [],
        "predictions": ["prediction"],
        "falsifiers": ["falsifier"],
        "generation_strategy": "causal contrast",
        "parent_content_ids": [],
        "supersedes_content_id": supersedes,
    }


def _review(
    review_id: str,
    *,
    content_hash: str,
    plan_version: int,
    stage: str,
    safety_status: str,
) -> dict[str, object]:
    return {
        "review_id": review_id,
        "hypothesis_id": "h-1",
        "content_hash": content_hash,
        "research_plan_version": plan_version,
        "stage": stage,
        "recommendation": "pass",
        "safety_status": safety_status,
        "safety_passed": safety_status == "passed" if stage == "initial_review" else False,
        "dimension_scores": {},
        "critical_flaws": [],
        "evidence_ids": [],
    }


def _complete_events() -> list[DomainEvent]:
    return [
        _event(
            0,
            "TournamentEpochOpened",
            {
                "epoch_id": "epoch-1",
                "research_plan_version": 2,
                "rating_policy_version": "elo-32-v1",
            },
            schema_version=1,
        ),
        _event(
            1,
            "HypothesisContentCreated",
            _content(content_id="content-v1", content_hash=CONTENT_V1, plan_version=1),
            schema_version=2,
        ),
        _event(
            2,
            "ReviewCompleted",
            _review(
                "review-v1",
                content_hash=CONTENT_V1,
                plan_version=1,
                stage="initial_review",
                safety_status="passed",
            ),
            schema_version=2,
        ),
        _event(
            3,
            "NoveltyAssessmentRecorded",
            {
                "assessment_id": "novelty-v1",
                "hypothesis_id": "h-1",
                "content_hash": CONTENT_V1,
                "research_plan_version": 1,
                "verdict": "novel",
                "closest_prior_work_ids": [],
                "evidence_ids": [],
            },
            schema_version=1,
        ),
        _event(
            4,
            "HypothesisContentCreated",
            _content(
                content_id="content-v2",
                content_hash=CONTENT_V2,
                plan_version=2,
                supersedes="content-v1",
            ),
            schema_version=2,
        ),
        _event(
            5,
            "ReviewCompleted",
            _review(
                "stale-review",
                content_hash=CONTENT_V1,
                plan_version=1,
                stage="full_review",
                safety_status="not_assessed",
            ),
            schema_version=2,
        ),
        _event(
            6,
            "ReviewCompleted",
            _review(
                "current-initial",
                content_hash=CONTENT_V2,
                plan_version=2,
                stage="initial_review",
                safety_status="passed",
            ),
            schema_version=2,
        ),
        _event(
            7,
            "ReviewCompleted",
            _review(
                "current-full",
                content_hash=CONTENT_V2,
                plan_version=2,
                stage="full_review",
                safety_status="not_assessed",
            ),
            schema_version=2,
        ),
        _event(
            8,
            "NoveltyAssessmentRecorded",
            {
                "assessment_id": "novelty-v2",
                "hypothesis_id": "h-1",
                "content_hash": CONTENT_V2,
                "research_plan_version": 2,
                "verdict": "partially_novel",
                "closest_prior_work_ids": ["paper-1"],
                "evidence_ids": ["source-1"],
            },
            schema_version=1,
        ),
        _event(
            9,
            "ProximityAssessed",
            {
                "edge_id": "edge-1-2",
                "research_plan_version": 2,
                "left_id": "h-1",
                "left_content_hash": CONTENT_V2,
                "right_id": "h-2",
                "right_content_hash": OTHER_CONTENT,
                "similarity": 3,
                "mechanism_overlap": ["shared step"],
                "duplicate_likelihood": 0.2,
                "cluster_suggestion": "cluster-causal",
                "rationale": "related but distinct",
                "access_issues": ["paywalled supplement"],
            },
            schema_version=2,
        ),
        _event(
            10,
            "HypothesisTournamentReady",
            {
                "run_id": "run-1",
                "hypothesis_id": "h-1",
                "content_id": "content-v2",
                "content_hash": CONTENT_V2,
                "research_plan_version": 2,
                "epoch_id": "epoch-1",
                "rating_policy_version": "elo-32-v1",
            },
            schema_version=2,
        ),
        _event(
            11,
            "TournamentEntryCreated",
            {
                "epoch_id": "epoch-1",
                "hypothesis_id": "h-1",
                "content_hash": CONTENT_V2,
                "rating": 1200.0,
                "matches_played": 0,
            },
            schema_version=1,
        ),
        _event(
            12,
            "InitialRatingAssigned",
            {
                "epoch_id": "epoch-1",
                "hypothesis_id": "h-1",
                "rating": 1200.0,
                "rating_policy_version": "elo-32-v1",
            },
            schema_version=1,
        ),
        _event(
            13,
            "HypothesisTournamentReady",
            {
                "run_id": "run-1",
                "hypothesis_id": "h-2",
                "content_id": "content-other",
                "content_hash": OTHER_CONTENT,
                "research_plan_version": 2,
                "epoch_id": "epoch-1",
                "rating_policy_version": "elo-32-v1",
            },
            schema_version=2,
        ),
        _event(
            14,
            "TournamentEntryCreated",
            {
                "epoch_id": "epoch-1",
                "hypothesis_id": "h-2",
                "content_hash": OTHER_CONTENT,
                "rating": 1200.0,
                "matches_played": 0,
            },
            schema_version=1,
        ),
        _event(
            15,
            "InitialRatingAssigned",
            {
                "epoch_id": "epoch-1",
                "hypothesis_id": "h-2",
                "rating": 1200.0,
                "rating_policy_version": "elo-32-v1",
            },
            schema_version=1,
        ),
        _event(
            16,
            "MatchEvaluated",
            {
                "match_id": "match-inconclusive",
                "epoch_id": "epoch-1",
                "left_id": "h-1",
                "left_content_hash": CONTENT_V2,
                "right_id": "h-2",
                "right_content_hash": OTHER_CONTENT,
                "research_plan_version": 2,
                "decision": "inconclusive",
                "winner_id": None,
            },
            schema_version=2,
        ),
        _event(
            17,
            "MatchEvaluated",
            {
                "match_id": "match-decisive",
                "epoch_id": "epoch-1",
                "left_id": "h-1",
                "left_content_hash": CONTENT_V2,
                "right_id": "h-2",
                "right_content_hash": OTHER_CONTENT,
                "research_plan_version": 2,
                "decision": "decisive",
                "winner_id": "h-1",
            },
            schema_version=2,
        ),
        _event(
            18,
            "RatingUpdated",
            {
                "match_id": "match-decisive",
                "epoch_id": "epoch-1",
                "hypothesis_id": "h-1",
                "before_rating": 1200.0,
                "rating": 1216.0,
                "rating_policy_version": "elo-32-v1",
            },
            schema_version=1,
        ),
        _event(
            19,
            "RatingUpdated",
            {
                "match_id": "match-decisive",
                "epoch_id": "epoch-1",
                "hypothesis_id": "h-2",
                "before_rating": 1200.0,
                "rating": 1184.0,
                "rating_policy_version": "elo-32-v1",
            },
            schema_version=1,
        ),
        _event(
            20,
            "MetaReviewCompleted",
            {
                "research_plan_version": 2,
                "source_content_hashes": {"h-1": CONTENT_V2, "h-2": OTHER_CONTENT},
                "system_feedback": ["preserve mechanism diversity"],
                "overview": "coverage complete",
                "coverage_gaps": [],
                "safety_direction_check": "clear",
            },
            schema_version=2,
        ),
    ]


# Mutations caught: flattening revision evidence, ignoring tournament/match history, or
# computing current evidence from stale content.
def test_complete_projection_preserves_history_and_applies_only_current_revision() -> None:
    projection = replay_hypothesis("h-1", _complete_events())

    assert projection.current_content_id == "content-v2"
    assert projection.current_content_hash == CONTENT_V2
    assert [revision.content_id for revision in projection.content_revisions] == [
        "content-v1",
        "content-v2",
    ]
    assert projection.lifecycle_state == "tournament_active"
    assert projection.current_safety_status == "passed"
    assert projection.review_coverage_by_content[CONTENT_V1] == {
        "initial_review": ("review-v1",),
        "full_review": ("stale-review",),
    }
    assert projection.review_coverage_by_content[CONTENT_V2] == {
        "initial_review": ("current-initial",),
        "full_review": ("current-full",),
    }
    assert [item.applies_to_current_revision for item in projection.review_history] == [
        False,
        False,
        True,
        True,
    ]
    assert [item.applies_to_current_revision for item in projection.novelty_history] == [
        False,
        True,
    ]
    assert projection.current_novelty_assessment_ids == ("novelty-v2",)
    assert projection.cluster_ids == ("cluster-causal",)
    assert projection.access_issues == ("paywalled supplement",)
    assert projection.tournament_entries_by_epoch["epoch-1"].content_hash == CONTENT_V2
    assert projection.tournament_entries_by_epoch["epoch-1"].matches_played == 2
    assert projection.tournament_readiness_history[0].epoch_id == "epoch-1"
    assert projection.tournament_readiness_history[0].rating_policy_version == "elo-32-v1"
    assert len(projection.tournament_entry_history) == 1
    assert [rating.rating for rating in projection.rating_history] == [1200.0, 1216.0]
    assert projection.current_ratings_by_epoch == {"epoch-1": 1216.0}
    assert [match.decision for match in projection.match_participation] == [
        "inconclusive",
        "decisive",
    ]
    assert projection.created_sequence == 1
    assert projection.updated_sequence == 20
    with pytest.raises(ValidationError):
        projection.current_content_hash = CONTENT_V1  # type: ignore[misc]


# Mutation caught: silently skipping a known scientific event from an unknown schema.
def test_projection_rejects_unsupported_relevant_event_version() -> None:
    events = _complete_events()
    review_index = next(
        index
        for index, event in enumerate(events)
        if event.payload.get("review_id") == "current-full"
    )
    events[review_index] = events[review_index].model_copy(update={"schema_version": 1})

    with pytest.raises(ValueError, match="unsupported scientific event version"):
        replay_hypothesis("h-1", events)


# Mutation caught: recording match participation against an epoch the hypothesis never entered.
def test_projection_rejects_match_outside_hypothesis_entry_epoch() -> None:
    events = _complete_events()
    match_index = next(
        index
        for index, event in enumerate(events)
        if event.payload.get("match_id") == "match-inconclusive"
    )
    events[match_index] = events[match_index].model_copy(
        update={"payload": {**events[match_index].payload, "epoch_id": "epoch-other"}}
    )

    with pytest.raises(ValueError, match="match requires a tournament entry"):
        replay_hypothesis("h-1", events)


# Mutation caught: carrying epoch-local entry/rating current views across a new
# content and plan revision.
def test_new_content_revision_retires_current_entries_and_ratings_but_keeps_history() -> None:
    events = [
        *_complete_events(),
        _event(
            21,
            "HypothesisContentCreated",
            _content(
                content_id="content-v3",
                content_hash=CONTENT_V3,
                plan_version=3,
                supersedes="content-v2",
            ),
            schema_version=2,
        ),
    ]

    projection = replay_hypothesis("h-1", events)

    assert projection.current_content_hash == CONTENT_V3
    assert projection.lifecycle_state == "created"
    assert projection.tournament_entries_by_epoch == {}
    assert projection.current_ratings_by_epoch == {}
    assert len(projection.tournament_entry_history) == 1
    assert projection.tournament_entry_history[0].content_hash == CONTENT_V2
    assert not projection.tournament_entry_history[0].applies_to_current_revision
    assert [rating.applies_to_current_revision for rating in projection.rating_history] == [
        False,
        False,
    ]


# Mutation caught: admitting an entry without readiness for the same opened epoch.
def test_entry_requires_matching_readiness_and_open_epoch() -> None:
    events = _complete_events()
    entry_index = next(
        index
        for index, event in enumerate(events)
        if event.event_type == "TournamentEntryCreated"
        and event.payload.get("hypothesis_id") == "h-1"
    )
    events[entry_index] = events[entry_index].model_copy(
        update={"payload": {**events[entry_index].payload, "epoch_id": "epoch-other"}}
    )

    with pytest.raises(ValueError, match="readiness.*opened epoch"):
        replay_hypothesis("h-1", events[: entry_index + 1])


# Mutation caught: validating only the projected participant of a match.
def test_match_requires_both_content_bound_epoch_entries() -> None:
    events = [
        event
        for event in _complete_events()
        if not (
            event.event_type in {"TournamentEntryCreated", "InitialRatingAssigned"}
            and event.payload.get("hypothesis_id") == "h-2"
        )
    ]

    with pytest.raises(ValueError, match="both participants"):
        replay_hypothesis("h-1", events)


# Mutation caught: allowing one MatchEvaluated identity to be replayed twice.
def test_projection_rejects_duplicate_match_identity() -> None:
    events = _complete_events()
    decisive = next(
        event
        for event in events
        if event.payload.get("match_id") == "match-decisive"
        and event.event_type == "MatchEvaluated"
    )
    rating_index = next(
        index for index, event in enumerate(events) if event.event_type == "RatingUpdated"
    )
    events.insert(rating_index, decisive.model_copy(update={"sequence": 18}))

    with pytest.raises(ValueError, match="duplicate match_id"):
        replay_hypothesis("h-1", events)


# Mutation caught: accepting a rating policy unrelated to the entry's opened epoch.
def test_projection_rejects_rating_policy_mismatch() -> None:
    events = _complete_events()
    rating_index = next(
        index
        for index, event in enumerate(events)
        if event.event_type == "RatingUpdated"
        and event.payload.get("hypothesis_id") == "h-1"
    )
    events[rating_index] = events[rating_index].model_copy(
        update={
            "payload": {
                **events[rating_index].payload,
                "rating_policy_version": "foreign-policy",
            }
        }
    )

    with pytest.raises(ValueError, match="rating policy"):
        replay_hypothesis("h-1", events)


# Mutation caught: seeding a derived match count from caller-provided entry data.
def test_projection_rejects_nonzero_entry_matches_played_seed() -> None:
    events = _complete_events()
    entry_index = next(
        index
        for index, event in enumerate(events)
        if event.event_type == "TournamentEntryCreated"
        and event.payload.get("hypothesis_id") == "h-1"
    )
    events[entry_index] = events[entry_index].model_copy(
        update={
            "payload": {
                **events[entry_index].payload,
                "matches_played": 37,
            }
        }
    )

    with pytest.raises(ValueError, match="matches_played must start at zero"):
        replay_hypothesis("h-1", events)


# Mutation caught: maintaining a second SQL-side hypothesis projection algorithm.
def test_sqlite_export_projection_is_canonical_replay_byte_for_byte(tmp_path) -> None:
    uow = SqliteUnitOfWork(f"sqlite:///{tmp_path / 'projection.db'}")
    uow.create_schema()
    uow.create_started_run(
        "run-1",
        manifest={"profile": "projection"},
        event=NewEvent(event_type="RunStarted", payload={}),
        idempotency_key="start:run-1:0",
    )
    source_events = _complete_events()
    uow.commit_domain_batch(
        run_id="run-1",
        expected_sequence=1,
        events=tuple(
            NewEvent(
                event_type=event.event_type,
                schema_version=event.schema_version,
                payload=event.payload,
            )
            for event in source_events
        ),
        idempotency_key="complete-projection",
    )
    events = uow.load("run-1")
    canonical = replay_hypothesis("h-1", events).model_dump(mode="json")
    exported = SqliteRunReadModel(uow).hypothesis_projections("run-1")[0]

    compact = lambda value: json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    assert compact(exported) == compact(canonical)
