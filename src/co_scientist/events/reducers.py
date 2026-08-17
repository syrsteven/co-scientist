"""Pure reducers for rebuilding projections from domain events."""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from pydantic import BaseModel, Field

from co_scientist.domain.hypothesis import (
    ContentRevisionProjection,
    HypothesisProjection,
    MatchParticipationProjection,
    NoveltyProjection,
    ProximityProjection,
    RatingProjection,
    ReviewProjection,
    SafetyEvidenceProjection,
    TournamentEntryProjection,
    TournamentReadinessProjection,
)
from co_scientist.events.contracts import assert_supported_event_version
from co_scientist.events.models import DomainEvent


def _required_str(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"scientific event requires {key}")
    return value


def _required_int(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"scientific event requires integer {key}")
    return value


def _required_float(payload: Mapping[str, Any], key: str) -> float:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"scientific event requires numeric {key}")
    return float(value)


def _revision_for_hash(
    projection: HypothesisProjection, content_hash: str
) -> ContentRevisionProjection:
    for revision in projection.content_revisions:
        if revision.content_hash == content_hash:
            return revision
    raise ValueError(f"scientific evidence references unknown content hash: {content_hash}")


def _assert_revision_binding(
    projection: HypothesisProjection, content_hash: str, research_plan_version: int
) -> ContentRevisionProjection:
    revision = _revision_for_hash(projection, content_hash)
    if revision.research_plan_version != research_plan_version:
        raise ValueError("scientific evidence research plan does not match content revision")
    return revision


def _validate_hypothesis_replay_contracts(events: list[DomainEvent]) -> None:
    opened_epochs: dict[str, tuple[int, str]] = {}
    active_epochs: set[str] = set()
    readiness: dict[tuple[str, str], tuple[str, int, str]] = {}
    entries: dict[tuple[str, str], tuple[str, float]] = {}
    initial_ratings: set[tuple[str, str]] = set()
    matches: dict[str, tuple[str, str, str, str]] = {}
    rating_updates: set[tuple[str, str]] = set()

    for event in events:
        assert_supported_event_version(event)
        payload = event.payload
        if event.event_type == "TournamentEpochOpened":
            epoch_id = _required_str(payload, "epoch_id")
            if epoch_id in opened_epochs:
                raise ValueError(f"duplicate opened epoch: {epoch_id}")
            opened_epochs[epoch_id] = (
                _required_int(payload, "research_plan_version"),
                _required_str(payload, "rating_policy_version"),
            )
            active_epochs.add(epoch_id)
        elif event.event_type == "TournamentEpochClosed":
            epoch_id = _required_str(payload, "epoch_id")
            if epoch_id not in active_epochs:
                raise ValueError(f"closing an epoch that is not open: {epoch_id}")
            active_epochs.remove(epoch_id)
        elif event.event_type == "HypothesisTournamentReady":
            epoch_id = _required_str(payload, "epoch_id")
            hypothesis_id = _required_str(payload, "hypothesis_id")
            epoch_contract = opened_epochs.get(epoch_id)
            if epoch_contract is None or epoch_id not in active_epochs:
                raise ValueError("tournament readiness requires the same opened epoch")
            plan_version = _required_int(payload, "research_plan_version")
            rating_policy = _required_str(payload, "rating_policy_version")
            if epoch_contract != (plan_version, rating_policy):
                raise ValueError("tournament readiness does not match opened epoch contract")
            key = (hypothesis_id, epoch_id)
            if key in readiness:
                raise ValueError("duplicate tournament readiness for hypothesis and epoch")
            readiness[key] = (
                _required_str(payload, "content_hash"),
                plan_version,
                rating_policy,
            )
        elif event.event_type == "TournamentEntryCreated":
            epoch_id = _required_str(payload, "epoch_id")
            hypothesis_id = _required_str(payload, "hypothesis_id")
            key = (hypothesis_id, epoch_id)
            ready = readiness.get(key)
            content_hash = _required_str(payload, "content_hash")
            if _required_int(payload, "matches_played") != 0:
                raise ValueError("tournament entry matches_played must start at zero")
            if (
                ready is None
                or epoch_id not in active_epochs
                or ready[0] != content_hash
            ):
                raise ValueError(
                    "tournament entry requires readiness for the same opened epoch"
                )
            if key in entries:
                raise ValueError("duplicate tournament entry for hypothesis and epoch")
            entries[key] = (content_hash, _required_float(payload, "rating"))
        elif event.event_type == "InitialRatingAssigned":
            epoch_id = _required_str(payload, "epoch_id")
            hypothesis_id = _required_str(payload, "hypothesis_id")
            key = (hypothesis_id, epoch_id)
            entry = entries.get(key)
            ready = readiness.get(key)
            if entry is None or ready is None:
                raise ValueError("initial rating requires a tournament entry")
            if _required_float(payload, "rating") != entry[1]:
                raise ValueError("initial rating does not match tournament entry")
            if _required_str(payload, "rating_policy_version") != ready[2]:
                raise ValueError("initial rating policy does not match opened epoch")
            if key in initial_ratings:
                raise ValueError("duplicate initial rating for hypothesis and epoch")
            initial_ratings.add(key)
        elif event.event_type == "MatchEvaluated":
            match_id = _required_str(payload, "match_id")
            if match_id in matches:
                raise ValueError(f"duplicate match_id: {match_id}")
            epoch_id = _required_str(payload, "epoch_id")
            left_id = _required_str(payload, "left_id")
            right_id = _required_str(payload, "right_id")
            if left_id == right_id:
                raise ValueError("match requires distinct participants")
            plan_version = _required_int(payload, "research_plan_version")
            left_entry = entries.get((left_id, epoch_id))
            right_entry = entries.get((right_id, epoch_id))
            if (
                epoch_id not in active_epochs
                or left_entry is None
                or right_entry is None
                or (left_id, epoch_id) not in initial_ratings
                or (right_id, epoch_id) not in initial_ratings
                or left_entry[0] != _required_str(payload, "left_content_hash")
                or right_entry[0] != _required_str(payload, "right_content_hash")
                or readiness[(left_id, epoch_id)][1] != plan_version
                or readiness[(right_id, epoch_id)][1] != plan_version
            ):
                raise ValueError(
                    "match requires a tournament entry for both participants "
                    "with matching content and epoch"
                )
            matches[match_id] = (
                epoch_id,
                left_id,
                right_id,
                _required_str(payload, "decision"),
            )
        elif event.event_type == "RatingUpdated":
            match_id = _required_str(payload, "match_id")
            hypothesis_id = _required_str(payload, "hypothesis_id")
            match = matches.get(match_id)
            if (
                match is None
                or match[3] != "decisive"
                or hypothesis_id not in {match[1], match[2]}
            ):
                raise ValueError("rating update requires a decisive participant match")
            key = (hypothesis_id, match_id)
            if key in rating_updates:
                raise ValueError("duplicate rating update for hypothesis and match")
            expected_policy = readiness[(hypothesis_id, match[0])][2]
            if _required_str(payload, "rating_policy_version") != expected_policy:
                raise ValueError("rating policy does not match tournament entry epoch")
            rating_updates.add(key)


def _refresh_current_bindings(
    projection: HypothesisProjection,
    *,
    current_content_hash: str,
    current_plan_version: int,
) -> dict[str, Any]:
    def applies(content_hash: str, plan_version: int) -> bool:
        return (
            content_hash == current_content_hash
            and plan_version == current_plan_version
        )

    reviews = tuple(
        review.model_copy(
            update={
                "applies_to_current_revision": applies(
                    review.content_hash, review.research_plan_version
                )
            }
        )
        for review in projection.review_history
    )
    novelty = tuple(
        item.model_copy(
            update={
                "applies_to_current_revision": applies(
                    item.content_hash, item.research_plan_version
                )
            }
        )
        for item in projection.novelty_history
    )
    proximity = tuple(
        item.model_copy(
            update={
                "applies_to_current_revision": applies(
                    item.own_content_hash, item.research_plan_version
                )
            }
        )
        for item in projection.proximity_history
    )
    matches = tuple(
        item.model_copy(
            update={
                "applies_to_current_revision": applies(
                    item.own_content_hash, item.research_plan_version
                )
            }
        )
        for item in projection.match_participation
    )
    readiness = tuple(
        item.model_copy(
            update={
                "applies_to_current_revision": applies(
                    item.content_hash, item.research_plan_version
                )
            }
        )
        for item in projection.tournament_readiness_history
    )
    entries = tuple(
        item.model_copy(
            update={
                "applies_to_current_revision": applies(
                    item.content_hash, item.research_plan_version
                )
            }
        )
        for item in projection.tournament_entry_history
    )
    ratings = tuple(
        item.model_copy(
            update={
                "applies_to_current_revision": applies(
                    item.content_hash, item.research_plan_version
                )
            }
        )
        for item in projection.rating_history
    )
    safety = tuple(
        item.model_copy(
            update={
                "applies_to_current_revision": item.content_hash
                == current_content_hash
            }
        )
        for item in projection.safety_evidence
    )
    assessed_safety = [
        item.status
        for item in safety
        if item.applies_to_current_revision
        and item.source_type == "review"
        and item.status in {"passed", "blocked"}
    ]
    current_proximity = [item for item in proximity if item.applies_to_current_revision]
    current_readiness = {
        item.epoch_id: item for item in readiness if item.applies_to_current_revision
    }
    current_entries = {
        item.epoch_id: item for item in entries if item.applies_to_current_revision
    }
    current_ratings: dict[str, float] = {}
    for item in ratings:
        if item.applies_to_current_revision:
            current_ratings[item.epoch_id] = item.rating
    return {
        "review_history": reviews,
        "novelty_history": novelty,
        "current_novelty_assessment_ids": tuple(
            item.assessment_id for item in novelty if item.applies_to_current_revision
        ),
        "proximity_history": proximity,
        "cluster_ids": tuple(
            dict.fromkeys(
                item.cluster_suggestion
                for item in current_proximity
                if item.cluster_suggestion is not None
            )
        ),
        "access_issues": tuple(
            dict.fromkeys(
                issue for item in current_proximity for issue in item.access_issues
            )
        ),
        "match_participation": matches,
        "tournament_readiness_history": readiness,
        "current_tournament_readiness_by_epoch": MappingProxyType(current_readiness),
        "tournament_entry_history": entries,
        "tournament_entries_by_epoch": MappingProxyType(current_entries),
        "rating_history": ratings,
        "current_ratings_by_epoch": MappingProxyType(current_ratings),
        "safety_evidence": safety,
        "current_safety_status": assessed_safety[-1] if assessed_safety else "pending",
    }


def reduce_hypothesis(
    projection: HypothesisProjection | None, event: DomainEvent, hypothesis_id: str
) -> HypothesisProjection | None:
    """Apply one event to a hypothesis projection without mutating either input."""
    assert_supported_event_version(event)
    payload = event.payload
    if event.event_type == "HypothesisContentCreated":
        if payload.get("hypothesis_id") != hypothesis_id:
            return projection
        content_id = _required_str(payload, "content_id")
        content_hash = _required_str(payload, "content_hash")
        plan_version = _required_int(payload, "research_plan_version")
        supersedes = payload.get("supersedes_content_id")
        if supersedes is not None and not isinstance(supersedes, str):
            raise ValueError("supersedes_content_id must be a string or null")
        if projection is not None:
            if any(
                revision.content_id == content_id or revision.content_hash == content_hash
                for revision in projection.content_revisions
            ):
                raise ValueError("duplicate hypothesis content revision")
            if supersedes is not None and supersedes != projection.current_content_id:
                raise ValueError("content revision does not supersede the current content")
            revision = ContentRevisionProjection(
                content_id=content_id,
                content_hash=content_hash,
                research_plan_version=plan_version,
                parent_content_ids=tuple(payload.get("parent_content_ids", ())),
                supersedes_content_id=supersedes,
                created_sequence=event.sequence,
            )
            updated = projection.model_copy(
                update={
                    "content_revisions": (*projection.content_revisions, revision),
                    "current_content_id": content_id,
                    "current_content_hash": content_hash,
                    "current_research_plan_version": plan_version,
                    "lifecycle_state": "created",
                    "updated_sequence": event.sequence,
                }
            )
            return updated.model_copy(
                update=_refresh_current_bindings(
                    updated,
                    current_content_hash=content_hash,
                    current_plan_version=plan_version,
                )
            )
        revision = ContentRevisionProjection(
            content_id=content_id,
            content_hash=content_hash,
            research_plan_version=plan_version,
            parent_content_ids=tuple(payload.get("parent_content_ids", ())),
            supersedes_content_id=supersedes,
            created_sequence=event.sequence,
        )
        return HypothesisProjection(
            hypothesis_id=hypothesis_id,
            content_revisions=(revision,),
            current_content_id=content_id,
            current_content_hash=content_hash,
            current_research_plan_version=plan_version,
            created_sequence=event.sequence,
            updated_sequence=event.sequence,
        )

    is_direct = payload.get("hypothesis_id") == hypothesis_id
    is_proximity = event.event_type == "ProximityAssessed" and hypothesis_id in {
        payload.get("left_id"),
        payload.get("right_id"),
    }
    is_match = event.event_type == "MatchEvaluated" and hypothesis_id in {
        payload.get("left_id"),
        payload.get("right_id"),
    }
    source_hashes = payload.get("source_content_hashes")
    is_meta = (
        event.event_type == "MetaReviewCompleted"
        and isinstance(source_hashes, Mapping)
        and hypothesis_id in source_hashes
    )
    if not (is_direct or is_proximity or is_match or is_meta):
        return projection
    if projection is None:
        raise ValueError("hypothesis scientific evidence precedes canonical content")

    if event.event_type == "ReviewCompleted":
        content_hash = _required_str(payload, "content_hash")
        plan_version = _required_int(payload, "research_plan_version")
        _assert_revision_binding(projection, content_hash, plan_version)
        review_id = _required_str(payload, "review_id")
        stage = _required_str(payload, "stage")
        safety_status = _required_str(payload, "safety_status")
        review = ReviewProjection(
            review_id=review_id,
            content_hash=content_hash,
            research_plan_version=plan_version,
            stage=stage,
            recommendation=_required_str(payload, "recommendation"),
            safety_status=safety_status,
            critical_flaws=tuple(payload.get("critical_flaws", ())),
            evidence_ids=tuple(payload.get("evidence_ids", ())),
            sequence=event.sequence,
            applies_to_current_revision=False,
        )
        coverage = {
            item_hash: {item_stage: tuple(ids) for item_stage, ids in stages.items()}
            for item_hash, stages in projection.review_coverage_by_content.items()
        }
        stages = coverage.setdefault(content_hash, {})
        stages[stage] = (*stages.get(stage, ()), review_id)
        frozen_coverage = MappingProxyType(
            {
                item_hash: MappingProxyType(dict(item_stages))
                for item_hash, item_stages in coverage.items()
            }
        )
        safety = SafetyEvidenceProjection(
            source_type="review",
            source_id=review_id,
            content_hash=content_hash,
            status=safety_status,
            sequence=event.sequence,
            applies_to_current_revision=False,
        )
        updated = projection.model_copy(
            update={
                "review_history": (*projection.review_history, review),
                "review_coverage_by_content": frozen_coverage,
                "safety_evidence": (*projection.safety_evidence, safety),
                "updated_sequence": event.sequence,
            }
        )
    elif event.event_type == "NoveltyAssessmentRecorded":
        content_hash = _required_str(payload, "content_hash")
        plan_version = _required_int(payload, "research_plan_version")
        _assert_revision_binding(projection, content_hash, plan_version)
        novelty_item = NoveltyProjection(
            assessment_id=_required_str(payload, "assessment_id"),
            content_hash=content_hash,
            research_plan_version=plan_version,
            verdict=_required_str(payload, "verdict"),
            closest_prior_work_ids=tuple(payload.get("closest_prior_work_ids", ())),
            evidence_ids=tuple(payload.get("evidence_ids", ())),
            sequence=event.sequence,
            applies_to_current_revision=False,
        )
        updated = projection.model_copy(
            update={
                "novelty_history": (*projection.novelty_history, novelty_item),
                "updated_sequence": event.sequence,
            }
        )
    elif event.event_type == "ProximityAssessed":
        left = payload.get("left_id") == hypothesis_id
        own_hash = _required_str(
            payload, "left_content_hash" if left else "right_content_hash"
        )
        other_hash = _required_str(
            payload, "right_content_hash" if left else "left_content_hash"
        )
        plan_version = _required_int(payload, "research_plan_version")
        _assert_revision_binding(projection, own_hash, plan_version)
        proximity_item = ProximityProjection(
            edge_id=_required_str(payload, "edge_id"),
            own_content_hash=own_hash,
            other_hypothesis_id=_required_str(payload, "right_id" if left else "left_id"),
            other_content_hash=other_hash,
            research_plan_version=plan_version,
            similarity=_required_int(payload, "similarity"),
            mechanism_overlap=tuple(payload.get("mechanism_overlap", ())),
            duplicate_likelihood=_required_float(payload, "duplicate_likelihood"),
            cluster_suggestion=(
                str(payload["cluster_suggestion"])
                if payload.get("cluster_suggestion") is not None
                else None
            ),
            rationale=_required_str(payload, "rationale"),
            access_issues=tuple(payload.get("access_issues", ())),
            sequence=event.sequence,
            applies_to_current_revision=False,
        )
        updated = projection.model_copy(
            update={
                "proximity_history": (*projection.proximity_history, proximity_item),
                "updated_sequence": event.sequence,
            }
        )
    elif event.event_type == "HypothesisTournamentReady":
        content_hash = _required_str(payload, "content_hash")
        plan_version = _required_int(payload, "research_plan_version")
        if (
            content_hash != projection.current_content_hash
            or plan_version != projection.current_research_plan_version
        ):
            raise ValueError("tournament readiness does not bind current content")
        readiness_item = TournamentReadinessProjection(
            epoch_id=_required_str(payload, "epoch_id"),
            content_hash=content_hash,
            research_plan_version=plan_version,
            rating_policy_version=_required_str(payload, "rating_policy_version"),
            sequence=event.sequence,
            applies_to_current_revision=False,
        )
        updated = projection.model_copy(
            update={
                "tournament_readiness_history": (
                    *projection.tournament_readiness_history,
                    readiness_item,
                ),
                "lifecycle_state": "tournament_ready",
                "updated_sequence": event.sequence,
            }
        )
        return updated.model_copy(
            update=_refresh_current_bindings(
                updated,
                current_content_hash=updated.current_content_hash,
                current_plan_version=updated.current_research_plan_version,
            )
        )
    elif event.event_type == "TournamentEntryCreated":
        content_hash = _required_str(payload, "content_hash")
        if content_hash != projection.current_content_hash:
            raise ValueError("tournament entry does not bind current content")
        epoch_id = _required_str(payload, "epoch_id")
        matching_readiness = next(
            (
                item
                for item in reversed(projection.tournament_readiness_history)
                if item.epoch_id == epoch_id and item.content_hash == content_hash
            ),
            None,
        )
        if matching_readiness is None:
            raise ValueError("tournament entry requires readiness for the same opened epoch")
        entry_item = TournamentEntryProjection(
            epoch_id=epoch_id,
            content_hash=content_hash,
            research_plan_version=matching_readiness.research_plan_version,
            rating_policy_version=matching_readiness.rating_policy_version,
            initial_rating=_required_float(payload, "rating"),
            matches_played=0,
            created_sequence=event.sequence,
            applies_to_current_revision=False,
        )
        updated = projection.model_copy(
            update={
                "tournament_entry_history": (
                    *projection.tournament_entry_history,
                    entry_item,
                ),
                "lifecycle_state": "tournament_active",
                "updated_sequence": event.sequence,
            }
        )
        return updated.model_copy(
            update=_refresh_current_bindings(
                updated,
                current_content_hash=updated.current_content_hash,
                current_plan_version=updated.current_research_plan_version,
            )
        )
    elif event.event_type == "InitialRatingAssigned":
        epoch_id = _required_str(payload, "epoch_id")
        entry = next(
            (
                item
                for item in reversed(projection.tournament_entry_history)
                if item.epoch_id == epoch_id
            ),
            None,
        )
        if entry is None:
            raise ValueError("initial rating requires a tournament entry")
        rating = _required_float(payload, "rating")
        if rating != entry.initial_rating:
            raise ValueError("initial rating does not match tournament entry")
        rating_policy = _required_str(payload, "rating_policy_version")
        if rating_policy != entry.rating_policy_version:
            raise ValueError("initial rating policy does not match tournament entry")
        initial_rating_item = RatingProjection(
            epoch_id=epoch_id,
            content_hash=entry.content_hash,
            research_plan_version=entry.research_plan_version,
            rating=rating,
            rating_policy_version=rating_policy,
            source="initial",
            sequence=event.sequence,
            applies_to_current_revision=False,
        )
        updated = projection.model_copy(
            update={
                "rating_history": (*projection.rating_history, initial_rating_item),
                "updated_sequence": event.sequence,
            }
        )
        return updated.model_copy(
            update=_refresh_current_bindings(
                updated,
                current_content_hash=updated.current_content_hash,
                current_plan_version=updated.current_research_plan_version,
            )
        )
    elif event.event_type == "MatchEvaluated":
        left = payload.get("left_id") == hypothesis_id
        own_hash = _required_str(
            payload, "left_content_hash" if left else "right_content_hash"
        )
        other_hash = _required_str(
            payload, "right_content_hash" if left else "left_content_hash"
        )
        plan_version = _required_int(payload, "research_plan_version")
        _assert_revision_binding(projection, own_hash, plan_version)
        epoch_id = _required_str(payload, "epoch_id")
        entry = next(
            (
                item
                for item in reversed(projection.tournament_entry_history)
                if item.epoch_id == epoch_id and item.content_hash == own_hash
            ),
            None,
        )
        if entry is None:
            raise ValueError(
                "match requires a tournament entry for both participants "
                "with matching content and epoch"
            )
        match_item = MatchParticipationProjection(
            match_id=_required_str(payload, "match_id"),
            epoch_id=epoch_id,
            opponent_id=_required_str(payload, "right_id" if left else "left_id"),
            own_content_hash=own_hash,
            opponent_content_hash=other_hash,
            research_plan_version=plan_version,
            decision=_required_str(payload, "decision"),
            winner_id=(str(payload["winner_id"]) if payload.get("winner_id") else None),
            sequence=event.sequence,
            applies_to_current_revision=False,
        )
        advanced_entries = tuple(
            item.model_copy(update={"matches_played": item.matches_played + 1})
            if item is entry
            else item
            for item in projection.tournament_entry_history
        )
        updated = projection.model_copy(
            update={
                "match_participation": (*projection.match_participation, match_item),
                "tournament_entry_history": advanced_entries,
                "updated_sequence": event.sequence,
            }
        )
    elif event.event_type == "RatingUpdated":
        epoch_id = _required_str(payload, "epoch_id")
        entry = next(
            (
                item
                for item in reversed(projection.tournament_entry_history)
                if item.epoch_id == epoch_id
            ),
            None,
        )
        if entry is None:
            raise ValueError("rating update requires a tournament entry")
        match_id = _required_str(payload, "match_id")
        match = next(
            (
                item
                for item in reversed(projection.match_participation)
                if item.match_id == match_id and item.epoch_id == epoch_id
            ),
            None,
        )
        if match is None or match.decision != "decisive":
            raise ValueError("rating update requires a decisive match")
        before = _required_float(payload, "before_rating")
        prior_rating = next(
            (
                item.rating
                for item in reversed(projection.rating_history)
                if item.epoch_id == epoch_id
                and item.content_hash == entry.content_hash
                and item.research_plan_version == entry.research_plan_version
            ),
            None,
        )
        if prior_rating != before:
            raise ValueError("rating update before_rating does not match projection")
        rating = _required_float(payload, "rating")
        rating_policy = _required_str(payload, "rating_policy_version")
        if rating_policy != entry.rating_policy_version:
            raise ValueError("rating policy does not match tournament entry epoch")
        rating_update_item = RatingProjection(
            epoch_id=epoch_id,
            content_hash=entry.content_hash,
            research_plan_version=entry.research_plan_version,
            rating=rating,
            rating_policy_version=rating_policy,
            source="match",
            sequence=event.sequence,
            match_id=match_id,
            before_rating=before,
            applies_to_current_revision=False,
        )
        updated = projection.model_copy(
            update={
                "rating_history": (*projection.rating_history, rating_update_item),
                "updated_sequence": event.sequence,
            }
        )
        return updated.model_copy(
            update=_refresh_current_bindings(
                updated,
                current_content_hash=updated.current_content_hash,
                current_plan_version=updated.current_research_plan_version,
            )
        )
    elif event.event_type == "MetaReviewCompleted":
        assert isinstance(source_hashes, Mapping)
        content_hash = str(source_hashes[hypothesis_id])
        plan_version = _required_int(payload, "research_plan_version")
        _assert_revision_binding(projection, content_hash, plan_version)
        safety = SafetyEvidenceProjection(
            source_type="meta_review",
            source_id=f"meta:{event.sequence}",
            content_hash=content_hash,
            status=_required_str(payload, "safety_direction_check"),
            sequence=event.sequence,
            applies_to_current_revision=False,
        )
        updated = projection.model_copy(
            update={
                "safety_evidence": (*projection.safety_evidence, safety),
                "updated_sequence": event.sequence,
            }
        )
    else:
        return projection
    return updated.model_copy(
        update=_refresh_current_bindings(
            updated,
            current_content_hash=updated.current_content_hash,
            current_plan_version=updated.current_research_plan_version,
        )
    )


def replay_hypothesis(
    hypothesis_id: str, events: list[DomainEvent]
) -> HypothesisProjection:
    """Deterministically rebuild one hypothesis projection from an event stream."""
    _validate_hypothesis_replay_contracts(events)
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
