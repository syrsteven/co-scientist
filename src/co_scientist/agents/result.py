"""Immutable result envelope shared by workers and the supervisor."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class AgentExecutionContext(BaseModel):
    """Traceability metadata attached to one agent execution."""

    model_config = ConfigDict(frozen=True)

    task_id: str
    idempotency_key: str
    skill_id: str
    skill_version: str
    output_schema_version: int
    input_snapshot_hash: str


class AgentResult(BaseModel):
    """Immutable validated output submitted to the supervisor."""

    model_config = ConfigDict(frozen=True)

    result_id: str
    external_call_id: str
    task_id: str
    idempotency_key: str
    skill_id: str
    skill_version: str
    output_schema_version: int
    input_snapshot_hash: str
    status: Literal["completed", "partial", "rejected", "failed"]
    payload: dict[str, Any]
    evidence_refs: tuple[str, ...] = ()
    recommended_actions: tuple[str, ...] = ()
    raw_artifact_ref: str
