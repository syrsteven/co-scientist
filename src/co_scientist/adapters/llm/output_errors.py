"""Distinct failures at provider transport and scientific validation boundaries."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class OutputContractError(ValueError):
    """Base class for output-contract failures; never implies a scientific retry."""


class ProviderSyntaxError(OutputContractError):
    """Raw provider payload or embedded JSON is syntactically invalid."""


class ProviderSchemaError(OutputContractError):
    """Provider envelope/result channel violates the selected provider contract."""


class DomainValidationError(OutputContractError):
    """Normalized value cannot represent the required local domain object."""


class ScientificValidationFailure(OutputContractError):
    """Normalized object violates a scientific/provenance/policy invariant."""


class StructuralRepairPolicy(BaseModel):
    """Future bounded re-ask design; disabled for paid/live execution by default."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool = False
    max_reasks: int = Field(default=1, ge=1, le=2)

    def may_reask(self, error: Exception, *, used: int) -> bool:
        return (
            self.enabled
            and used < self.max_reasks
            and isinstance(error, (ProviderSyntaxError, ProviderSchemaError))
        )
