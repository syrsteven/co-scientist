from decimal import Decimal

import pytest
from pydantic import ValidationError

from co_scientist.domain.budget import BudgetLedger, BudgetPolicy


def test_null_cost_limit_is_unlimited_but_usage_is_recorded() -> None:
    ledger = BudgetLedger(policy=BudgetPolicy(max_usd=None))

    updated = ledger.settle(
        cost_usd=Decimal("12.34"),
        model_calls=1,
        hypotheses=3,
        matches=4,
    )

    assert updated.cost_usd == Decimal("12.34")
    assert updated.hypotheses == 3
    assert updated.matches == 4
    assert not updated.hard_limit_reached


def test_cost_or_model_call_limits_are_hard_budget_limits() -> None:
    cost_limited = BudgetLedger(policy=BudgetPolicy(max_usd=Decimal("10.00"))).settle(
        cost_usd=Decimal("10.00"), model_calls=0
    )
    call_limited = BudgetLedger(policy=BudgetPolicy(max_model_calls=2)).settle(
        cost_usd=Decimal(0), model_calls=2
    )

    assert cost_limited.hard_limit_reached
    assert call_limited.hard_limit_reached


def test_hypothesis_and_match_limits_are_hard_budget_limits_at_threshold() -> None:
    hypothesis_limited = BudgetLedger(policy=BudgetPolicy(max_hypotheses=3)).settle(
        cost_usd=Decimal(0), model_calls=0, hypotheses=3, matches=0
    )
    match_limited = BudgetLedger(policy=BudgetPolicy(max_matches=4)).settle(
        cost_usd=Decimal(0), model_calls=0, hypotheses=0, matches=4
    )

    assert hypothesis_limited.hard_limit_reached
    assert match_limited.hard_limit_reached


# Mutation caught: token limits are collapsed into model-call or USD accounting.
def test_input_and_output_token_limits_are_independent_hard_limits() -> None:
    input_limited = BudgetLedger(policy=BudgetPolicy(max_input_tokens=10)).settle(
        cost_usd=Decimal(0), model_calls=0, input_tokens=10
    )
    output_limited = BudgetLedger(policy=BudgetPolicy(max_output_tokens=20)).settle(
        cost_usd=Decimal(0), model_calls=0, output_tokens=20
    )

    assert input_limited.hard_limit_reached
    assert output_limited.hard_limit_reached


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
