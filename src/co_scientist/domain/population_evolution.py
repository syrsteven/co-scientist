"""Frozen, event-projectable population search policy (not scientific truth)."""

from __future__ import annotations

import hashlib
import random
from collections.abc import Mapping, Sequence
from math import isfinite
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from co_scientist.domain.bayesian_ranking import CandidateRating

MutationStrategy = Literal["simplify", "feasibility", "out_of_box", "targeted_revision"]
Operator = Literal["crossover", "mutation"]


class BaselineSearchPolicy(BaseModel):
    """Independent opt-in contract. Never rewrites population_evolution_v1."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    version: Literal["2608-ideation-search-v1"] = "2608-ideation-search-v1"
    root_slots: Literal[4] = 4
    reproduction_slots_per_transition: Literal[2] = 2
    reproduction_transitions: Literal[10] = 10
    tournament_k: Literal[2] = 2
    ucb_kappa: float = Field(default=1.0, strict=True, allow_inf_nan=False)
    crossover_probability: float = 0.7
    mutation_probability: float = 0.3
    min_valid_decisive: Literal[2] = 2
    max_focal_attempts: Literal[6] = 6
    sampling_version: Literal["python-mt19937-sha256-v1"] = "python-mt19937-sha256-v1"

    @model_validator(mode="after")
    def frozen_probabilities(self) -> BaselineSearchPolicy:
        if (self.crossover_probability != 0.7 or self.mutation_probability != 0.3
                or self.ucb_kappa != 1.0):
            raise ValueError("baseline operator probabilities are frozen at 0.7/0.3")
        return self


class BaselineParentDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    version: Literal["2608-ucb-tournament-v1"] = "2608-ucb-tournament-v1"
    generation: int
    slot: int
    epoch_id: str
    seed: str
    operator_draw: float
    operator: Operator
    eligible_parent_ids: tuple[str, ...]
    contestant_draws: tuple[tuple[str, ...], ...]
    parent_ids: tuple[str, ...]
    state: Literal["SELECTED", "NO_ELIGIBLE_PARENTS", "SKIPPED_INSUFFICIENT_DISTINCT_PARENTS"]


class ShortSearchPolicy(BaseModel):
    """G3 diagnostic revision; the G10 baseline reader remains unchanged."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    version: Literal["2608-ideation-search-g3-v1"] = "2608-ideation-search-g3-v1"
    root_slots: Literal[4] = 4
    reproduction_slots_per_transition: Literal[2] = 2
    reproduction_transitions: Literal[3] = 3
    tournament_k: Literal[2] = 2
    ucb_kappa: float = Field(default=1.0, strict=True, allow_inf_nan=False)
    crossover_probability: float = 0.7
    mutation_probability: float = 0.3
    min_valid_decisive: Literal[2] = 2
    max_focal_attempts: Literal[6] = 6
    sampling_version: Literal["python-mt19937-sha256-v1"] = "python-mt19937-sha256-v1"

    @model_validator(mode="after")
    def unchanged_selection(self) -> ShortSearchPolicy:
        if (self.crossover_probability != 0.7 or self.mutation_probability != 0.3
                or self.ucb_kappa != 1.0):
            raise ValueError("short cycle retains frozen operator and UCB parameters")
        return self


def read_search_policy(document: Mapping[str, Any]) -> BaselineSearchPolicy | ShortSearchPolicy:
    if document.get("version") == "2608-ideation-search-g3-v1":
        return ShortSearchPolicy.model_validate(document)
    if document.get("version") == "2608-ideation-search-v1":
        return BaselineSearchPolicy.model_validate(document)
    raise ValueError("unsupported explicit Ideation search version")


def select_baseline_parents(
    ratings: Mapping[str, CandidateRating], *, epoch_id: str, seed: str,
    generation: int, slot: int,
) -> BaselineParentDecision:
    """Spec §7/8: uniform contestants from cumulative P, then UCB winner."""
    if generation not in range(1, 11) or slot not in range(2):
        raise ValueError("baseline reproduction slot outside G1..G10")
    if any(key != value.hypothesis_id or not isfinite(value.mu)
           or not isfinite(value.sigma) or value.sigma <= 0
           for key, value in ratings.items()):
        raise ValueError("invalid baseline parent rating identity")
    pool = sorted(key for key, value in ratings.items()
                  if value.epoch_id == epoch_id and value.decisive_matches >= 2)
    random_identity = f"python-mt19937-sha256-v1:{seed}:{epoch_id}:{generation}:{slot}"
    rng = random.Random(int(hashlib.sha256(random_identity.encode()).hexdigest(), 16))
    draw = rng.random()
    operator: Operator = "crossover" if draw < 0.7 else "mutation"
    parents: list[str] = []
    draws: list[tuple[str, ...]] = []
    state: Literal["SELECTED", "NO_ELIGIBLE_PARENTS", "SKIPPED_INSUFFICIENT_DISTINCT_PARENTS"]
    state = "SELECTED"
    if not pool:
        state = "NO_ELIGIBLE_PARENTS"
    elif len(pool) == 1 and operator == "crossover":
        state = "SKIPPED_INSUFFICIENT_DISTINCT_PARENTS"
    else:
        available = pool.copy()
        for _ in range(2 if operator == "crossover" else 1):
            contestants = tuple(rng.sample(available, min(2, len(available))))
            winner = min(contestants, key=lambda key: (
                -(ratings[key].mu + ratings[key].sigma), -ratings[key].mu, key))
            draws.append(contestants)
            parents.append(winner)
            available.remove(winner)
    return BaselineParentDecision(
        generation=generation, slot=slot, epoch_id=epoch_id, seed=seed,
        operator_draw=draw, operator=operator, eligible_parent_ids=tuple(pool),
        contestant_draws=tuple(draws), parent_ids=tuple(parents), state=state,
    )


def baseline_final_choice(
    ratings: Mapping[str, CandidateRating], *, epoch_id: str, complete: bool,
) -> tuple[str, str | None, str | None]:
    """Spec §9: exact posterior mean over cumulative P, never UCB or top-K."""
    pool = [key for key, value in ratings.items()
            if value.epoch_id == epoch_id and value.decisive_matches >= 2]
    if any(key != ratings[key].hypothesis_id or not isfinite(ratings[key].mu)
           or not isfinite(ratings[key].sigma) for key in pool):
        raise ValueError("invalid final eligible rating identity")
    best = min(pool, key=lambda key: (-ratings[key].mu, key)) if pool else None
    if not complete:
        return "INCOMPLETE", None, best
    return ("FINAL_WINNER", best, None) if best else ("NO_ELIGIBLE_HYPOTHESIS", None, None)


def _default_mutation_weights() -> dict[MutationStrategy, float]:
    return {"simplify": 1.0, "feasibility": 1.0, "out_of_box": 1.0,
            "targeted_revision": 1.0}


class PopulationEvolutionPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal["population_evolution_v1"] = "population_evolution_v1"
    population_size: int = Field(default=6, ge=2, le=100, strict=True)
    offspring_per_generation: int = Field(default=2, ge=1, le=30, strict=True)
    max_generations: int = Field(default=2, ge=1, le=20, strict=True)
    parent_pool_size: int = Field(default=6, ge=2, le=100, strict=True)
    elite_count: int = Field(default=2, ge=0, le=100, strict=True)
    exploration_slots: int = Field(default=1, ge=0, le=100, strict=True)
    crossover_probability: float = Field(default=0.7, ge=0, le=1, allow_inf_nan=False)
    mutation_probability: float = Field(default=0.3, ge=0, le=1, allow_inf_nan=False)
    mutation_strategy_weights: dict[MutationStrategy, float] = Field(
        default_factory=_default_mutation_weights)
    max_offspring_per_parent: int = Field(default=3, ge=1, le=100, strict=True)
    max_crossover_repeats_per_parent_pair: int = Field(default=2, ge=1, le=100, strict=True)
    max_total_hypotheses: int = Field(default=30, ge=2, le=1000, strict=True)
    minimum_child_validation_reserve: int = Field(default=12, ge=1, le=1000, strict=True)
    matches_per_generation: int = Field(default=1, ge=0, le=20, strict=True)
    random_seed_policy: Literal["run-generation-slot-sha256-v1"] = (
        "run-generation-slot-sha256-v1"
    )

    @model_validator(mode="after")
    def validate_bounds(self) -> PopulationEvolutionPolicy:
        if abs(self.crossover_probability + self.mutation_probability - 1.0) > 1e-9:
            raise ValueError("crossover and mutation probabilities must sum to one")
        if self.elite_count + self.exploration_slots > self.population_size:
            raise ValueError("elite and exploration slots exceed population size")
        if self.parent_pool_size > self.max_total_hypotheses:
            raise ValueError("parent pool exceeds total hypothesis cap")
        if not self.mutation_strategy_weights or any(
            weight < 0 or not isfinite(weight)
            for weight in self.mutation_strategy_weights.values()
        ) or sum(self.mutation_strategy_weights.values()) <= 0:
            raise ValueError("mutation strategy weights must be finite and positive in total")
        return self


class ParentCandidate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    hypothesis_id: str
    content_id: str
    content_hash: str
    mu: float
    sigma: float
    review_complete: bool
    evidence_complete: bool
    safety_clear: bool
    cluster: str | None = None
    offspring_count: int = 0
    generation_index: int = 0


class ParentSelectionDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_id: str
    generation_id: str
    slot: int
    operator: Operator
    mutation_subtype: MutationStrategy | None
    eligible_parent_ids: tuple[str, ...]
    chosen_parent_ids: tuple[str, ...]
    candidate_metrics: dict[str, dict[str, Any]]
    pair_metrics: dict[str, Any]
    rejected_alternatives: dict[str, Any]
    selection_reason: dict[str, Any]
    random_seed: str
    sampled_value: float


def deterministic_sample(seed: str, label: str) -> float:
    digest = hashlib.sha256(f"{seed}:{label}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def sample_operator(policy: PopulationEvolutionPolicy, seed: str) -> Operator:
    return ("crossover" if deterministic_sample(seed, "operator") <
            policy.crossover_probability else "mutation")


def sample_mutation(policy: PopulationEvolutionPolicy, seed: str) -> MutationStrategy:
    weights = policy.mutation_strategy_weights
    point = deterministic_sample(seed, "mutation") * sum(weights.values())
    running = 0.0
    for strategy, weight in sorted(weights.items()):
        running += weight
        if point < running:
            return strategy
    return max(weights)


def choose_parents(
    *, generation_id: str, slot: int, candidates: Sequence[ParentCandidate],
    policy: PopulationEvolutionPolicy, pair_counts: Mapping[tuple[str, str], int],
    seed: str, operator: Operator, kappa: float = 1.0,
) -> ParentSelectionDecision:
    """Scientific eligibility first, then bounded quality/exploration/diversity."""

    if slot < 1 or slot > policy.offspring_per_generation:
        raise ValueError("offspring slot is outside frozen generation cap")
    if not isfinite(kappa) or kappa < 0:
        raise ValueError("UCB kappa must be finite and nonnegative")
    if len({candidate.hypothesis_id for candidate in candidates}) != len(candidates):
        raise ValueError("duplicate parent candidate")
    rejected: dict[str, Any] = {}
    eligible = []
    metrics: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        metrics[candidate.hypothesis_id] = {
            "mu": candidate.mu, "sigma": candidate.sigma,
            "ucb": candidate.mu + kappa * candidate.sigma,
            "review_status": "complete" if candidate.review_complete else "incomplete",
            "evidence_status": "complete" if candidate.evidence_complete else "incomplete",
            "safety_status": "clear" if candidate.safety_clear else "blocked",
            "reproduction_count": candidate.offspring_count,
            "generation_index": candidate.generation_index,
            "cluster": candidate.cluster,
        }
        if not (candidate.review_complete and candidate.evidence_complete
                and candidate.safety_clear):
            rejected[candidate.hypothesis_id] = {"reason": "scientifically_ineligible"}
        elif candidate.offspring_count >= policy.max_offspring_per_parent:
            rejected[candidate.hypothesis_id] = {"reason": "parent_reproduction_cap"}
        else:
            eligible.append(candidate)
    eligible.sort(key=lambda item: (-(item.mu + kappa * item.sigma), item.hypothesis_id))
    # Keep an exploration tail even when quality dominates the pool.
    quality_count = max(0, policy.parent_pool_size - policy.exploration_slots)
    quality_pool = eligible[:quality_count]
    exploratory = sorted(eligible, key=lambda item: (-item.sigma,
                         item.offspring_count, item.hypothesis_id))
    pool = list(quality_pool)
    for item in exploratory:
        if len(pool) >= policy.parent_pool_size:
            break
        if item not in pool:
            pool.append(item)
    for item in eligible:
        if item not in pool:
            rejected[item.hypothesis_id] = {"reason": "outside_parent_pool_size"}
    if operator == "crossover" and len(pool) < 2:
        raise ValueError("no eligible distinct crossover parents")
    if operator == "mutation" and not pool:
        raise ValueError("no eligible mutation parent")
    exploration = slot > policy.offspring_per_generation - policy.exploration_slots
    track = "exploration" if exploration else "quality"
    subtype = sample_mutation(policy, seed) if operator == "mutation" else None
    chosen: tuple[str, ...]
    if operator == "mutation":
        selected = max(pool, key=lambda item: (
            (item.sigma if exploration else item.mu + kappa * item.sigma),
            -item.offspring_count, item.hypothesis_id,
        ))
        chosen = (selected.hypothesis_id,)
        pair_metrics: dict[str, Any] = {}
        for item in pool:
            if item.hypothesis_id != selected.hypothesis_id:
                rejected[item.hypothesis_id] = {
                    "reason": "lower_mutation_priority", "track": track,
                    "quality_ucb": item.mu + kappa * item.sigma,
                    "uncertainty": item.sigma,
                }
    else:
        pairs = []
        for index, left in enumerate(pool):
            for right in pool[index + 1:]:
                left_id, right_id = sorted((left.hypothesis_id, right.hypothesis_id))
                pair = (left_id, right_id)
                count = pair_counts.get(pair, 0)
                if count >= policy.max_crossover_repeats_per_parent_pair:
                    rejected[" × ".join(pair)] = {"reason": "pair_reproduction_cap",
                                                   "prior_reproduction_count": count}
                    continue
                diverse = int(bool(left.cluster and right.cluster
                                   and left.cluster != right.cluster))
                # Diversity is an explicit tie-break/coverage factor, never an eligibility waiver.
                quality_score = left.mu + right.mu + kappa * (left.sigma + right.sigma)
                new_candidate = int(left.generation_index > 0 or right.generation_index > 0)
                score = ((max(left.sigma, right.sigma),
                          min(left.sigma, right.sigma), diverse, new_candidate, quality_score,
                          -count, -max(left.offspring_count, right.offspring_count), pair)
                         if exploration else
                         (quality_score, diverse, new_candidate, -count,
                          -max(left.offspring_count, right.offspring_count), pair))
                pairs.append((score, left, right, count, diverse))
        if not pairs:
            raise ValueError("no crossover pair under repeat cap")
        _, left, right, count, diverse = max(pairs, key=lambda item: item[0])
        chosen = tuple(sorted((left.hypothesis_id, right.hypothesis_id)))
        pair_metrics = {"mechanism_complementarity": "distinct_cluster" if diverse
                        else "not_established", "prior_reproduction_count": count,
                        "new_candidate_in_pair": int(left.generation_index > 0 or
                                                     right.generation_index > 0)}
        for score, alternative_left, alternative_right, alternative_count, alternative_diverse in pairs:
            alternative = tuple(sorted((alternative_left.hypothesis_id,
                                        alternative_right.hypothesis_id)))
            if alternative == chosen:
                continue
            rejected[" × ".join(alternative)] = {
                "reason": "lower_policy_priority", "track": track,
                "quality_ucb_sum": alternative_left.mu + alternative_right.mu
                                   + kappa * (alternative_left.sigma + alternative_right.sigma),
                "mechanism_complementarity": "distinct_cluster" if alternative_diverse
                                             else "not_established",
                "prior_reproduction_count": alternative_count,
                "new_candidate_in_pair": int(alternative_left.generation_index > 0 or
                                             alternative_right.generation_index > 0),
                "ordered_score": list(score[:-1]),
            }
    return ParentSelectionDecision(
        decision_id=f"{generation_id}:selection:{slot}", generation_id=generation_id,
        slot=slot, operator=operator, mutation_subtype=subtype,
        eligible_parent_ids=tuple(item.hypothesis_id for item in eligible),
        chosen_parent_ids=chosen, candidate_metrics=metrics,
        pair_metrics=pair_metrics, rejected_alternatives=rejected,
        selection_reason={"track": track, "rule": "eligibility_then_ucb_diversity_caps",
                          "ucb_kappa": kappa,
                          "priority_order": (["max_sigma", "min_sigma",
                                              "mechanism_diversity", "new_candidate", "ucb_sum",
                                              "reproduction_caps", "stable_id"]
                                             if exploration else
                                             ["ucb_sum", "mechanism_diversity",
                                              "new_candidate", "reproduction_caps",
                                              "stable_id"]),
                          "selected": list(chosen)},
        random_seed=seed, sampled_value=deterministic_sample(seed, "operator"),
    )


def retain_population(
    *, previous_ids: Sequence[str], admitted_offspring_ids: Sequence[str],
    candidates: Mapping[str, ParentCandidate], policy: PopulationEvolutionPolicy,
) -> tuple[str, ...]:
    """Keep validated children, then diverse elites/explorers; never delete history."""

    valid = {key: value for key, value in candidates.items()
             if value.review_complete and value.evidence_complete and value.safety_clear}
    children = [key for key in admitted_offspring_ids if key in valid]
    if len(children) > policy.population_size:
        children = children[:policy.population_size]
    remaining = [key for key in previous_ids if key in valid and key not in children]
    quality = sorted(remaining, key=lambda key: (
        -valid[key].mu, valid[key].sigma, key,
    ))
    active = list(children)
    for key in quality[:policy.elite_count]:
        if len(active) < policy.population_size and key not in active:
            active.append(key)
    explorers = sorted(remaining, key=lambda key: (
        -valid[key].sigma, valid[key].offspring_count, key,
    ))
    for key in explorers[:policy.exploration_slots]:
        if len(active) < policy.population_size and key not in active:
            active.append(key)
    for key in quality:
        if len(active) >= policy.population_size:
            break
        if key not in active:
            active.append(key)
    return tuple(active)
