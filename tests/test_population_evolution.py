"""Population policy contracts are deterministic and independent of LLM output."""

import pytest
from pydantic import ValidationError


def test_baseline_parent_tournament_and_operator_are_replayable():
    from co_scientist.domain.bayesian_ranking import CandidateRating
    from co_scientist.domain.population_evolution import select_baseline_parents

    ratings = {key: CandidateRating(hypothesis_id=key, epoch_id="epoch", mu=mu,
                                   sigma=sigma, decisive_matches=2)
               for key, mu, sigma in (("a", 30, 1), ("b", 28, 6), ("c", 20, 5))}
    choice = select_baseline_parents(ratings, epoch_id="epoch", seed="fixed",
                                     generation=1, slot=0)
    assert choice == select_baseline_parents(ratings, epoch_id="epoch", seed="fixed",
                                              generation=1, slot=0)
    assert set(choice.eligible_parent_ids) == set(ratings)
    assert len(set(choice.parent_ids)) == len(choice.parent_ids)
    assert len(choice.parent_ids) == (2 if choice.operator == "crossover" else 1)
    for contestants, parent in zip(choice.contestant_draws, choice.parent_ids, strict=True):
        assert parent == min(contestants, key=lambda key: (
            -(ratings[key].mu + ratings[key].sigma), -ratings[key].mu, key))


def test_baseline_singleton_crossover_consumes_slot_without_compensation():
    from co_scientist.domain.bayesian_ranking import CandidateRating
    from co_scientist.domain.population_evolution import select_baseline_parents

    ratings = {"a": CandidateRating(hypothesis_id="a", epoch_id="e", mu=25,
                                    sigma=8, decisive_matches=2)}
    choices = [select_baseline_parents(ratings, epoch_id="e", seed=str(seed),
                                      generation=1, slot=0) for seed in range(30)]
    crossover = [choice for choice in choices if choice.operator == "crossover"]
    assert crossover and all(choice.state == "SKIPPED_INSUFFICIENT_DISTINCT_PARENTS"
                             and not choice.parent_ids for choice in crossover)
    assert any(choice.operator == "mutation" and choice.parent_ids == ("a",)
               for choice in choices)


def test_baseline_final_winner_is_mu_not_ucb_and_partial_has_no_winner():
    from co_scientist.domain.bayesian_ranking import CandidateRating
    from co_scientist.domain.population_evolution import baseline_final_choice

    ratings = {"mu": CandidateRating(hypothesis_id="mu", epoch_id="e", mu=30, sigma=1,
                                      decisive_matches=2),
               "ucb": CandidateRating(hypothesis_id="ucb", epoch_id="e", mu=29, sigma=8,
                                       decisive_matches=2)}
    assert baseline_final_choice(ratings, epoch_id="e", complete=True) == (
        "FINAL_WINNER", "mu", None)
    assert baseline_final_choice(ratings, epoch_id="e", complete=False) == (
        "INCOMPLETE", None, "mu")
    assert baseline_final_choice({}, epoch_id="e", complete=True) == (
        "NO_ELIGIBLE_HYPOTHESIS", None, None)
    ratings["a"] = ratings["mu"].model_copy(update={"hypothesis_id": "a"})
    assert baseline_final_choice(ratings, epoch_id="e", complete=True)[1] == "a"

from co_scientist.domain.population_evolution import (
    ParentCandidate,
    PopulationEvolutionPolicy,
    choose_parents,
)


def candidate(key: str, *, mu: float, sigma: float, cluster: str,
              offspring: int = 0, eligible: bool = True) -> ParentCandidate:
    return ParentCandidate(
        hypothesis_id=key, content_id=f"content-{key}",
        content_hash="sha256:" + key.lower()[0] * 64,
        mu=mu, sigma=sigma, review_complete=eligible,
        evidence_complete=eligible, safety_clear=eligible,
        cluster=cluster, offspring_count=offspring,
    )


def test_policy_is_frozen_and_probabilities_are_normalized():
    policy = PopulationEvolutionPolicy()
    assert policy.version == "population_evolution_v1"
    assert policy.crossover_probability + policy.mutation_probability == 1
    with pytest.raises(ValueError):
        PopulationEvolutionPolicy(crossover_probability=0.9, mutation_probability=0.3)
    with pytest.raises(ValidationError):
        policy.max_generations = 100


def test_parent_selection_excludes_ineligible_and_caps_monopoly():
    policy = PopulationEvolutionPolicy(max_offspring_per_parent=1)
    candidates = [
        candidate("a", mu=40, sigma=1, cluster="x", offspring=1),
        candidate("b", mu=28, sigma=6, cluster="x"),
        candidate("c", mu=25, sigma=8, cluster="y"),
        candidate("d", mu=50, sigma=1, cluster="z", eligible=False),
    ]
    decision = choose_parents(
        generation_id="g1", slot=1, candidates=candidates, policy=policy,
        pair_counts={}, seed="fixed", operator="crossover",
    )
    assert set(decision.chosen_parent_ids) == {"b", "c"}
    assert "a" in decision.rejected_alternatives
    assert "d" in decision.rejected_alternatives
    assert decision.candidate_metrics["b"]["sigma"] == 6


def test_pair_repeat_cap_forces_another_pair_and_replay_is_stable():
    policy = PopulationEvolutionPolicy(max_crossover_repeats_per_parent_pair=1)
    candidates = [
        candidate("a", mu=30, sigma=2, cluster="x"),
        candidate("b", mu=29, sigma=2, cluster="y"),
        candidate("c", mu=24, sigma=9, cluster="z"),
    ]
    kwargs = {"generation_id": "g1", "slot": 2, "candidates": candidates,
              "policy": policy, "pair_counts": {("a", "b"): 1},
              "seed": "fixed", "operator": "crossover"}
    first = choose_parents(**kwargs)
    assert set(first.chosen_parent_ids) != {"a", "b"}
    assert choose_parents(**kwargs) == first


def test_mutation_uses_one_parent_and_respects_exploration():
    policy = PopulationEvolutionPolicy(exploration_slots=1)
    candidates = [candidate("a", mu=40, sigma=1, cluster="x"),
                  candidate("b", mu=24, sigma=10, cluster="y")]
    decision = choose_parents(
        generation_id="g1", slot=2, candidates=candidates, policy=policy,
        pair_counts={}, seed="fixed", operator="mutation",
    )
    assert decision.chosen_parent_ids == ("b",)
    assert decision.selection_reason["track"] == "exploration"
