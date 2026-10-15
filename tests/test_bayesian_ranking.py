"""Deterministic TrueSkill ledger and bounded UCB pairing contracts."""

from co_scientist.domain.bayesian_ranking import (
    CandidateRating,
    TrueSkillConfig,
    UCBPairingPolicy,
    replay_bayesian_rating,
    select_ucb_pair,
)
from co_scientist.domain.tournament import MatchDecision, MatchResult, apply_match
from co_scientist.events.models import DomainEvent, NewEvent
from co_scientist.events.reducers import replay_tournament


def test_baseline_pairing_ignores_rating_and_alternates_orientation():
    from co_scientist.domain.bayesian_ranking import select_baseline_pair

    ratings = {key: CandidateRating(hypothesis_id=key, epoch_id="e1", mu=25,
                                   sigma=8, decisive_matches=0)
               for key in ("a", "b", "c")}
    first, state = select_baseline_pair(ratings, [], epoch_id="e1", seed="seed")
    assert state == "MATCH_REQUIRED" and first is not None
    changed = {key: value.model_copy(update={"mu": 1000 if key == "c" else -20,
                                           "sigma": 1 if key == "c" else 90})
               for key, value in ratings.items()}
    assert select_baseline_pair(changed, [], epoch_id="e1", seed="seed")[0] == first
    pair_only = {key: ratings[key] for key in (first.left_id, first.right_id)}
    rows = [event("MatchPairReserved", match_id="one", left_id=first.left_id,
                  right_id=first.right_id, focal_id=first.focal_id)]
    second, _ = select_baseline_pair(pair_only, rows, epoch_id="e1", seed="seed")
    assert second is not None
    assert (second.left_id, second.right_id) == (first.right_id, first.left_id)


def test_baseline_focal_cap_quota_and_singleton_are_distinct():
    from co_scientist.domain.bayesian_ranking import select_baseline_pair

    a = CandidateRating(hypothesis_id="a", epoch_id="e1", mu=25, sigma=8)
    b = a.model_copy(update={"hypothesis_id": "b", "decisive_matches": 2})
    assert select_baseline_pair({"a": a}, [], epoch_id="e1", seed="x")[1] == (
        "NO_COMPARABLE_PAIR")
    rows = [event("MatchPairReserved", match_id=str(i), left_id="a", right_id="b",
                  focal_id="a") for i in range(6)]
    assert select_baseline_pair({"a": a, "b": b}, rows, epoch_id="e1", seed="x")[1] == (
        "EVALUATION_INCOMPLETE")
    pair, _ = select_baseline_pair({"a": a, "b": b}, [], epoch_id="e1", seed="x")
    assert pair is not None and pair.focal_id == "a" and pair.opponent_id == "b"
    complete = a.model_copy(update={"decisive_matches": 2})
    assert select_baseline_pair({"a": complete, "b": b}, [], epoch_id="e1", seed="x")[1] == (
        "EVALUATION_COMPLETE")


def event(name, **payload):
    return NewEvent(event_type=name, payload={"epoch_id": "e1", **payload})


def ledger():
    return [event("TournamentEntryCreated", hypothesis_id=key) for key in ("h1", "h2", "h3")]


def test_trueskill_replay_matches_explicit_reference_environment():
    from trueskill import TrueSkill

    policy = TrueSkillConfig()
    rows = ledger() + [
        event("MatchPairReserved", match_id="m1", left_id="h1", right_id="h2"),
        event("MatchEvaluated", match_id="m1", left_id="h1", right_id="h2",
              decision="decisive", winner_id="h1"),
    ]
    result = replay_bayesian_rating(rows, epoch_id="e1", policy=policy)
    reference = TrueSkill(mu=policy.mu0, sigma=policy.sigma0, beta=policy.beta,
                          tau=policy.tau, draw_probability=0.0)
    expected = reference.rate([(reference.create_rating(),),
                               (reference.create_rating(),)], ranks=[0, 1])
    assert (result["h1"].mu, result["h1"].sigma) == (expected[0][0].mu, expected[0][0].sigma)
    assert (result["h2"].mu, result["h2"].sigma) == (expected[1][0].mu, expected[1][0].sigma)
    assert result["h1"].mu > result["h2"].mu
    assert result["h3"].mu == policy.mu0
    assert result == replay_bayesian_rating(rows, epoch_id="e1", policy=policy)


def test_inconclusive_and_invalid_do_not_change_rating_but_count_attempts():
    policy = TrueSkillConfig()
    rows = ledger() + [
        event("MatchPairReserved", match_id="m1", left_id="h1", right_id="h2"),
        event("MatchEvaluated", match_id="m1", left_id="h1", right_id="h2",
              decision="inconclusive", winner_id=None),
        event("MatchPairReserved", match_id="m2", left_id="h1", right_id="h2"),
        event("MatchEvaluated", match_id="m2", left_id="h1", right_id="h2",
              decision="invalid", winner_id=None),
    ]
    ratings = replay_bayesian_rating(rows, epoch_id="e1", policy=policy)
    assert ratings["h1"].mu == policy.mu0
    assert ratings["h1"].sigma == policy.sigma0
    assert ratings["h1"].decisive_matches == 0
    assert ratings["h1"].total_match_attempts == 2


def test_conflicting_outcomes_and_new_epoch_are_independent():
    policy = TrueSkillConfig()
    rows = ledger() + [
        event("MatchPairReserved", match_id="m1", left_id="h1", right_id="h2"),
        event("MatchEvaluated", match_id="m1", left_id="h1", right_id="h2",
              decision="decisive", winner_id="h1"),
        event("MatchPairReserved", match_id="m2", left_id="h2", right_id="h1"),
        event("MatchEvaluated", match_id="m2", left_id="h2", right_id="h1",
              decision="decisive", winner_id="h2"),
        NewEvent(event_type="TournamentEntryCreated", payload={"epoch_id": "e2",
                                                             "hypothesis_id": "h1"}),
    ]
    result = replay_bayesian_rating(rows, epoch_id="e1", policy=policy)
    assert result["h1"].decisive_matches == 2
    assert result["h1"].sigma < policy.sigma0
    assert replay_bayesian_rating(rows, epoch_id="e2", policy=policy)["h1"].mu == policy.mu0


def test_coverage_prevents_starvation_and_new_uncertain_candidate_gets_pair():
    ratings = {
        "h1": CandidateRating(hypothesis_id="h1", epoch_id="e1", mu=35, sigma=2),
        "h2": CandidateRating(hypothesis_id="h2", epoch_id="e1", mu=25, sigma=9),
        "h3": CandidateRating(hypothesis_id="h3", epoch_id="e1", mu=20, sigma=8),
        "h4": CandidateRating(hypothesis_id="h4", epoch_id="e1", mu=26, sigma=3),
    }
    rows = [event("MatchPairReserved", match_id=f"m{i}", left_id="h1", right_id="h4")
            for i in range(2)]
    proposal, reason = select_ucb_pair(
        ratings, rows, epoch_id="e1", policy=UCBPairingPolicy(),
        context_hashes={key: key for key in ratings},
    )
    assert proposal is not None and reason.startswith("selected_")
    assert {proposal.left_id, proposal.right_id} == {"h2", "h3"}
    assert proposal.reason["coverage_priority"] == 0


def test_two_candidate_pair_cap_stops_instead_of_repeating():
    ratings = {key: CandidateRating(hypothesis_id=key, epoch_id="e1", mu=25, sigma=8)
               for key in ("h1", "h2")}
    rows = [event("MatchPairReserved", match_id=f"m{i}", left_id="h1", right_id="h2")
            for i in range(3)]
    proposal, reason = select_ucb_pair(
        ratings, rows, epoch_id="e1", policy=UCBPairingPolicy(max_matches_per_pair=3),
        context_hashes={key: key for key in ratings},
    )
    assert proposal is None
    assert reason == "no_eligible_pair_under_match_caps"


def test_evidence_gap_blocks_immediate_rematch_and_requires_changed_context():
    ratings = {key: CandidateRating(hypothesis_id=key, epoch_id="e1", mu=25, sigma=8)
               for key in ("h1", "h2")}
    rows = [
        event("MatchPairReserved", match_id="m1", left_id="h1", right_id="h2"),
        event("MatchEvaluated", match_id="m1", left_id="h1", right_id="h2",
              decision="needs_more_evidence", winner_id=None),
        event("EvidenceGapRecorded", match_id="m1", left_id="h1", right_id="h2",
              left_context_hash="old-a", right_context_hash="old-b"),
    ]
    policy = UCBPairingPolicy(max_matches_per_pair=3, max_tiebreakers_per_pair=1)
    blocked, reason = select_ucb_pair(
        ratings, rows, epoch_id="e1", policy=policy,
        context_hashes={"h1": "old-a", "h2": "old-b"},
    )
    assert blocked is None and reason == "no_eligible_pair_under_match_caps"
    reopened, _ = select_ucb_pair(
        ratings, rows, epoch_id="e1", policy=policy,
        context_hashes={"h1": "new-a", "h2": "old-b"},
    )
    assert reopened is not None and reopened.comparison_kind == "tiebreaker"
    rows.append(event("MatchPairReserved", match_id="m2", left_id="h1", right_id="h2",
                      comparison_kind="tiebreaker"))
    blocked_again, _ = select_ucb_pair(
        ratings, rows, epoch_id="e1", policy=policy,
        context_hashes={"h1": "another-a", "h2": "old-b"},
    )
    assert blocked_again is None


def test_new_evidence_without_match_does_not_mutate_rating():
    policy = TrueSkillConfig()
    rows = ledger()
    before = replay_bayesian_rating(rows, epoch_id="e1", policy=policy)
    rows.append(event("EvidenceSnapshotRecorded", hypothesis_id="h1",
                      snapshot_hash="sha256:new-evidence"))
    after = replay_bayesian_rating(rows, epoch_id="e1", policy=policy)
    assert before == after


def test_invalid_output_after_reserved_attempt_still_consumes_pair_cap():
    ratings = {key: CandidateRating(hypothesis_id=key, epoch_id="e1", mu=25, sigma=8)
               for key in ("h1", "h2")}
    rows = [event("MatchPairReserved", match_id="bad-judge-output",
                  left_id="h1", right_id="h2")]
    projected = replay_bayesian_rating(ledger() + rows,
                                       epoch_id="e1", policy=TrueSkillConfig())
    assert projected["h1"].total_match_attempts == 1
    assert projected["h1"].decisive_matches == 0
    proposal, reason = select_ucb_pair(
        ratings, rows, epoch_id="e1", policy=UCBPairingPolicy(max_matches_per_pair=1),
        context_hashes={"h1": "a", "h2": "b"},
    )
    assert proposal is None and reason == "no_eligible_pair_under_match_caps"


def test_fixed_decisive_ledger_keeps_elo_and_trueskill_projections_isolated():
    winner, loser = apply_match(
        1200.0, 1200.0,
        MatchResult(match_id="m1", epoch_id="elo-epoch", left_id="h1",
                    right_id="h2", decision=MatchDecision.DECISIVE, winner_id="h1"),
    )
    elo_events = [
        DomainEvent(sequence=index, run_id="r", event_type=name, payload=payload)
        for index, (name, payload) in enumerate((
            ("TournamentEntryCreated", {"epoch_id": "elo-epoch", "hypothesis_id": "h1",
                                        "rating": 1200.0}),
            ("TournamentEntryCreated", {"epoch_id": "elo-epoch", "hypothesis_id": "h2",
                                        "rating": 1200.0}),
            ("MatchEvaluated", {"epoch_id": "elo-epoch", "match_id": "m1",
                                "left_id": "h1", "right_id": "h2", "winner_id": "h1",
                                "decision": "decisive"}),
            ("RatingUpdated", {"epoch_id": "elo-epoch", "match_id": "m1",
                               "hypothesis_id": "h1", "rating": winner}),
            ("RatingUpdated", {"epoch_id": "elo-epoch", "match_id": "m1",
                               "hypothesis_id": "h2", "rating": loser}),
        ), start=1)
    ]
    bayesian_events = ledger() + [
        event("MatchPairReserved", match_id="m1", left_id="h1", right_id="h2"),
        event("MatchEvaluated", match_id="m1", left_id="h1", right_id="h2",
              decision="decisive", winner_id="h1"),
    ]
    assert replay_tournament(elo_events).ratings["elo-epoch"] == {"h1": winner, "h2": loser}
    state = replay_bayesian_rating(bayesian_events, epoch_id="e1", policy=TrueSkillConfig())
    assert state["h1"].mu > state["h2"].mu
    assert replay_tournament(elo_events).ratings["elo-epoch"]["h1"] == 1216.0
