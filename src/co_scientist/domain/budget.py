from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class BudgetEstimate(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_calls: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_usd: Decimal = Field(default=Decimal(0), ge=0)
    hypotheses: int = Field(default=0, ge=0)
    matches: int = Field(default=0, ge=0)


class BudgetUsage(BudgetEstimate):
    pass


def add_budget_usage(left: BudgetEstimate, right: BudgetEstimate) -> BudgetUsage:
    """Add all six budget dimensions without collapsing independent limits."""

    return BudgetUsage(
        model_calls=left.model_calls + right.model_calls,
        input_tokens=left.input_tokens + right.input_tokens,
        output_tokens=left.output_tokens + right.output_tokens,
        cost_usd=left.cost_usd + right.cost_usd,
        hypotheses=left.hypotheses + right.hypotheses,
        matches=left.matches + right.matches,
    )


class BudgetPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_usd: Decimal | None = Field(default=None, ge=0)
    max_model_calls: int | None = Field(default=None, ge=0)
    max_input_tokens: int | None = Field(default=None, ge=0)
    max_output_tokens: int | None = Field(default=None, ge=0)
    max_hypotheses: int | None = Field(default=None, ge=0)
    max_matches: int | None = Field(default=None, ge=0)

    def reached(self, usage: BudgetEstimate) -> bool:
        checks = (
            (self.max_usd, usage.cost_usd),
            (self.max_model_calls, usage.model_calls),
            (self.max_input_tokens, usage.input_tokens),
            (self.max_output_tokens, usage.output_tokens),
            (self.max_hypotheses, usage.hypotheses),
            (self.max_matches, usage.matches),
        )
        return any(limit is not None and actual >= limit for limit, actual in checks)


class DurableBudgetSnapshot(BaseModel):
    """Restart-stable budget facts reconstructed from the durable ledger."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    policy_version: str
    settled: BudgetUsage
    actively_reserved: BudgetEstimate
    hard_limit_reached: bool
    source_reservation_ids: tuple[str, ...]
    source_cost_entry_ids: tuple[str, ...]

    @property
    def total_usage(self) -> BudgetUsage:
        return add_budget_usage(self.settled, self.actively_reserved)


class CostEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    cost_entry_id: str
    run_id: str
    external_call_id: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal(0)
    pricing_version: str
