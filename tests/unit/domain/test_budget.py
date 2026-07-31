from decimal import Decimal

from co_scientist.domain.budget import BudgetLedger, BudgetPolicy


def test_null_cost_limit_is_unlimited_but_usage_is_recorded() -> None:
    ledger = BudgetLedger(policy=BudgetPolicy(max_usd=None))

    updated = ledger.settle(cost_usd=Decimal("12.34"), model_calls=1)

    assert updated.cost_usd == Decimal("12.34")
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
