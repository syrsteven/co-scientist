"""Immutable result envelope shared by workers and the supervisor."""

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from co_scientist.agents.payloads import CoreOutputSchemaId, validate_output_payload
from co_scientist.ports.artifact_store import ArtifactRef
from co_scientist.ports.external_provider import freeze_json, thaw_json


class AgentExecutionContext(BaseModel):
    """Traceability metadata attached to one agent execution."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    task_id: str
    idempotency_key: str
    skill_id: str
    skill_version: str
    output_schema_id: CoreOutputSchemaId
    output_schema_version: int
    research_plan_version: int = Field(ge=1)
    provider: str
    model_or_tool: str
    input_snapshot_hash: str
    prompt_hash: str | None = None


class AgentResult(BaseModel):
    """Immutable validated output submitted to the supervisor."""

    model_config = ConfigDict(frozen=True)

    result_id: str
    external_call_id: str
    run_id: str
    task_id: str
    idempotency_key: str
    skill_id: str
    skill_version: str
    output_schema_id: CoreOutputSchemaId
    output_schema_version: int
    research_plan_version: int = Field(ge=1)
    provider: str
    model_or_tool: str
    input_snapshot_hash: str
    prompt_hash: str | None = None
    status: Literal["completed", "partial", "rejected", "failed"]
    payload: Mapping[str, Any]
    evidence_refs: tuple[str, ...] = ()
    recommended_actions: tuple[str, ...] = ()
    raw_artifact_ref: ArtifactRef

    @field_validator("payload")
    @classmethod
    def freeze_payload(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        return freeze_json(value)

    @field_serializer("payload", when_used="json")
    def serialize_payload(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return thaw_json(value)

    @model_validator(mode="after")
    def validate_typed_payload(self) -> "AgentResult":
        validated = validate_output_payload(
            status=self.status,
            schema_id=self.output_schema_id,
            schema_version=self.output_schema_version,
            payload=self.payload,
        )
        payload_plan_version = getattr(validated, "research_plan_version", None)
        if (
            payload_plan_version is not None
            and payload_plan_version != self.research_plan_version
        ):
            raise ValueError("payload research plan version does not match execution context")
        return self
