from collections.abc import Callable

import pytest
from pydantic import ValidationError

from co_scientist.domain.admission import (
    AdmissionEvidenceSnapshot,
    AdmissionPolicy,
    reduce_admission_evidence,
)
from co_scientist.domain.review import ReviewPolicy, ReviewStage
from co_scientist.events.models import DomainEvent

CONTENT_HASH = "sha256:" + "a" * 64
OTHER_CONTENT_HASH = "sha256:" + "b" * 64


def _event(
    sequence: int,
    event_type: str,
    payload: dict[str, object],
    *,
    schema_version: int = 1,
) -> DomainEvent:
    return DomainEvent(
        sequence=sequence,
        run_id="run-1",
        event_type=event_type,
        schema_version=schema_version,
        payload=payload,
    )


def _policy(*, version: str = "admission-v1") -> AdmissionPolicy:
    return AdmissionPolicy(
        version=version,
        review_policy=ReviewPolicy(
            profile_id="core-preview",
            required_before_admission=(ReviewStage.FULL,),
        ),
        literature_novelty_required=True,
        duplicate_likelihood_threshold=0.5,
    )


def _complete_events() -> list[DomainEvent]:
    return [
        _event(
            1,
            "TournamentEpochOpened",
            {
                "epoch_id": "epoch-1",
                "research_plan_version": 2,
                "evaluation_rules_hash": "sha256:rules",
                "ranking_prompt_hash": "sha256:prompt",
                "judge_profile_hash": "sha256:judge",
                "rating_policy_version": "elo-32-v1",
                "admission_policy_version": "admission-v1",
            },
        ),
        _event(
            2,
            "HypothesisContentCreated",
            {
                "hypothesis_id": "h-1",
                "content_id": "content-2",
                "content_hash": CONTENT_HASH,
                "research_plan_version": 2,
                "generation_strategy": "causal contrast",
            },
            schema_version=2,
        ),
        _event(
            3,
            "ReviewCompleted",
            {
                "review_id": "review-initial",
                "hypothesis_id": "h-1",
                "content_hash": CONTENT_HASH,
                "research_plan_version": 2,
                "stage": "initial_review",
                "recommendation": "pass",
                "safety_status": "passed",
                "critical_flaws": [],
            },
            schema_version=2,
        ),
        _event(
            4,
            "ReviewCompleted",
            {
                "review_id": "review-full",
                "hypothesis_id": "h-1",
                "content_hash": CONTENT_HASH,
                "research_plan_version": 2,
                "stage": "full_review",
                "recommendation": "pass",
                "safety_status": "not_assessed",
                "critical_flaws": [],
            },
            schema_version=2,
        ),
        _event(
            5,
            "NoveltyAssessmentRecorded",
            {
                "assessment_id": "novelty-1",
                "hypothesis_id": "h-1",
                "content_hash": CONTENT_HASH,
                "research_plan_version": 2,
                "verdict": "partially_novel",
                "closest_prior_work_ids": ["paper-1"],
            },
        ),
        _event(
            6,
            "ProximityAssessed",
            {
                "edge_id": "edge-1-2",
                "research_plan_version": 2,
                "left_id": "h-1",
                "left_content_hash": CONTENT_HASH,
                "right_id": "h-2",
                "right_content_hash": OTHER_CONTENT_HASH,
                "similarity": 2,
                "duplicate_likelihood": 0.49,
                "rationale": "Distinct mechanisms.",
            },
            schema_version=2,
        ),
    ]


def _reduce(
    events: list[DomainEvent],
    *,
    hypothesis_id: str = "h-1",
    policy: AdmissionPolicy | None = None,
) -> AdmissionEvidenceSnapshot:
    return reduce_admission_evidence(
        run_id="run-1",
        hypothesis_id=hypothesis_id,
        events=events,
        policy=policy or _policy(),
    )


# Mutation caught: omitting one current evidence sequence or retaining mutable events.
def test_complete_evidence_returns_exact_immutable_traceable_snapshot() -> None:
    snapshot = _reduce(_complete_events())

    assert snapshot == AdmissionEvidenceSnapshot(
        run_id="run-1",
        hypothesis_id="h-1",
        content_id="content-2",
        content_hash=CONTENT_HASH,
        research_plan_version=2,
        admission_policy_version="admission-v1",
        required_review_stages=(ReviewStage.INITIAL, ReviewStage.FULL),
        safety_status="passed",
        novelty_assessment_id="novelty-1",
        duplicate_detected=False,
        epoch_id="epoch-1",
        rating_policy_version="elo-32-v1",
        missing_requirements=(),
        conflicting_evidence=(),
        source_event_sequences=(1, 2, 3, 4, 5, 6),
        review_ids=("review-initial", "review-full"),
        proximity_edge_ids=("edge-1-2",),
        content_event_sequence=2,
        novelty_event_sequence=5,
        proximity_event_sequences=(6,),
        epoch_event_sequence=1,
    )
    assert "events" not in snapshot.model_dump()
    with pytest.raises(ValidationError):
        snapshot.content_hash = OTHER_CONTENT_HASH  # type: ignore[misc]


# Mutation caught: treating independent agreeing assessment IDs as verdict conflict.
def test_multiple_agreeing_novelty_assessments_use_latest_provenance() -> None:
    events = _complete_events()
    events.append(
        _event(
            7,
            "NoveltyAssessmentRecorded",
            {
                "assessment_id": "novelty-2",
                "hypothesis_id": "h-1",
                "content_hash": CONTENT_HASH,
                "research_plan_version": 2,
                "verdict": "partially_novel",
                "closest_prior_work_ids": ["paper-2"],
            },
        )
    )

    snapshot = _reduce(events)

    assert snapshot.novelty_assessment_id == "novelty-2"
    assert snapshot.novelty_event_sequence == 7
    assert snapshot.missing_requirements == ()
    assert snapshot.conflicting_evidence == ()
    assert snapshot.source_event_sequences == (1, 2, 3, 4, 5, 6, 7)


# Mutations caught: letting content-v1 evidence admit content-v2, treating a delayed
# stale result as current, or dropping exact provenance for current mixed replay input.
def test_content_revision_replay_selects_only_current_evidence_provenance() -> None:
    current_hash = "sha256:" + "c" * 64
    events = [
        _event(
            1,
            "TournamentEpochOpened",
            {
                "epoch_id": "epoch-1",
                "research_plan_version": 2,
                "evaluation_rules_hash": "sha256:rules",
                "ranking_prompt_hash": "sha256:prompt",
                "judge_profile_hash": "sha256:judge",
                "rating_policy_version": "elo-32-v1",
                "admission_policy_version": "admission-v1",
            },
        ),
        _event(
            2,
            "HypothesisContentCreated",
            {
                "hypothesis_id": "h-1",
                "content_id": "content-v1",
                "content_hash": CONTENT_HASH,
                "research_plan_version": 1,
            },
            schema_version=2,
        ),
        _event(
            3,
            "ReviewCompleted",
            {
                "review_id": "v1-initial",
                "hypothesis_id": "h-1",
                "content_hash": CONTENT_HASH,
                "research_plan_version": 1,
                "stage": "initial_review",
                "recommendation": "pass",
                "safety_status": "passed",
                "critical_flaws": [],
            },
            schema_version=2,
        ),
        _event(
            4,
            "NoveltyAssessmentRecorded",
            {
                "assessment_id": "v1-novelty",
                "hypothesis_id": "h-1",
                "content_hash": CONTENT_HASH,
                "research_plan_version": 1,
                "verdict": "novel",
            },
        ),
        _event(
            5,
            "HypothesisContentCreated",
            {
                "hypothesis_id": "h-1",
                "content_id": "content-v2",
                "content_hash": current_hash,
                "research_plan_version": 2,
                "supersedes_content_id": "content-v1",
            },
            schema_version=2,
        ),
        _event(
            6,
            "ReviewCompleted",
            {
                "review_id": "delayed-v1-full",
                "hypothesis_id": "h-1",
                "content_hash": CONTENT_HASH,
                "research_plan_version": 1,
                "stage": "full_review",
                "recommendation": "pass",
                "safety_status": "not_assessed",
                "critical_flaws": [],
            },
            schema_version=2,
        ),
        _event(
            7,
            "ReviewCompleted",
            {
                "review_id": "v2-initial",
                "hypothesis_id": "h-1",
                "content_hash": current_hash,
                "research_plan_version": 2,
                "stage": "initial_review",
                "recommendation": "pass",
                "safety_status": "passed",
                "critical_flaws": [],
            },
            schema_version=2,
        ),
        _event(
            8,
            "NoveltyAssessmentRecorded",
            {
                "assessment_id": "delayed-v1-novelty",
                "hypothesis_id": "h-1",
                "content_hash": CONTENT_HASH,
                "research_plan_version": 1,
                "verdict": "novel",
            },
        ),
        _event(
            9,
            "ReviewCompleted",
            {
                "review_id": "v2-full",
                "hypothesis_id": "h-1",
                "content_hash": current_hash,
                "research_plan_version": 2,
                "stage": "full_review",
                "recommendation": "pass",
                "safety_status": "not_assessed",
                "critical_flaws": [],
            },
            schema_version=2,
        ),
        _event(
            10,
            "NoveltyAssessmentRecorded",
            {
                "assessment_id": "v2-novelty",
                "hypothesis_id": "h-1",
                "content_hash": current_hash,
                "research_plan_version": 2,
                "verdict": "partially_novel",
            },
        ),
        _event(
            11,
            "ProximityAssessed",
            {
                "edge_id": "delayed-v1-edge",
                "research_plan_version": 1,
                "left_id": "h-1",
                "left_content_hash": CONTENT_HASH,
                "right_id": "h-2",
                "right_content_hash": OTHER_CONTENT_HASH,
                "similarity": 2,
                "duplicate_likelihood": 0.1,
                "rationale": "stale",
            },
            schema_version=2,
        ),
        _event(
            12,
            "ProximityAssessed",
            {
                "edge_id": "v2-edge",
                "research_plan_version": 2,
                "left_id": "h-1",
                "left_content_hash": current_hash,
                "right_id": "h-2",
                "right_content_hash": OTHER_CONTENT_HASH,
                "similarity": 2,
                "duplicate_likelihood": 0.1,
                "rationale": "current",
            },
            schema_version=2,
        ),
    ]

    snapshot = _reduce(events)

    assert snapshot.content_id == "content-v2"
    assert snapshot.content_hash == current_hash
    assert snapshot.review_ids == ("v2-initial", "v2-full")
    assert snapshot.novelty_assessment_id == "v2-novelty"
    assert snapshot.proximity_edge_ids == ("v2-edge",)
    assert snapshot.missing_requirements == ()
    assert snapshot.conflicting_evidence == ()
    assert snapshot.source_event_sequences == (1, 5, 7, 9, 10, 12)


def _remove(event_type: str, *, stage: str | None = None) -> Callable[[list[DomainEvent]], None]:
    def mutate(events: list[DomainEvent]) -> None:
        events[:] = [
            event
            for event in events
            if not (
                event.event_type == event_type
                and (stage is None or event.payload.get("stage") == stage)
            )
        ]

    return mutate


def _replace_payload(
    event_type: str,
    updates: dict[str, object],
    *,
    stage: str | None = None,
) -> Callable[[list[DomainEvent]], None]:
    def mutate(events: list[DomainEvent]) -> None:
        for index, event in enumerate(events):
            if event.event_type == event_type and (
                stage is None or event.payload.get("stage") == stage
            ):
                events[index] = event.model_copy(
                    update={"payload": {**event.payload, **updates}}
                )
                return
        raise AssertionError(f"fixture event missing: {event_type}")

    return mutate


def _append_conflicting_safety(events: list[DomainEvent]) -> None:
    events.append(
        _event(
            7,
            "ReviewCompleted",
            {
                "review_id": "review-initial-blocked",
                "hypothesis_id": "h-1",
                "content_hash": CONTENT_HASH,
                "research_plan_version": 2,
                "stage": "initial_review",
                "recommendation": "reject",
                "safety_status": "blocked",
                "critical_flaws": [],
            },
            schema_version=2,
        )
    )


@pytest.mark.parametrize(
    ("mutate", "expected_missing", "expected_safety", "expected_conflict"),
    [
        (
            _remove("ReviewCompleted", stage="initial_review"),
            {"initial_review", "safety"},
            "missing",
            None,
        ),
        (
            _replace_payload(
                "ReviewCompleted", {"safety_status": "blocked"}, stage="initial_review"
            ),
            {"initial_review", "safety"},
            "blocked",
            None,
        ),
        (
            _append_conflicting_safety,
            {"initial_review", "safety"},
            "conflicting",
            "conflicting_safety",
        ),
        (
            _replace_payload(
                "ReviewCompleted", {"critical_flaws": ["fatal flaw"]}, stage="full_review"
            ),
            {"full_review", "critical_flaws"},
            "passed",
            "critical_flaw:review-full",
        ),
        (
            _replace_payload(
                "ReviewCompleted", {"content_hash": OTHER_CONTENT_HASH}, stage="full_review"
            ),
            {"full_review"},
            "passed",
            "stale_review:review-full",
        ),
        (
            _replace_payload(
                "ReviewCompleted", {"research_plan_version": 1}, stage="full_review"
            ),
            {"full_review"},
            "passed",
            "stale_review:review-full",
        ),
        (
            _remove("NoveltyAssessmentRecorded"),
            {"novelty_assessment"},
            "passed",
            None,
        ),
        (
            _replace_payload(
                "NoveltyAssessmentRecorded", {"content_hash": OTHER_CONTENT_HASH}
            ),
            {"novelty_assessment"},
            "passed",
            "stale_novelty:novelty-1",
        ),
        (
            _remove("ProximityAssessed"),
            {"proximity"},
            "passed",
            None,
        ),
        (
            _replace_payload("ProximityAssessed", {"duplicate_likelihood": 0.5}),
            {"candidate_duplicate"},
            "passed",
            None,
        ),
        (
            _remove("TournamentEpochOpened"),
            {"active_epoch"},
            "passed",
            None,
        ),
        (
            _replace_payload(
                "TournamentEpochOpened", {"admission_policy_version": "admission-v2"}
            ),
            {"admission_policy"},
            "passed",
            "admission_policy_mismatch",
        ),
    ],
)
def test_reducer_fails_closed_for_missing_stale_blocked_or_conflicting_evidence(
    mutate: Callable[[list[DomainEvent]], None],
    expected_missing: set[str],
    expected_safety: str,
    expected_conflict: str | None,
) -> None:
    events = _complete_events()
    mutate(events)

    snapshot = _reduce(events)

    assert expected_missing.issubset(snapshot.missing_requirements)
    assert snapshot.safety_status == expected_safety
    if expected_conflict is not None:
        assert expected_conflict in snapshot.conflicting_evidence


# Mutation caught: treating unrelated or unsupported event versions as current evidence.
def test_reducer_ignores_other_runs_and_rejects_unsupported_scientific_event_versions() -> None:
    events = _complete_events()
    initial = events[2]
    events[2] = initial.model_copy(update={"schema_version": 1})
    events.append(
        _event(
            7,
            "ReviewCompleted",
            dict(initial.payload),
            schema_version=2,
        ).model_copy(update={"run_id": "run-other"})
    )

    snapshot = _reduce(events)

    assert {"initial_review", "safety"}.issubset(snapshot.missing_requirements)
    assert "unsupported_event_version:ReviewCompleted:1" in snapshot.conflicting_evidence


# Mutation caught: inventing a hypothesis shell when no canonical content exists.
def test_reducer_rejects_nonexistent_hypothesis() -> None:
    snapshot = _reduce(_complete_events(), hypothesis_id="h-missing")

    assert snapshot.content_id is None
    assert snapshot.content_event_sequence is None
    assert "hypothesis" in snapshot.missing_requirements
