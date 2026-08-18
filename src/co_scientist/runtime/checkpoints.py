"""Construction and validation of durable convergence checkpoints."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict

from co_scientist.adapters.persistence.sqlite import CommitResult, SqliteUnitOfWork
from co_scientist.domain.convergence import ConvergenceCheckpoint
from co_scientist.domain.tournament import TournamentEpoch
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
        events: Sequence[DomainEvent], *, epoch_id: str, top_k: int
    ) -> tuple[tuple[int, tuple[str, ...]], ...]:
        ratings: dict[str, float] = {}
        snapshots: list[tuple[int, tuple[str, ...]]] = []
        for event in events:
            if event.payload.get("epoch_id") != epoch_id:
                continue
            if event.event_type in {"TournamentEntryCreated", "RatingUpdated"}:
                hypothesis_id = event.payload.get("hypothesis_id")
                rating = event.payload.get("rating")
                if not isinstance(hypothesis_id, str) or not isinstance(rating, int | float):
                    raise ValueError("ranking evidence is malformed")
                ratings[hypothesis_id] = float(rating)
            elif event.event_type == "MatchEvaluated":
                ranked = tuple(
                    sorted(ratings, key=lambda item: (-ratings[item], item))[:top_k]
                )
                snapshots.append((event.sequence, ranked))
        return tuple(snapshots)

    def _build(self, *, run_id: str, source_sequence: int) -> ConvergenceCheckpoint:
        events = tuple(
            event for event in self.uow.load(run_id) if event.sequence <= source_sequence
        )
        if not events or events[-1].sequence != source_sequence:
            raise ValueError("checkpoint source sequence is missing or stale")
        if any(event.event_type == "ConvergenceCheckpointRecorded" for event in events):
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

        epoch_events = tuple(event for event in events if event.sequence >= epoch_sequence)
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
        comparison_by_anchor: dict[str, str] = {}
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
            participants = {match.payload.get("left_id"), match.payload.get("right_id")}
            for anchor_id in anchor_members:
                if anchor_id in participants:
                    comparison_by_anchor[anchor_id] = match_id
        if set(comparison_by_anchor) != set(anchor_members):
            raise ValueError("checkpoint is missing fixed anchor comparison IDs")
        if len(matches) < minimum_matches:
            raise ValueError("checkpoint has insufficient minimum coverage")

        rankings = self._rankings(epoch_events, epoch_id=epoch.epoch_id, top_k=top_k)
        if len(rankings) < top_k_window:
            raise ValueError("checkpoint has insufficient top-k stability window")
        recent_rankings = rankings[-top_k_window:]
        top_k_ids = recent_rankings[-1][1]
        if len(top_k_ids) != top_k:
            raise ValueError("checkpoint top-k membership is incomplete")
        top_k_stable = all(snapshot == top_k_ids for _, snapshot in recent_rankings)

        cluster_events = tuple(
            event
            for event in epoch_events
            if event.event_type == "ProximityAssessed"
            and isinstance(event.payload.get("cluster_suggestion"), str)
            and event.payload.get("cluster_suggestion")
        )
        if len(cluster_events) < cluster_window:
            raise ValueError("checkpoint has no complete cluster diversity snapshot")
        recent_clusters = cluster_events[-cluster_window:]
        cluster_membership_ids = tuple(
            str(event.payload.get("edge_id"))
            for event in recent_clusters
            if isinstance(event.payload.get("edge_id"), str)
            and event.payload.get("edge_id")
        )
        if len(cluster_membership_ids) != cluster_window:
            raise ValueError("checkpoint has malformed cluster membership IDs")
        cluster_ids = tuple(
            sorted({str(event.payload["cluster_suggestion"]) for event in recent_clusters})
        )
        cluster_diversity = len(cluster_ids) >= min(2, top_k)

        novelty_events = tuple(
            event
            for event in epoch_events
            if event.event_type == "NoveltyAssessmentRecorded"
        )
        if len(novelty_events) < cluster_window:
            raise ValueError("checkpoint has no complete novelty plateau window")
        recent_novelty = novelty_events[-cluster_window:]
        novelty_plateau = all(event.payload.get("verdict") != "novel" for event in recent_novelty)

        hypothesis_ids = {
            str(event.payload["hypothesis_id"])
            for event in epoch_events
            if event.event_type == "HypothesisContentCreated"
            and event.payload.get("research_plan_version") == epoch.research_plan_version
            and isinstance(event.payload.get("hypothesis_id"), str)
        }
        budget = self.uow.load_checkpoint_budget_snapshot(run_id)
        if budget.settled.model_calls < minimum_model_calls:
            raise ValueError("checkpoint has insufficient minimum model calls")
        if len(hypothesis_ids) < minimum_hypotheses:
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
            "policy_version": _identity(policy_document),
            **epoch.model_dump(mode="json"),
            "anchor_set_id": epoch.anchor_set_id,
            "anchor_member_ids": anchor_members,
            "anchor_member_content_hashes": tuple(
                content_hash for _, content_hash in frozen_anchor_members
            ),
            "anchor_comparison_ids": tuple(
                comparison_by_anchor[anchor_id] for anchor_id in anchor_members
            ),
            "top_k": top_k,
            "top_k_stability_window": top_k_window,
            "top_k_ids": top_k_ids,
            "top_k_window_sequences": tuple(sequence for sequence, _ in recent_rankings),
            "top_k_stable": top_k_stable,
            "cluster_ids": cluster_ids,
            "cluster_membership_ids": cluster_membership_ids,
            "cluster_diversity_window": cluster_window,
            "cluster_window_sequences": tuple(event.sequence for event in recent_clusters),
            "cluster_diversity_satisfied": cluster_diversity,
            "novelty_window_sequences": tuple(event.sequence for event in recent_novelty),
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
        }
        if any(item.event_type not in resumable_types for item in suffix):
            raise ValueError("stale checkpoint: newer persisted evidence exists")
        checkpoint = ConvergenceCheckpoint.model_validate(event.payload)
        if checkpoint.run_id != run_id or checkpoint.source_sequence + 1 != event.sequence:
            raise ValueError("checkpoint source binding is forged or stale")
        rebuilt = self._build(run_id=run_id, source_sequence=checkpoint.source_sequence)
        if rebuilt != checkpoint:
            raise ValueError("checkpoint contains forged or stale evidence")
        return checkpoint
