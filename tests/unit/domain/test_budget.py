from decimal import Decimal

import pytest
from pydantic import ValidationError

from co_scientist.domain.budget import (
    BudgetEstimate,
    BudgetPolicy,
    BudgetUsage,
    DurableBudgetSnapshot,
)


def test_null_cost_limit_is_unlimited_for_complete_usage() -> None:
    usage = BudgetUsage(cost_usd=Decimal("12.34"), model_calls=1, hypotheses=3, matches=4)

    assert not BudgetPolicy(max_usd=None).reached(usage)


def test_cost_or_model_call_limits_are_hard_budget_limits() -> None:
    assert BudgetPolicy(max_usd=Decimal("10.00")).reached(
        BudgetUsage(cost_usd=Decimal("10.00"))
    )
    assert BudgetPolicy(max_model_calls=2).reached(BudgetUsage(model_calls=2))


def test_hypothesis_and_match_limits_are_hard_budget_limits_at_threshold() -> None:
    assert BudgetPolicy(max_hypotheses=3).reached(BudgetUsage(hypotheses=3))
    assert BudgetPolicy(max_matches=4).reached(BudgetUsage(matches=4))


def test_candidate_capacity_allows_downstream_work_but_not_overflow() -> None:
    policy = BudgetPolicy(hypothesis_limit_policy="capacity-v2", max_hypotheses=3,
                          max_model_calls=10, max_matches=4)
    assert not policy.reached(BudgetUsage(hypotheses=3))
    assert policy.reached(BudgetUsage(hypotheses=4))
    assert policy.reached(BudgetUsage(hypotheses=3, model_calls=10))
    assert policy.reached(BudgetUsage(hypotheses=3, matches=4))
    assert "hypothesis_limit_policy" not in BudgetPolicy().model_dump()
    assert BudgetPolicy.model_validate(policy.model_dump()) == policy


def test_capacity_reservations_allow_processing_but_reject_new_candidates() -> None:
    from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork

    policy = BudgetPolicy(hypothesis_limit_policy="capacity-v2", max_hypotheses=3)
    usage = BudgetUsage(hypotheses=3)
    assert SqliteUnitOfWork._fits_budget(policy, usage, BudgetEstimate(model_calls=1))
    assert not SqliteUnitOfWork._fits_budget(policy, usage, BudgetEstimate(hypotheses=1))


# Mutation caught: token limits are collapsed into model-call or USD accounting.
def test_input_and_output_token_limits_are_independent_hard_limits() -> None:
    assert BudgetPolicy(max_input_tokens=10).reached(BudgetUsage(input_tokens=10))
    assert BudgetPolicy(max_output_tokens=20).reached(BudgetUsage(output_tokens=20))


# Mutation caught: null unlimited limits are coerced to zero or negative finite limits pass.
def test_budget_policy_preserves_null_unlimited_and_rejects_negative_finite_limits() -> None:
    policy = BudgetPolicy(
        max_usd=None,
        max_model_calls=None,
        max_input_tokens=None,
        max_output_tokens=None,
        max_hypotheses=None,
        max_matches=None,
    )
    assert all(value is None for value in policy.model_dump().values())

    for field in BudgetPolicy.model_fields:
        with pytest.raises(ValidationError):
            BudgetPolicy.model_validate({field: Decimal("-0.01") if field == "max_usd" else -1})


# Mutation caught: checking only settled usage and ignoring active reservations.
def test_durable_snapshot_checks_limits_against_settled_plus_active_reservations() -> None:
    snapshot = DurableBudgetSnapshot(
        run_id="run-1",
        policy_version="sha256:policy",
        settled=BudgetUsage(model_calls=2, hypotheses=1),
        actively_reserved=BudgetEstimate(model_calls=1, hypotheses=3),
        hard_limit_reached=True,
        source_reservation_ids=("reservation-1", "reservation-2"),
        source_cost_entry_ids=("cost-1",),
    )

    assert snapshot.hard_limit_reached
    assert snapshot.total_usage == BudgetUsage(model_calls=3, hypotheses=4)


# Mutation caught: omitting durable snapshots when every policy dimension is unlimited.
def test_unlimited_durable_snapshot_still_records_complete_sources() -> None:
    snapshot = DurableBudgetSnapshot(
        run_id="run-1",
        policy_version="sha256:unlimited",
        settled=BudgetUsage(input_tokens=12, output_tokens=7, cost_usd=Decimal("0.03")),
        actively_reserved=BudgetEstimate(model_calls=1),
        hard_limit_reached=False,
        source_reservation_ids=("reservation-1", "reservation-2"),
        source_cost_entry_ids=("cost-1",),
    )

    assert not snapshot.hard_limit_reached
    assert snapshot.total_usage.input_tokens == 12
    assert snapshot.total_usage.model_calls == 1
