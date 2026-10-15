"""Versioned, ledger-derived Research v2 pairwise preference estimates.

These estimates prioritize comparisons; they are not probabilities of scientific truth.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from hashlib import sha256
from math import isfinite
from typing import Any, Literal

import trueskill
from pydantic import BaseModel, ConfigDict, Field, model_validator

from co_scientist.events.models import DomainEvent


class TrueSkillConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal["trueskill_v1"] = "trueskill_v1"
    mu0: float = Field(default=25.0, allow_inf_nan=False)
    sigma0: float = Field(default=25.0 / 3.0, gt=0, allow_inf_nan=False)
    beta: float = Field(default=25.0 / 6.0, gt=0, allow_inf_nan=False)
    tau: float = Field(default=25.0 / 300.0, ge=0, allow_inf_nan=False)
    draw_probability: Literal[0.0] = 0.0

    def environment(self) -> trueskill.TrueSkill:
        # Explicit instance: never mutate or depend on trueskill's global setup().
        return trueskill.TrueSkill(mu=self.mu0, sigma=self.sigma0, beta=self.beta,
                                   tau=self.tau, draw_probability=0.0)


class UCBPairingPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal["ucb_pairing_v1"] = "ucb_pairing_v1"
    kappa: float = Field(default=1.0, ge=0, le=10, allow_inf_nan=False)
    max_matches_per_candidate: int = Field(default=8, ge=1, le=100, strict=True)
    max_matches_per_pair: int = Field(default=3, ge=1, le=20, strict=True)
    max_tiebreakers_per_pair: int = Field(default=1, ge=0, le=10, strict=True)

    @model_validator(mode="after")
    def check_caps(self) -> UCBPairingPolicy:
        if self.max_tiebreakers_per_pair > self.max_matches_per_pair:
            raise ValueError("tiebreaker cap cannot exceed pair cap")
        return self


class CandidateRating(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    hypothesis_id: str
    epoch_id: str
    mu: float
    sigma: float
    decisive_matches: int = 0
    total_match_attempts: int = 0
    policy_version: Literal["trueskill_v1"] = "trueskill_v1"
    updated_from_match_id: str | None = None


class PairProposal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    left_id: str
    right_id: str
    epoch_id: str
    comparison_kind: Literal["opportunistic", "tiebreaker"]
    selection_policy_version: Literal["ucb_pairing_v1"] = "ucb_pairing_v1"
    reason: dict[str, Any]


class BaselinePairProposal(BaseModel):
    """A frozen logical opportunity; not a scientific outcome or rating update."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    version: Literal["2608-balanced-pairing-v1"] = "2608-balanced-pairing-v1"
    epoch_id: str
    focal_id: str
    opponent_id: str
    left_id: str
    right_id: str
    pair_attempt_index: int
    eligible_ids: tuple[str, ...]
    seed: str


def baseline_priority(seed: str, label: str, candidate_id: str) -> str:
    """Stable, independent priorities; no rating or scientific-quality input."""
    return sha256(f"2608-balanced-pairing-v1:{seed}:{label}:{candidate_id}".encode()).hexdigest()


def select_baseline_pair(
    ratings: Mapping[str, CandidateRating], events: Sequence[DomainEvent], *,
    epoch_id: str, seed: str,
) -> tuple[BaselinePairProposal | None, str]:
    """Spec §6.2: R in, quota-aware balanced opportunity out (never UCB)."""
    eligible = {key: value for key, value in ratings.items() if value.epoch_id == epoch_id}
    if any(key != value.hypothesis_id for key, value in eligible.items()):
        raise ValueError("rating identity mismatch")
    focal_attempts: Counter[str] = Counter()
    pair_attempts: Counter[tuple[str, str]] = Counter()
    seen: set[str] = set()
    for event in events:
        if event.event_type != "MatchPairReserved" or event.payload.get("epoch_id") != epoch_id:
            continue
        payload = event.payload
        match_id = str(payload["match_id"])
        if match_id in seen:
            raise ValueError("duplicate baseline match opportunity")
        seen.add(match_id)
        left, right, focal = (str(payload[key]) for key in ("left_id", "right_id", "focal_id"))
        if left == right or focal not in {left, right}:
            raise ValueError("invalid baseline focal identity")
        focal_attempts[focal] += 1
        pair_attempts[(min(left, right), max(left, right))] += 1
    below_quota = [key for key, value in eligible.items() if value.decisive_matches < 2]
    if not below_quota:
        return None, "EVALUATION_COMPLETE"
    # An exhausted required candidate is incomplete, not a discarded survivor.
    if any(focal_attempts[key] >= 6 for key in below_quota):
        return None, "EVALUATION_INCOMPLETE"
    if len(eligible) < 2:
        return None, "NO_COMPARABLE_PAIR"
    focal = min(below_quota, key=lambda key: (
        eligible[key].decisive_matches, focal_attempts[key],
        baseline_priority(seed, "focal", key), key))
    opponent = min((key for key in eligible if key != focal), key=lambda key: (
        pair_attempts[(min(focal, key), max(focal, key))], eligible[key].decisive_matches,
        baseline_priority(seed, "opponent", key), key))
    pair = (min(focal, opponent), max(focal, opponent))
    initial = int(baseline_priority(seed, "orientation", ":".join(pair)), 16) % 2
    orientation = (initial + pair_attempts[pair]) % 2
    left, right = pair if orientation == 0 else pair[::-1]
    return BaselinePairProposal(
        epoch_id=epoch_id, focal_id=focal, opponent_id=opponent,
        left_id=left, right_id=right, pair_attempt_index=pair_attempts[pair],
        eligible_ids=tuple(sorted(eligible)), seed=seed,
    ), "MATCH_REQUIRED"


def replay_bayesian_rating(
    events: Sequence[DomainEvent], *, epoch_id: str, policy: TrueSkillConfig,
) -> dict[str, CandidateRating]:
    """Rebuild ratings from admitted entries and ordered immutable match outcomes."""

    env = policy.environment()
    ratings: dict[str, CandidateRating] = {}
    seen_matches: set[str] = set()
    reservations: dict[str, tuple[str, str]] = {}
    for event in events:
        payload = event.payload
        if payload.get("epoch_id") != epoch_id:
            continue
        if event.event_type == "TournamentEntryCreated":
            candidate_id = str(payload["hypothesis_id"])
            if candidate_id in ratings:
                raise ValueError("duplicate Bayesian tournament entry")
            ratings[candidate_id] = CandidateRating(
                hypothesis_id=candidate_id, epoch_id=epoch_id,
                mu=policy.mu0, sigma=policy.sigma0,
            )
        elif event.event_type == "MatchPairReserved":
            match_id = str(payload["match_id"])
            if match_id in reservations:
                raise ValueError("duplicate Bayesian match reservation")
            reservations[match_id] = (str(payload["left_id"]), str(payload["right_id"]))
            for candidate_id in (str(payload["left_id"]), str(payload["right_id"])):
                if candidate_id not in ratings:
                    raise ValueError("attempt references unadmitted candidate")
                old = ratings[candidate_id]
                ratings[candidate_id] = old.model_copy(update={
                    "total_match_attempts": old.total_match_attempts + 1,
                })
        elif event.event_type == "MatchEvaluated":
            match_id = str(payload["match_id"])
            if match_id in seen_matches:
                raise ValueError("duplicate match in Bayesian ledger")
            seen_matches.add(match_id)
            if reservations.get(match_id) != (str(payload["left_id"]),
                                              str(payload["right_id"])):
                raise ValueError("Bayesian outcome has no matching attempted pair")
            if payload["decision"] != "decisive":
                continue
            left_id, right_id = str(payload["left_id"]), str(payload["right_id"])
            if left_id not in ratings or right_id not in ratings:
                raise ValueError("match references unadmitted candidate")
            winner = str(payload["winner_id"])
            if winner not in {left_id, right_id}:
                raise ValueError("decisive match has invalid winner")
            left, right = ratings[left_id], ratings[right_id]
            updated = env.rate(
                [(env.create_rating(left.mu, left.sigma),),
                 (env.create_rating(right.mu, right.sigma),)],
                ranks=[0, 1] if winner == left_id else [1, 0],
            )
            for candidate_id, value in ((left_id, updated[0][0]),
                                        (right_id, updated[1][0])):
                before = ratings[candidate_id]
                if not isfinite(value.mu) or not isfinite(value.sigma):
                    raise ValueError("non-finite Bayesian rating")
                ratings[candidate_id] = before.model_copy(update={
                    "mu": value.mu, "sigma": value.sigma,
                    "decisive_matches": before.decisive_matches + 1,
                    "updated_from_match_id": match_id,
                })
    return ratings


def select_ucb_pair(
    ratings: Mapping[str, CandidateRating], events: Sequence[DomainEvent], *,
    epoch_id: str, policy: UCBPairingPolicy,
    context_hashes: Mapping[str, str], clusters: Mapping[str, str] | None = None,
) -> tuple[PairProposal | None, str]:
    """Coverage first, UCB next, then informative/diverse bounded opponent selection."""

    clusters = clusters or {}
    attempts: Counter[str] = Counter()
    pair_attempts: Counter[tuple[str, str]] = Counter()
    orientation: Counter[tuple[str, str]] = Counter()
    gaps: dict[tuple[str, str], tuple[str, str]] = {}
    tiebreakers: Counter[tuple[str, str]] = Counter()
    for event in events:
        if event.payload.get("epoch_id") != epoch_id:
            continue
        p = event.payload
        if event.event_type == "MatchPairReserved":
            left, right = str(p["left_id"]), str(p["right_id"])
            pair = tuple(sorted((left, right)))
            attempts.update((left, right))
            pair_attempts[pair] += 1
            orientation[(left, right)] += 1
            if p.get("comparison_kind") == "tiebreaker":
                tiebreakers[pair] += 1
        elif event.event_type == "EvidenceGapRecorded":
            left, right = str(p["left_id"]), str(p["right_id"])
            pair = tuple(sorted((left, right)))
            hashes = {left: str(p["left_context_hash"]),
                      right: str(p["right_context_hash"])}
            gaps[pair] = (hashes[pair[0]], hashes[pair[1]])
    eligible = {key: rating for key, rating in ratings.items()
                if rating.epoch_id == epoch_id
                and attempts[key] < policy.max_matches_per_candidate
                and key in context_hashes}
    possibilities = []
    for left in sorted(eligible):
        for right in sorted(eligible):
            if left >= right:
                continue
            pair = (left, right)
            if pair_attempts[pair] >= policy.max_matches_per_pair:
                continue
            gap = gaps.get(pair)
            context_changed = gap is not None and gap != (
                context_hashes[left], context_hashes[right])
            if gap is not None and (not context_changed
                                    or tiebreakers[pair] >= policy.max_tiebreakers_per_pair):
                continue
            possibilities.append((left, right, bool(gap)))
    if not possibilities:
        return None, "no_eligible_pair_under_match_caps"
    eligible_pair_count = len(possibilities)
    min_coverage = min(max(attempts[left], attempts[right]) for left, right, _ in possibilities)
    possibilities = [item for item in possibilities
                     if max(attempts[item[0]], attempts[item[1]]) == min_coverage]

    def ucb(key: str) -> float:
        return eligible[key].mu + policy.kappa * eligible[key].sigma

    def key(item: tuple[str, str, bool]) -> tuple[Any, ...]:
        left, right, _ = item
        pair = (left, right)
        diversity = int(bool(clusters.get(left) and clusters.get(right)
                             and clusters[left] != clusters[right]))
        information = (eligible[left].sigma**2 + eligible[right].sigma**2) / (
            1.0 + abs(eligible[left].mu - eligible[right].mu))
        return (max(ucb(left), ucb(right)), information, diversity,
                -pair_attempts[pair], -abs(orientation[(left, right)]
                                           - orientation[(right, left)]), left, right)

    left, right, tiebreaker = max(possibilities, key=key)
    alternatives = [
        {"pair": [a, b], "coverage": max(attempts[a], attempts[b]),
         "max_ucb": max(ucb(a), ucb(b)),
         "pair_attempts": pair_attempts[(a, b)]}
        for a, b, _ in sorted(possibilities)
    ]
    if orientation[(left, right)] > orientation[(right, left)]:
        left, right = right, left
    pair = tuple(sorted((left, right)))
    proposal = PairProposal(
        left_id=left, right_id=right, epoch_id=epoch_id,
        comparison_kind="tiebreaker" if tiebreaker else "opportunistic",
        reason={
            "coverage_priority": min_coverage,
            "eligible_pair_count": eligible_pair_count,
            "coverage_tier_alternatives": alternatives,
            "candidate_attempts": {left: attempts[left], right: attempts[right]},
            "candidate_ucb": {left: ucb(left), right: ucb(right)},
            "pair_attempts": pair_attempts[pair],
            "information_value": (eligible[left].sigma**2 + eligible[right].sigma**2)
                                 / (1.0 + abs(eligible[left].mu - eligible[right].mu)),
            "mechanistic_diversity": bool(clusters.get(left) and clusters.get(right)
                                           and clusters[left] != clusters[right]),
            "left_right_balance": orientation[(left, right)] - orientation[(right, left)],
            "evidence_gap_reopened": tiebreaker,
        },
    )
    return proposal, "selected_coverage_then_ucb_then_information"
