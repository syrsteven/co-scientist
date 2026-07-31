from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class BudgetPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_usd: Decimal | None = None
    max_model_calls: int | None = None
    max_hypotheses: int | None = None
    max_matches: int | None = None


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
    hypotheses: int = 0
    matches: int = 0

    def settle(
        self,
        *,
        cost_usd: Decimal,
        model_calls: int,
        hypotheses: int = 0,
        matches: int = 0,
    ) -> "BudgetLedger":
        return self.model_copy(
            update={
                "cost_usd": self.cost_usd + cost_usd,
                "model_calls": self.model_calls + model_calls,
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
            self.policy.max_hypotheses is not None
            and self.hypotheses >= self.policy.max_hypotheses
        ) or (
            self.policy.max_matches is not None and self.matches >= self.policy.max_matches
        )
