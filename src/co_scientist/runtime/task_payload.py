"""Immutable execution snapshots stored in Supervisor-created tasks."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from co_scientist.agents.payloads import CoreOutputSchemaId
from co_scientist.domain.budget import BudgetEstimate
from co_scientist.runtime.external_calls import request_fingerprint


class WorkerTaskPayload(BaseModel):
    """Immutable identity and inputs required to execute one task."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    skill_id: str
    skill_version: str
    output_schema_id: CoreOutputSchemaId
    output_schema_version: int = Field(ge=1)
    research_plan_version: int = Field(ge=1)
    provider_id: str
    model_or_tool: str
    inputs: dict[str, Any]
    input_snapshot_hash: str
    prompt_hash: str
    budget_estimate: BudgetEstimate

    @model_validator(mode="after")
    def validate_input_snapshot(self) -> WorkerTaskPayload:
        if request_fingerprint(self.inputs) != self.input_snapshot_hash:
            raise ValueError("task input snapshot hash does not match inputs")
        return self
