"""Opt-in conservative price snapshot for bounded DeepSeek pilot calls.

This is a dated estimate, not a vendor invoice or an account-level spending cap.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SerializerFunctionWrapHandler, model_serializer


class BoundedPricing(BaseModel):
    input_token_limit: int | None = Field(default=None, ge=4097, le=1000000)

    @model_serializer(mode="wrap")
    def serialize_bounds(self, handler: SerializerFunctionWrapHandler) -> dict:
        value = handler(self)
        if self.input_token_limit is None:
            value.pop("input_token_limit", None)
        return value


class DeepSeekPilotPricing(BoundedPricing):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = Field(min_length=1)
    model: Literal["deepseek-flash"] = "deepseek-flash"
    checked_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    source_url: str = Field(pattern=r"^https://")
    input_usd_per_million: Decimal = Field(ge=Decimal("0.30"))
    output_usd_per_million: Decimal = Field(ge=Decimal("1.20"))
    max_context_tokens: Literal[1000000] = 1000000
    reserve_usd_per_call: Decimal = Field(gt=0)

    def minimum_reserve(self, max_output_tokens: int) -> Decimal:
        return (
            Decimal(self.input_token_limit or self.max_context_tokens) * self.input_usd_per_million
            + Decimal(max_output_tokens) * self.output_usd_per_million
        ) / Decimal(1_000_000)

    def conservative_cost(
        self, *, input_tokens: int | None, output_tokens: int | None,
        max_output_tokens: int,
    ) -> Decimal:
        """Use full uncached peak rates; unknown usage consumes the reserved bound."""

        if input_tokens is None or output_tokens is None:
            return self.reserve_usd_per_call
        return (
            Decimal(input_tokens) * self.input_usd_per_million
            + Decimal(output_tokens) * self.output_usd_per_million
        ) / Decimal(1_000_000)


class OpenAIJudgePilotPricing(BoundedPricing):
    """Long-context/cache-write upper tier for the optional blinded judge."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = Field(min_length=1)
    model: Literal["gpt-5.6-terra"] = "gpt-5.6-terra"
    checked_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    source_url: str = Field(pattern=r"^https://")
    input_usd_per_million: Decimal = Field(ge=Decimal("5.00"))
    output_usd_per_million: Decimal = Field(ge=Decimal("18.00"))
    max_context_tokens: Literal[1050000] = 1050000
    reserve_usd_per_call: Decimal = Field(gt=0)

    def minimum_reserve(self, max_output_tokens: int) -> Decimal:
        return (
            Decimal(self.input_token_limit or self.max_context_tokens) * self.input_usd_per_million
            + Decimal(max_output_tokens) * self.output_usd_per_million
        ) / Decimal(1_000_000)

    def conservative_cost(
        self, *, input_tokens: int | None, output_tokens: int | None,
    ) -> Decimal:
        if input_tokens is None or output_tokens is None:
            return self.reserve_usd_per_call
        return (
            Decimal(input_tokens) * self.input_usd_per_million
            + Decimal(output_tokens) * self.output_usd_per_million
        ) / Decimal(1_000_000)


class SolGenerationPricing(BoundedPricing):
    """Versioned performance-only conservative uncached/cache-write bound."""

    model: Literal["gpt-6.1-sol"] = "gpt-6.1-sol"
    model_config = ConfigDict(frozen=True, extra="forbid")
    version: str = Field(min_length=1)
    checked_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    source_url: str = Field(pattern=r"^https://")
    max_context_tokens: Literal[1050000] = 1050000
    reserve_usd_per_call: Decimal = Field(gt=0)
    input_usd_per_million: Decimal = Field(default=Decimal("2.50"), ge=Decimal("2.50"), le=Decimal("2.50"))
    output_usd_per_million: Decimal = Field(default=Decimal(10), ge=Decimal(10), le=Decimal(10))

    def minimum_reserve(self, max_output_tokens: int) -> Decimal:
        return (Decimal(self.input_token_limit or self.max_context_tokens)*self.input_usd_per_million
                + Decimal(max_output_tokens)*self.output_usd_per_million)/1000000

    def conservative_cost(self, *, input_tokens: int | None, output_tokens: int | None) -> Decimal:
        if input_tokens is None or output_tokens is None:
            raise ValueError("unknown cost must retain reservation, not settle")
        return (input_tokens*self.input_usd_per_million + output_tokens*self.output_usd_per_million)/1000000


def effective_task_pricing(task: Mapping[str, Any]) -> DeepSeekPilotPricing | SolGenerationPricing:
    """Adapter to existing accounting, not a rewrite of historical snapshots."""
    price, role = task["pricing"], task["runtime"]
    pricing_class = SolGenerationPricing if task.get("version") == "generation-performance-v1" else DeepSeekPilotPricing
    return pricing_class(version=price["version"], model=price["model"],
        checked_at=price["checked_at"], source_url=price["source_url"],
        input_usd_per_million=price["input_usd_per_million"],
        output_usd_per_million=price["output_usd_per_million"],
        input_token_limit=role["max_input_tokens"], reserve_usd_per_call=task["reserved_usd"])
