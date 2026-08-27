from pydantic import BaseModel

from co_scientist.domain.states import ExternalCallState


class ExternalCall(BaseModel):
    external_call_id: str
    task_id: str
    attempt: int
    request_fingerprint: str
    provider: str
    model_or_tool: str
    state: ExternalCallState = ExternalCallState.PLANNED
    raw_artifact_ref: str | None = None
    validated_artifact_ref: str | None = None
    agent_result_id: str | None = None
    applied_domain_sequence: int | None = None
    parent_call_id: str | None = None
