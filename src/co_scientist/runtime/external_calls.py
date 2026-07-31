"""Raw-first execution and recovery for external calls."""

import hashlib
import json
from typing import Any
from uuid import uuid4

from co_scientist.agents.result import AgentExecutionContext, AgentResult
from co_scientist.ports.artifact_store import ArtifactRef
from co_scientist.ports.external_provider import ExternalProvider


def request_fingerprint(request: dict[str, Any]) -> str:
    """Hash the canonical JSON representation of a provider request."""

    canonical = json.dumps(request, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ExternalCallRunner:
    """Persist external-call bytes before interpreting them."""

    def __init__(self, runtime: Any) -> None:
        self.uow = runtime.uow
        self.artifacts = runtime.artifacts

    def _validate_and_submit(
        self,
        call_id: str,
        ref: ArtifactRef,
        validator: Any,
        context: AgentExecutionContext,
    ) -> AgentResult:
        try:
            payload = validator(self.artifacts.read(ref))
            self.uow.record_validated(call_id, payload)
        except Exception:
            self.uow.transition_call(call_id, "validation_failed")
            raise
        result = AgentResult(
            result_id=str(uuid4()),
            external_call_id=call_id,
            raw_artifact_ref=ref.path,
            status="completed",
            payload=payload,
            **context.model_dump(),
        )
        try:
            self.uow.record_submitted_result(call_id, result)
        except Exception:
            self.uow.transition_call(call_id, "submission_failed")
            raise
        return result

    async def execute(
        self,
        *,
        call_id: str,
        request: dict[str, Any],
        provider: ExternalProvider,
        validator: Any,
        context: AgentExecutionContext,
    ) -> AgentResult:
        self.uow.plan_external_call(
            call_id,
            request_fingerprint(request),
            task_id=context.task_id,
        )
        self.uow.transition_call(call_id, "started")
        try:
            raw = await provider.invoke(request)
        except Exception:
            self.uow.transition_call(call_id, "failed_before_response")
            raise
        try:
            ref = self.artifacts.persist_raw(call_id, raw.body, raw.mime_type)
            self.uow.record_raw_and_transition(
                call_id,
                ref,
                "raw_response_persisted",
                provider_response_id=raw.provider_response_id,
                usage=raw.usage,
            )
        except Exception:
            self.uow.transition_call(call_id, "raw_persist_failed")
            raise
        return self._validate_and_submit(call_id, ref, validator, context)

    async def resume(
        self,
        call_id: str,
        *,
        provider: ExternalProvider,
        validator: Any,
        context: AgentExecutionContext,
    ) -> AgentResult:
        call = self.uow.get_external_call(call_id)
        if call.state != "raw_response_persisted" or call.raw_artifact_ref is None:
            raise ValueError(f"call {call_id} has no resumable raw response")
        return self._validate_and_submit(call_id, call.raw_artifact_ref, validator, context)
