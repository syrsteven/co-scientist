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


class BudgetPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_usd: Decimal | None = Field(default=None, ge=0)
    max_model_calls: int | None = Field(default=None, ge=0)
    max_input_tokens: int | None = Field(default=None, ge=0)
    max_output_tokens: int | None = Field(default=None, ge=0)
    max_hypotheses: int | None = Field(default=None, ge=0)
    max_matches: int | None = Field(default=None, ge=0)


class CostEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    cost_entry_id: str
    run_id: str
    external_call_id: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal(0)
    pricing_version: str


class BudgetLedger(BaseModel):
    model_config = ConfigDict(frozen=True)

    policy: BudgetPolicy
    cost_usd: Decimal = Decimal(0)
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    hypotheses: int = 0
    matches: int = 0

    def settle(
        self,
        *,
        cost_usd: Decimal,
        model_calls: int,
        input_tokens: int = 0,
        output_tokens: int = 0,
        hypotheses: int = 0,
        matches: int = 0,
    ) -> "BudgetLedger":
        return self.model_copy(
            update={
                "cost_usd": self.cost_usd + cost_usd,
                "model_calls": self.model_calls + model_calls,
                "input_tokens": self.input_tokens + input_tokens,
                "output_tokens": self.output_tokens + output_tokens,
                "hypotheses": self.hypotheses + hypotheses,
                "matches": self.matches + matches,
            }
        )

    @property
    def hard_limit_reached(self) -> bool:
        return (self.policy.max_usd is not None and self.cost_usd >= self.policy.max_usd) or (
            self.policy.max_model_calls is not None
            and self.model_calls >= self.policy.max_model_calls
        ) or (
            self.policy.max_input_tokens is not None
            and self.input_tokens >= self.policy.max_input_tokens
        ) or (
            self.policy.max_output_tokens is not None
            and self.output_tokens >= self.policy.max_output_tokens
        ) or (
            self.policy.max_hypotheses is not None
            and self.hypotheses >= self.policy.max_hypotheses
        ) or (
            self.policy.max_matches is not None and self.matches >= self.policy.max_matches
        )
