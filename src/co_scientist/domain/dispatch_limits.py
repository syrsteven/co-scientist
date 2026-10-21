"""Opt-in immutable operational envelope, separate from scientific scheduling."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from co_scientist.domain.pilot_pricing import (
    DeepSeekPilotPricing,
    OpenAIJudgePilotPricing,
    SolGenerationPricing,
)


class DispatchLimits(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal["bounded-dispatch-v1"] = "bounded-dispatch-v1"
    max_model_calls: int = Field(ge=1)
    max_literature_calls: int = Field(ge=0)
    max_input_tokens: int = Field(ge=1)
    max_output_tokens: int = Field(ge=1)
    max_usd: Decimal = Field(gt=0)
    max_wall_seconds: int = Field(ge=1)
    output_tokens_per_call: int = Field(ge=1)
    pricing: DeepSeekPilotPricing | OpenAIJudgePilotPricing | SolGenerationPricing

    @model_validator(mode="after")
    def validate_bound(self) -> "DispatchLimits":
        if self.pricing.input_token_limit is None:
            raise ValueError("bounded dispatch requires a frozen input-token limit")
        if self.pricing.reserve_usd_per_call < self.pricing.minimum_reserve(
            self.output_tokens_per_call
        ):
            raise ValueError("dispatch reserve is below bounded input/output price")
        return self
