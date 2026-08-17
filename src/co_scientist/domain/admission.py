"""Pure, fail-closed reduction of durable tournament-admission evidence."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from co_scientist.domain.review import ReviewPolicy, ReviewStage
from co_scientist.domain.tournament import TournamentEpoch
from co_scientist.events.models import DomainEvent


class AdmissionPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str
    review_policy: ReviewPolicy
    literature_novelty_required: bool
    duplicate_likelihood_threshold: float = Field(ge=0.0, le=1.0)


class AdmissionEvidenceSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    hypothesis_id: str
    content_id: str | None
    content_hash: str | None
    research_plan_version: int | None
    admission_policy_version: str
    required_review_stages: tuple[ReviewStage, ...]
    safety_status: Literal["passed", "blocked", "missing", "conflicting"]
    novelty_assessment_id: str | None
    duplicate_detected: bool | None
    epoch_id: str | None
    rating_policy_version: str | None
    missing_requirements: tuple[str, ...]
    conflicting_evidence: tuple[str, ...]
    source_event_sequences: tuple[int, ...]
    review_ids: tuple[str, ...]
    proximity_edge_ids: tuple[str, ...]
    content_event_sequence: int | None
    novelty_event_sequence: int | None
    proximity_event_sequences: tuple[int, ...]
    epoch_event_sequence: int | None


_SUPPORTED_EVENT_VERSIONS = {
    "HypothesisContentCreated": 2,
    "ReviewCompleted": 2,
    "NoveltyAssessmentRecorded": 1,
    "ProximityAssessed": 2,
    "TournamentEpochOpened": 1,
    "TournamentEpochClosed": 1,
}


def admission_policy_from_manifest(
    manifest: Mapping[str, Any],
    *,
    version: str,
) -> AdmissionPolicy:
    """Resolve one exact admission-policy version from an immutable Run manifest."""

    policies = manifest.get("admission_policies")
    profile = manifest.get("profile")
    if not isinstance(policies, Mapping) and isinstance(profile, Mapping):
        policies = profile.get("admission_policies")
    if not isinstance(policies, Mapping):
        raise TypeError("Run manifest has no resolved admission policies")
    value = policies.get(version)
    if not isinstance(value, Mapping):
        raise TypeError(f"Run manifest has no admission policy: {version}")
    policy = AdmissionPolicy.model_validate(value)
    if policy.version != version:
        raise ValueError(
            f"Run manifest admission policy version mismatch: {policy.version} != {version}"
        )
    return policy


def _ordered_stages(policy: AdmissionPolicy) -> tuple[ReviewStage, ...]:
    stages: list[ReviewStage] = []
    for stage in (ReviewStage.INITIAL, *policy.review_policy.required_before_admission):
        if stage not in stages:
            stages.append(stage)
    return tuple(stages)


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _targets_hypothesis(event: DomainEvent, hypothesis_id: str) -> bool:
    payload = event.payload
    if event.event_type in {
        "HypothesisContentCreated",
        "ReviewCompleted",
        "NoveltyAssessmentRecorded",
    }:
        return payload.get("hypothesis_id") == hypothesis_id
    if event.event_type == "ProximityAssessed":
        return hypothesis_id in {payload.get("left_id"), payload.get("right_id")}
    return event.event_type in {"TournamentEpochOpened", "TournamentEpochClosed"}


def reduce_admission_evidence(
    *,
    run_id: str,
    hypothesis_id: str,
    events: Sequence[DomainEvent],
    policy: AdmissionPolicy,
) -> AdmissionEvidenceSnapshot:
    """Fold an ordered event snapshot into immutable, content-bound admission evidence."""

    content_event: DomainEvent | None = None
    active_epoch_event: DomainEvent | None = None
    review_events: list[DomainEvent] = []
    novelty_events: list[DomainEvent] = []
    proximity_events: list[DomainEvent] = []
    conflicting: list[str] = []
    source_sequences: set[int] = set()

    for event in events:
        if event.run_id != run_id or not _targets_hypothesis(event, hypothesis_id):
            continue
        supported_version = _SUPPORTED_EVENT_VERSIONS.get(event.event_type)
        if supported_version is None:
            continue
        if event.schema_version != supported_version:
            _append_unique(
                conflicting,
                f"unsupported_event_version:{event.event_type}:{event.schema_version}",
            )
            source_sequences.add(event.sequence)
            continue
        if event.event_type == "HypothesisContentCreated":
            content_event = event
        elif event.event_type == "ReviewCompleted":
            review_events.append(event)
        elif event.event_type == "NoveltyAssessmentRecorded":
            novelty_events.append(event)
        elif event.event_type == "ProximityAssessed":
            proximity_events.append(event)
        elif event.event_type == "TournamentEpochOpened":
            active_epoch_event = event
        elif (
            active_epoch_event is not None
            and event.payload.get("epoch_id") == active_epoch_event.payload.get("epoch_id")
        ):
            source_sequences.add(event.sequence)
            active_epoch_event = None

    missing: list[str] = []
    required_stages = _ordered_stages(policy)
    content_id: str | None = None
    content_hash: str | None = None
    plan_version: int | None = None
    if content_event is None:
        _append_unique(missing, "hypothesis")
    else:
        payload = content_event.payload
        raw_content_id = payload.get("content_id")
        raw_content_hash = payload.get("content_hash")
        raw_plan_version = payload.get("research_plan_version")
        if (
            not isinstance(raw_content_id, str)
            or not raw_content_id
            or not isinstance(raw_content_hash, str)
            or not raw_content_hash
            or isinstance(raw_plan_version, bool)
            or not isinstance(raw_plan_version, int)
        ):
            _append_unique(missing, "hypothesis")
            _append_unique(conflicting, f"invalid_content:{content_event.sequence}")
        else:
            content_id = raw_content_id
            content_hash = raw_content_hash
            plan_version = raw_plan_version
        source_sequences.add(content_event.sequence)

    epoch: TournamentEpoch | None = None
    if active_epoch_event is None:
        _append_unique(missing, "active_epoch")
    else:
        source_sequences.add(active_epoch_event.sequence)
        try:
            epoch = TournamentEpoch.model_validate(active_epoch_event.payload)
        except ValidationError:
            _append_unique(missing, "active_epoch")
            _append_unique(conflicting, f"invalid_epoch:{active_epoch_event.sequence}")
        if epoch is not None and epoch.admission_policy_version != policy.version:
            _append_unique(missing, "admission_policy")
            _append_unique(conflicting, "admission_policy_mismatch")
        if (
            epoch is not None
            and plan_version is not None
            and epoch.research_plan_version != plan_version
        ):
            _append_unique(missing, "active_epoch")
            _append_unique(conflicting, "epoch_plan_mismatch")

    current_reviews: list[DomainEvent] = []
    stale_reviews: dict[ReviewStage, list[DomainEvent]] = defaultdict(list)
    for event in review_events:
        payload = event.payload
        review_id = payload.get("review_id")
        raw_stage = payload.get("stage")
        if not isinstance(raw_stage, str):
            source_sequences.add(event.sequence)
            _append_unique(conflicting, f"invalid_review_stage:{review_id or event.sequence}")
            continue
        try:
            stage = ReviewStage(raw_stage)
        except ValueError:
            source_sequences.add(event.sequence)
            _append_unique(conflicting, f"invalid_review_stage:{review_id or event.sequence}")
            continue
        if (
            content_hash is None
            or plan_version is None
            or payload.get("content_hash") != content_hash
            or payload.get("research_plan_version") != plan_version
        ):
            stale_reviews[stage].append(event)
            continue
        current_reviews.append(event)
        source_sequences.add(event.sequence)

    reviews_by_stage: dict[ReviewStage, list[DomainEvent]] = defaultdict(list)
    review_ids: list[str] = []
    for event in current_reviews:
        stage = ReviewStage(event.payload["stage"])
        reviews_by_stage[stage].append(event)
        review_id = event.payload.get("review_id")
        if isinstance(review_id, str) and review_id:
            review_ids.append(review_id)
        else:
            _append_unique(conflicting, f"invalid_review_id:{event.sequence}")

    critical_review_ids: list[str] = []
    for event in current_reviews:
        flaws = event.payload.get("critical_flaws", ())
        if isinstance(flaws, (tuple, list)) and flaws:
            review_id = str(event.payload.get("review_id", event.sequence))
            critical_review_ids.append(review_id)
            _append_unique(conflicting, f"critical_flaw:{review_id}")
    if critical_review_ids:
        _append_unique(missing, "critical_flaws")

    for stage in required_stages:
        stage_reviews = reviews_by_stage.get(stage, [])
        qualifies = bool(stage_reviews) and all(
            event.payload.get("recommendation") == "pass"
            and not event.payload.get("critical_flaws", ())
            for event in stage_reviews
        )
        if not qualifies:
            _append_unique(missing, stage.value)
            for stale in stale_reviews.get(stage, []):
                source_sequences.add(stale.sequence)
                review_id = stale.payload.get("review_id", stale.sequence)
                _append_unique(conflicting, f"stale_review:{review_id}")
        recommendations = {event.payload.get("recommendation") for event in stage_reviews}
        if len(recommendations) > 1:
            _append_unique(conflicting, f"conflicting_review:{stage.value}")

    initial_reviews = reviews_by_stage.get(ReviewStage.INITIAL, [])
    safety_values = {event.payload.get("safety_status") for event in initial_reviews}
    if safety_values == {"passed"}:
        safety_status: Literal["passed", "blocked", "missing", "conflicting"] = "passed"
    elif safety_values == {"blocked"}:
        safety_status = "blocked"
        _append_unique(missing, "safety")
        _append_unique(missing, ReviewStage.INITIAL.value)
    elif not safety_values or safety_values == {"not_assessed"}:
        safety_status = "missing"
        _append_unique(missing, "safety")
        _append_unique(missing, ReviewStage.INITIAL.value)
    else:
        safety_status = "conflicting"
        _append_unique(missing, "safety")
        _append_unique(missing, ReviewStage.INITIAL.value)
        _append_unique(conflicting, "conflicting_safety")

    current_novelty: list[DomainEvent] = []
    stale_novelty: list[DomainEvent] = []
    for event in novelty_events:
        if (
            content_hash is not None
            and plan_version is not None
            and event.payload.get("content_hash") == content_hash
            and event.payload.get("research_plan_version") == plan_version
        ):
            current_novelty.append(event)
            source_sequences.add(event.sequence)
        else:
            stale_novelty.append(event)
    novelty_id: str | None = None
    novelty_sequence: int | None = None
    if current_novelty:
        novelty = current_novelty[-1]
        raw_assessment_id = novelty.payload.get("assessment_id")
        if isinstance(raw_assessment_id, str) and raw_assessment_id:
            novelty_id = raw_assessment_id
            novelty_sequence = novelty.sequence
        else:
            _append_unique(conflicting, f"invalid_novelty:{novelty.sequence}")
        novelty_facts = {
            (event.payload.get("assessment_id"), event.payload.get("verdict"))
            for event in current_novelty
        }
        if len(novelty_facts) > 1:
            _append_unique(conflicting, "conflicting_novelty")
            novelty_id = None
            novelty_sequence = None
    qualifying_novelty = (
        novelty_id is not None
        and current_novelty[-1].payload.get("verdict") in {"novel", "partially_novel"}
        and "conflicting_novelty" not in conflicting
    )
    if policy.literature_novelty_required and not qualifying_novelty:
        _append_unique(missing, "novelty_assessment")
        if not current_novelty:
            for stale in stale_novelty:
                source_sequences.add(stale.sequence)
                assessment_id = stale.payload.get("assessment_id", stale.sequence)
                _append_unique(conflicting, f"stale_novelty:{assessment_id}")

    valid_proximity: list[DomainEvent] = []
    stale_proximity: list[DomainEvent] = []
    duplicate_values: list[float] = []
    proximity_edge_ids: list[str] = []
    for event in proximity_events:
        payload = event.payload
        candidate_hash = (
            payload.get("left_content_hash")
            if payload.get("left_id") == hypothesis_id
            else payload.get("right_content_hash")
        )
        if (
            content_hash is None
            or plan_version is None
            or candidate_hash != content_hash
            or payload.get("research_plan_version") != plan_version
        ):
            stale_proximity.append(event)
            continue
        likelihood = payload.get("duplicate_likelihood")
        edge_id = payload.get("edge_id")
        if (
            isinstance(likelihood, bool)
            or not isinstance(likelihood, (int, float))
            or not 0.0 <= float(likelihood) <= 1.0
            or not isinstance(edge_id, str)
            or not edge_id
        ):
            source_sequences.add(event.sequence)
            _append_unique(conflicting, f"invalid_proximity:{event.sequence}")
            continue
        valid_proximity.append(event)
        duplicate_values.append(float(likelihood))
        proximity_edge_ids.append(edge_id)
        source_sequences.add(event.sequence)
    duplicate_detected = (
        any(value >= policy.duplicate_likelihood_threshold for value in duplicate_values)
        if duplicate_values
        else None
    )
    if not valid_proximity:
        _append_unique(missing, "proximity")
        for stale in stale_proximity:
            source_sequences.add(stale.sequence)
            edge_id = stale.payload.get("edge_id", stale.sequence)
            _append_unique(conflicting, f"stale_proximity:{edge_id}")
    elif duplicate_detected:
        _append_unique(missing, "candidate_duplicate")

    seen_sequences: set[int] = set()
    ordered_sources: list[int] = []
    for event in events:
        if (
            event.run_id == run_id
            and event.sequence in source_sequences
            and event.sequence not in seen_sequences
        ):
            ordered_sources.append(event.sequence)
            seen_sequences.add(event.sequence)

    return AdmissionEvidenceSnapshot(
        run_id=run_id,
        hypothesis_id=hypothesis_id,
        content_id=content_id,
        content_hash=content_hash,
        research_plan_version=plan_version,
        admission_policy_version=policy.version,
        required_review_stages=required_stages,
        safety_status=safety_status,
        novelty_assessment_id=novelty_id,
        duplicate_detected=duplicate_detected,
        epoch_id=epoch.epoch_id if epoch is not None else None,
        rating_policy_version=epoch.rating_policy_version if epoch is not None else None,
        missing_requirements=tuple(missing),
        conflicting_evidence=tuple(conflicting),
        source_event_sequences=tuple(ordered_sources),
        review_ids=tuple(review_ids),
        proximity_edge_ids=tuple(proximity_edge_ids),
        content_event_sequence=content_event.sequence if content_event is not None else None,
        novelty_event_sequence=novelty_sequence,
        proximity_event_sequences=tuple(event.sequence for event in valid_proximity),
        epoch_event_sequence=(
            active_epoch_event.sequence if active_epoch_event is not None else None
        ),
    )
