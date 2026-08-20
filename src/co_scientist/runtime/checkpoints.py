"""Construction and validation of durable convergence checkpoints."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from co_scientist.adapters.persistence.sqlite import CommitResult, SqliteUnitOfWork
from co_scientist.domain.convergence import ConvergenceCheckpoint
from co_scientist.domain.tournament import (
    MatchDecision,
    MatchResult,
    TournamentEpoch,
    apply_match,
    get_rating_policy,
)
from co_scientist.events.models import DomainEvent, NewEvent


class RecordedCheckpoint(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    checkpoint_id: str
    source_sequence: int
    commit: CommitResult


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _identity(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _required_non_negative(config: Mapping[str, Any], key: str) -> int:
    value = config.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"frozen stop policy requires non-negative {key}")
    return value


def _required_positive(config: Mapping[str, Any], key: str) -> int:
    value = _required_non_negative(config, key)
    if value == 0:
        raise ValueError(f"frozen stop policy requires positive {key}")
    return value


class ConvergenceCheckpointBuilder:
    """Derive stop evidence solely from a Run's immutable manifest and durable rows."""

    def __init__(self, uow: SqliteUnitOfWork) -> None:
        self.uow = uow

    @staticmethod
    def _active_epoch(events: Sequence[DomainEvent]) -> tuple[TournamentEpoch, int]:
        active: tuple[TournamentEpoch, int] | None = None
        for event in events:
            if event.event_type == "TournamentEpochOpened":
                active = (TournamentEpoch.model_validate(event.payload), event.sequence)
            elif (
                event.event_type == "TournamentEpochClosed"
                and active is not None
                and event.payload.get("epoch_id") == active[0].epoch_id
            ):
                active = None
        if active is None:
            raise ValueError("checkpoint requires an active TournamentEpoch")
        return active

    @staticmethod
    def _stop_policy(manifest: Mapping[str, Any]) -> Mapping[str, Any]:
        profile = manifest.get("profile")
        candidate = profile.get("stop") if isinstance(profile, Mapping) else manifest.get("stop")
        if not isinstance(candidate, Mapping):
            raise TypeError("Run manifest has no frozen stop policy")
        return candidate

    @staticmethod
    def _anchor_members(
        manifest: Mapping[str, Any], anchor_set_id: str
    ) -> tuple[tuple[str, str], ...]:
        raw_sets = manifest.get("anchor_sets")
        if not isinstance(raw_sets, list):
            raise TypeError("Run manifest has no frozen anchor membership")
        matching = [
            item
            for item in raw_sets
            if isinstance(item, Mapping) and item.get("anchor_set_id") == anchor_set_id
        ]
        if len(matching) != 1:
            raise ValueError("active anchor set has no unique frozen anchor membership")
        members = matching[0].get("members")
        if not isinstance(members, list) or not members:
            raise ValueError("active anchor set has no frozen anchor membership")
        frozen_members: list[tuple[str, str]] = []
        for member in members:
            if not isinstance(member, Mapping):
                raise TypeError("frozen anchor membership is malformed")
            anchor_id = member.get("anchor_id")
            content_hash = member.get("content_hash")
            if (
                not isinstance(anchor_id, str)
                or not anchor_id
                or any(existing_id == anchor_id for existing_id, _ in frozen_members)
                or not isinstance(content_hash, str)
                or not content_hash.startswith("sha256:")
            ):
                raise ValueError("frozen anchor membership is malformed")
            frozen_members.append((anchor_id, content_hash))
        return tuple(frozen_members)

    @staticmethod
    def _rankings(
        events: Sequence[DomainEvent],
        *,
        run_id: str,
        epoch: TournamentEpoch,
        top_k: int,
        candidate_ids: frozenset[str],
    ) -> tuple[tuple[int, str, tuple[str, ...]], ...]:
        matches = tuple(
            event
            for event in events
            if event.event_type == "MatchEvaluated"
            and event.payload.get("epoch_id") == epoch.epoch_id
        )
        match_by_id = {str(event.payload["match_id"]): event for event in matches}
        ratings_by_match: dict[str, list[DomainEvent]] = {}
        for event in events:
            if event.event_type != "RatingUpdated":
                continue
            if event.payload.get("epoch_id") != epoch.epoch_id:
                raise ValueError("rating update is stale for the active epoch contract")
            match_id = event.payload.get("match_id")
            if not isinstance(match_id, str) or not match_id or match_id not in match_by_id:
                raise ValueError("rating update has no decisive match provenance")
            ratings_by_match.setdefault(match_id, []).append(event)

        policy = get_rating_policy(epoch.rating_policy_version)
        completion_by_sequence: dict[int, str] = {}
        validated_rating_sequences: dict[int, str] = {}
        ratings: dict[str, float] = {}
        snapshots: list[tuple[int, str, tuple[str, ...]]] = []
        for event in events:
            if (
                event.event_type == "TournamentEntryCreated"
                and event.payload.get("epoch_id") == epoch.epoch_id
            ):
                hypothesis_id = event.payload.get("hypothesis_id")
                rating = event.payload.get("rating")
                if not isinstance(hypothesis_id, str) or not isinstance(rating, int | float):
                    raise ValueError("ranking evidence is malformed")
                ratings[hypothesis_id] = float(rating)
            elif (
                event.event_type == "MatchEvaluated"
                and event.payload.get("epoch_id") == epoch.epoch_id
            ):
                source_result_id = event.payload.get("source_result_id")
                if (
                    not isinstance(source_result_id, str)
                    or not source_result_id
                    or event.causation_id != source_result_id
                ):
                    raise ValueError(
                        "match causation provenance does not match its durable source result"
                    )
                if event.correlation_id != run_id:
                    raise ValueError("match correlation provenance does not match its Run")
                match_id = str(event.payload["match_id"])
                try:
                    match = MatchResult(
                        match_id=match_id,
                        epoch_id=epoch.epoch_id,
                        left_id=str(event.payload["left_id"]),
                        right_id=str(event.payload["right_id"]),
                        decision=MatchDecision(str(event.payload["decision"])),
                        winner_id=(
                            str(event.payload["winner_id"])
                            if event.payload.get("winner_id") is not None
                            else None
                        ),
                    )
                except (KeyError, ValueError) as error:
                    raise ValueError("match rating provenance is malformed") from error
                match_ratings = tuple(ratings_by_match.get(match_id, ()))
                if match.decision is not MatchDecision.DECISIVE:
                    if match_ratings:
                        raise ValueError("only a decisive match may have rating updates")
                    continue
                if len(match_ratings) != 2:
                    raise ValueError("decisive match has incomplete rating updates")
                if tuple(item.sequence for item in match_ratings) != (
                    event.sequence + 1,
                    event.sequence + 2,
                ):
                    raise ValueError("decisive match rating provenance is not contiguous")
                if {
                    item.payload.get("hypothesis_id") for item in match_ratings
                } != {match.left_id, match.right_id}:
                    raise ValueError("decisive match rating participants are incomplete")
                try:
                    before_left = ratings[match.left_id]
                    before_right = ratings[match.right_id]
                except KeyError as error:
                    raise ValueError("decisive match rating participant is not admitted") from error
                after_left, after_right = apply_match(
                    before_left,
                    before_right,
                    match,
                    k_factor=policy.k_factor,
                )
                expected_ratings = {
                    match.left_id: (before_left, after_left),
                    match.right_id: (before_right, after_right),
                }
                for rating_event in match_ratings:
                    participant_id = str(rating_event.payload.get("hypothesis_id"))
                    before, after = expected_ratings[participant_id]
                    if (
                        rating_event.payload.get("epoch_id") != epoch.epoch_id
                        or rating_event.payload.get("rating_policy_version") != policy.version
                        or rating_event.payload.get("before_rating") != before
                        or rating_event.payload.get("rating") != after
                        or rating_event.causation_id != event.causation_id
                        or rating_event.correlation_id != event.correlation_id
                    ):
                        raise ValueError("decisive match rating provenance or contract is forged")
                    validated_rating_sequences[rating_event.sequence] = match_id
                completion_sequence = match_ratings[-1].sequence
                if completion_sequence in completion_by_sequence:
                    raise ValueError("match applications have ambiguous completion sequence")
                completion_by_sequence[completion_sequence] = match_id
            elif event.event_type == "RatingUpdated":
                if event.sequence not in validated_rating_sequences:
                    raise ValueError("rating update has no validated decisive match provenance")
                hypothesis_id = event.payload.get("hypothesis_id")
                rating = event.payload.get("rating")
                if not isinstance(hypothesis_id, str) or not isinstance(rating, int | float):
                    raise ValueError("ranking evidence is malformed")
                ratings[hypothesis_id] = float(rating)
            completed_match_id = completion_by_sequence.get(event.sequence)
            if completed_match_id is not None:
                ranked = tuple(
                    sorted(
                        candidate_ids.intersection(ratings),
                        key=lambda item: (-ratings[item], item),
                    )[:top_k]
                )
                snapshots.append((event.sequence, completed_match_id, ranked))
        return tuple(snapshots)

    def _build(
        self,
        *,
        run_id: str,
        source_sequence: int,
        stop_cause: Literal["scientist_stop"] | None = None,
    ) -> ConvergenceCheckpoint:
        allow_incomplete = stop_cause == "scientist_stop"
        events = tuple(
            event for event in self.uow.load(run_id) if event.sequence <= source_sequence
        )
        if not events or events[-1].sequence != source_sequence:
            raise ValueError("checkpoint source sequence is missing or stale")
        if not allow_incomplete and any(
            event.event_type == "ConvergenceCheckpointRecorded" for event in events
        ):
            raise ValueError("checkpoint source sequence must precede checkpoint recording")
        manifest = self.uow.run_manifest(run_id)
        stop = self._stop_policy(manifest)
        minimum_matches = _required_non_negative(stop, "minimum_matches")
        minimum_hypotheses = _required_non_negative(stop, "minimum_hypotheses")
        minimum_model_calls = _required_non_negative(stop, "minimum_model_calls")
        top_k = _required_positive(stop, "top_k")
        top_k_window = _required_positive(stop, "top_k_stability_window")
        cluster_window = _required_positive(stop, "cluster_diversity_window")
        elo_window = _required_positive(stop, "elo_plateau_window")
        epoch, epoch_sequence = self._active_epoch(events)
        if epoch.anchor_set_id is None:
            raise ValueError("active epoch has no frozen anchor set")
        frozen_anchor_members = self._anchor_members(manifest, epoch.anchor_set_id)
        anchor_members = tuple(anchor_id for anchor_id, _ in frozen_anchor_members)
        anchor_hash_by_id = dict(frozen_anchor_members)

        epoch_events = tuple(event for event in events if event.sequence >= epoch_sequence)
        hypothesis_ids = {
            str(event.payload["hypothesis_id"])
            for event in epoch_events
            if event.event_type == "HypothesisContentCreated"
            and event.payload.get("research_plan_version") == epoch.research_plan_version
            and isinstance(event.payload.get("hypothesis_id"), str)
        }
        matches = tuple(
            event
            for event in epoch_events
            if event.event_type == "MatchEvaluated"
            and event.payload.get("epoch_id") == epoch.epoch_id
        )
        contract = (
            epoch.research_plan_version,
            epoch.evaluation_rules_hash,
            epoch.ranking_prompt_hash,
            epoch.judge_profile_hash,
            epoch.rating_policy_version,
            epoch.admission_policy_version,
        )
        match_ids: set[str] = set()
        for match in matches:
            actual = (
                match.payload.get("research_plan_version"),
                match.payload.get("evaluation_rules_hash"),
                match.payload.get("ranking_prompt_hash"),
                match.payload.get("judge_profile_hash"),
                match.payload.get("rating_policy_version"),
                match.payload.get("admission_policy_version"),
            )
            if actual != contract:
                raise ValueError("match evidence is stale for active epoch contract")
            match_id = match.payload.get("match_id")
            if not isinstance(match_id, str) or not match_id:
                raise ValueError("anchor comparison has no durable comparison ID")
            if match_id in match_ids:
                raise ValueError("comparison identity is not unique")
            match_ids.add(match_id)
        if not allow_incomplete and len(matches) < minimum_matches:
            raise ValueError("checkpoint has insufficient minimum coverage")

        rankings = self._rankings(
            epoch_events,
            run_id=run_id,
            epoch=epoch,
            top_k=top_k,
            candidate_ids=frozenset(hypothesis_ids),
        )
        if not allow_incomplete and len(rankings) < top_k_window:
            raise ValueError("checkpoint has insufficient top-k stability window")
        recent_rankings = rankings[-top_k_window:]
        top_k_ids = recent_rankings[-1][2] if recent_rankings else ()
        if not allow_incomplete and len(top_k_ids) != top_k:
            raise ValueError("checkpoint top-k membership is incomplete")
        top_k_stable = len(recent_rankings) == top_k_window and all(
            snapshot == top_k_ids for _, _, snapshot in recent_rankings
        )

        comparison_by_anchor: dict[str, tuple[str, str]] = {}
        for match in matches:
            left_id = match.payload.get("left_id")
            right_id = match.payload.get("right_id")
            participants = (left_id, right_id)
            matched_anchors = tuple(
                anchor_id for anchor_id in anchor_members if anchor_id in participants
            )
            if not matched_anchors:
                continue
            if len(matched_anchors) != 1:
                raise ValueError("fixed anchor comparison has ambiguous anchor membership")
            anchor_id = matched_anchors[0]
            candidate_id = right_id if left_id == anchor_id else left_id
            anchor_hash = (
                match.payload.get("left_content_hash")
                if left_id == anchor_id
                else match.payload.get("right_content_hash")
            )
            if (
                match.payload.get("comparison_kind") != "fixed_anchor"
                or match.payload.get("anchor_set_id") != epoch.anchor_set_id
                or anchor_hash != anchor_hash_by_id[anchor_id]
            ):
                raise ValueError("fixed anchor comparison provenance is invalid")
            if not isinstance(candidate_id, str):
                raise TypeError("fixed anchor comparison candidate is malformed")
            if candidate_id not in top_k_ids:
                if allow_incomplete:
                    continue
                raise ValueError("anchor comparison candidate is not in the stable top-k cohort")
            if anchor_id in comparison_by_anchor:
                raise ValueError("anchor has ambiguous fixed comparison identity")
            comparison_by_anchor[anchor_id] = (str(match.payload["match_id"]), candidate_id)
        if not allow_incomplete and set(comparison_by_anchor) != set(anchor_members):
            raise ValueError("checkpoint is missing fixed anchor comparison IDs")

        cluster_events = tuple(
            event
            for event in epoch_events
            if event.event_type == "ProximityAssessed"
            and event.payload.get("epoch_id") == epoch.epoch_id
            and event.payload.get("research_plan_version") == epoch.research_plan_version
            and isinstance(event.payload.get("cluster_suggestion"), str)
            and event.payload.get("cluster_suggestion")
            and isinstance(event.payload.get("left_id"), str)
            and isinstance(event.payload.get("right_id"), str)
            and {
                str(event.payload["left_id"]),
                str(event.payload["right_id"]),
            }.issubset(set(top_k_ids))
        )
        if not allow_incomplete and len(cluster_events) < cluster_window:
            raise ValueError("checkpoint has no complete cluster diversity snapshot")
        recent_clusters = cluster_events[-cluster_window:]
        cluster_membership_ids = tuple(
            str(event.payload.get("edge_id"))
            for event in recent_clusters
            if isinstance(event.payload.get("edge_id"), str)
            and event.payload.get("edge_id")
        )
        if len(cluster_membership_ids) != len(recent_clusters):
            raise ValueError("checkpoint has malformed cluster membership IDs")
        cluster_ids = tuple(
            sorted({str(event.payload["cluster_suggestion"]) for event in recent_clusters})
        )
        cluster_cohort_ids = tuple(
            sorted(
                {
                    str(event.payload[side])
                    for event in recent_clusters
                    for side in ("left_id", "right_id")
                }
            )
        )
        if not allow_incomplete and set(cluster_cohort_ids) != set(top_k_ids):
            raise ValueError("cluster window is not bound to the stable top-k cohort")
        cluster_diversity = (
            len(recent_clusters) == cluster_window
            and set(cluster_cohort_ids) == set(top_k_ids)
            and len(cluster_ids) >= min(2, top_k)
        )

        novelty_events = tuple(
            event
            for event in epoch_events
            if event.event_type == "NoveltyAssessmentRecorded"
            and event.payload.get("epoch_id") == epoch.epoch_id
            and event.payload.get("research_plan_version") == epoch.research_plan_version
            and event.payload.get("hypothesis_id") in top_k_ids
        )
        if not allow_incomplete and len(novelty_events) < cluster_window:
            raise ValueError("checkpoint has no complete novelty plateau window")
        recent_novelty = novelty_events[-cluster_window:]
        novelty_assessment_ids = tuple(
            str(event.payload.get("assessment_id"))
            for event in recent_novelty
            if isinstance(event.payload.get("assessment_id"), str)
            and event.payload.get("assessment_id")
        )
        novelty_cohort_ids = tuple(
            sorted({str(event.payload["hypothesis_id"]) for event in recent_novelty})
        )
        if not allow_incomplete and (
            len(novelty_assessment_ids) != cluster_window
            or len(set(novelty_assessment_ids)) != cluster_window
            or set(novelty_cohort_ids) != set(top_k_ids)
        ):
            raise ValueError("novelty window is not bound to the stable top-k cohort")
        novelty_plateau = (
            len(recent_novelty) == cluster_window
            and len(set(novelty_assessment_ids)) == cluster_window
            and set(novelty_cohort_ids) == set(top_k_ids)
            and all(event.payload.get("verdict") != "novel" for event in recent_novelty)
        )
        budget = self.uow.load_checkpoint_budget_snapshot(run_id)
        if not allow_incomplete and budget.settled.model_calls < minimum_model_calls:
            raise ValueError("checkpoint has insufficient minimum model calls")
        if not allow_incomplete and len(hypothesis_ids) < minimum_hypotheses:
            raise ValueError("checkpoint has insufficient minimum hypotheses")

        rating_events = tuple(
            event
            for event in epoch_events
            if event.event_type == "RatingUpdated"
            and event.payload.get("epoch_id") == epoch.epoch_id
        )
        recent_ratings = rating_events[-elo_window:]
        elo_plateau = len(recent_ratings) == elo_window and all(
            event.payload.get("before_rating") == event.payload.get("rating")
            for event in recent_ratings
        )
        policy_document = {
            "stop": dict(stop),
            "epoch": epoch.model_dump(mode="json"),
        }
        evidence_sequences = tuple(event.sequence for event in epoch_events)
        data = {
            "run_id": run_id,
            "source_sequence": source_sequence,
            "stop_cause": stop_cause,
            "policy_version": _identity(policy_document),
            **epoch.model_dump(mode="json"),
            "anchor_set_id": epoch.anchor_set_id,
            "anchor_member_ids": anchor_members,
            "anchor_member_content_hashes": tuple(
                content_hash for _, content_hash in frozen_anchor_members
            ),
            "anchor_comparison_ids": tuple(
                comparison_by_anchor[anchor_id][0]
                for anchor_id in anchor_members
                if anchor_id in comparison_by_anchor
            ),
            "anchor_comparison_candidate_ids": tuple(
                comparison_by_anchor[anchor_id][1]
                for anchor_id in anchor_members
                if anchor_id in comparison_by_anchor
            ),
            "top_k": top_k,
            "top_k_stability_window": top_k_window,
            "top_k_ids": top_k_ids,
            "top_k_window_match_ids": tuple(
                match_id for _, match_id, _ in recent_rankings
            ),
            "top_k_window_sequences": tuple(
                sequence for sequence, _, _ in recent_rankings
            ),
            "top_k_stable": top_k_stable,
            "cluster_ids": cluster_ids,
            "cluster_membership_ids": cluster_membership_ids,
            "cluster_cohort_ids": cluster_cohort_ids,
            "cluster_diversity_window": cluster_window,
            "cluster_window_sequences": tuple(event.sequence for event in recent_clusters),
            "cluster_diversity_satisfied": cluster_diversity,
            "novelty_window_sequences": tuple(event.sequence for event in recent_novelty),
            "novelty_assessment_ids": novelty_assessment_ids,
            "novelty_cohort_ids": novelty_cohort_ids,
            "novelty_plateau": novelty_plateau,
            "minimum_hypotheses": minimum_hypotheses,
            "hypothesis_count": len(hypothesis_ids),
            "minimum_model_calls": minimum_model_calls,
            "model_call_count": budget.settled.model_calls,
            "minimum_matches": minimum_matches,
            "match_count": len(matches),
            "minimum_coverage": len(anchor_members),
            "coverage_count": len(comparison_by_anchor),
            "elo_plateau_window": elo_window,
            "elo_window_sequences": tuple(event.sequence for event in recent_ratings),
            "elo_plateau": elo_plateau,
            "budget_snapshot": budget.model_dump(mode="json"),
            "unresolved_task_ids": self.uow.unresolved_task_ids(
                run_id, exclude_intent="finalize_run"
            ),
            "evidence_source_sequences": evidence_sequences,
        }
        checkpoint_id = _identity(data)
        return ConvergenceCheckpoint(checkpoint_id=checkpoint_id, **data)

    def build_and_record(
        self, *, run_id: str, expected_sequence: int
    ) -> RecordedCheckpoint:
        checkpoint = self._build(run_id=run_id, source_sequence=expected_sequence)
        commit = self.uow.commit_domain_batch(
            run_id=run_id,
            expected_sequence=expected_sequence,
            events=(
                NewEvent(
                    event_type="ConvergenceCheckpointRecorded",
                    payload=checkpoint.model_dump(mode="json"),
                ),
            ),
            idempotency_key=f"checkpoint:{checkpoint.checkpoint_id}",
        )
        return RecordedCheckpoint(
            checkpoint_id=checkpoint.checkpoint_id,
            source_sequence=checkpoint.source_sequence,
            commit=commit,
        )

    def _build_and_record_scientist_stop(
        self, *, run_id: str, expected_sequence: int
    ) -> RecordedCheckpoint:
        checkpoint = self._build(
            run_id=run_id,
            source_sequence=expected_sequence,
            stop_cause="scientist_stop",
        )
        commit = self.uow.commit_domain_batch(
            run_id=run_id,
            expected_sequence=expected_sequence,
            events=(
                NewEvent(
                    event_type="ConvergenceCheckpointRecorded",
                    payload=checkpoint.model_dump(mode="json"),
                ),
            ),
            idempotency_key=f"checkpoint:{checkpoint.checkpoint_id}",
        )
        return RecordedCheckpoint(
            checkpoint_id=checkpoint.checkpoint_id,
            source_sequence=checkpoint.source_sequence,
            commit=commit,
        )

    def load_recorded(
        self, *, run_id: str, checkpoint_id: str, expected_sequence: int
    ) -> ConvergenceCheckpoint:
        events = self.uow.load(run_id)
        if not events or events[-1].sequence != expected_sequence:
            raise ValueError("stale checkpoint: expected sequence is not the durable tip")
        recorded = [
            event
            for event in events
            if event.event_type == "ConvergenceCheckpointRecorded"
            and event.payload.get("checkpoint_id") == checkpoint_id
        ]
        if len(recorded) != 1:
            raise ValueError("checkpoint ID has no unique durable record")
        event = recorded[0]
        suffix = tuple(item for item in events if item.sequence > event.sequence)
        resumable_types = {
            "StopSignalObserved",
            "StopPolicyTriggered",
            "RunStopping",
            "FinalizationRequested",
            "TaskEnqueued",
            "TaskLeaseClaimed",
            "BudgetReserved",
            "TaskLeaseAdopted",
            "BudgetReleased",
            "FinalizationCompleted",
            "RunCompleted",
            "RunCompletedPartial",
            "RunCancelled",
        }
        if any(item.event_type not in resumable_types for item in suffix):
            raise ValueError("stale checkpoint: newer persisted evidence exists")
        checkpoint = ConvergenceCheckpoint.model_validate(event.payload)
        if checkpoint.run_id != run_id or checkpoint.source_sequence + 1 != event.sequence:
            raise ValueError("checkpoint source binding is forged or stale")
        rebuilt = self._build(
            run_id=run_id,
            source_sequence=checkpoint.source_sequence,
            stop_cause=checkpoint.stop_cause,
        )
        if rebuilt != checkpoint:
            raise ValueError("checkpoint contains forged or stale evidence")
        return checkpoint
