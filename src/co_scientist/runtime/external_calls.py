"""Raw-first execution and recovery for external calls."""

import hashlib
import json
from collections.abc import Callable, Mapping
from typing import Any
from uuid import uuid4

from co_scientist.adapters.persistence.sqlite import PersistedExternalCall
from co_scientist.agents.result import AgentExecutionContext, AgentResult
from co_scientist.domain.states import ExternalCallState
from co_scientist.ports.artifact_store import ArtifactRef, RawArtifactManifest
from co_scientist.ports.external_provider import ExternalProvider

Validator = Callable[[bytes], Mapping[str, Any]]


def request_fingerprint(request: dict[str, Any]) -> str:
    """Hash the canonical JSON representation of a provider request."""

    canonical = json.dumps(request, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def execution_context_fingerprint(context: Mapping[str, Any]) -> str:
    """Hash a canonical execution-context document for artifact provenance."""

    return request_fingerprint(dict(context))


class ExternalCallRunner:
    """Advance durable external calls without repeating committed work."""

    def __init__(self, runtime: Any) -> None:
        self.uow = runtime.uow
        self.artifacts = runtime.artifacts

    @staticmethod
    def _context_data(context: AgentExecutionContext) -> dict[str, Any]:
        return context.model_dump(mode="json")

    def _assert_context(
        self,
        call: PersistedExternalCall,
        context: AgentExecutionContext,
    ) -> None:
        if (
            context.run_id != call.run_id
            or context.task_id != call.task_id
            or context.idempotency_key != call.task_idempotency_key
            or (
                call.execution_context is not None
                and dict(call.execution_context) != self._context_data(context)
            )
        ):
            raise ValueError(f"call {call.external_call_id} execution context mismatch")

    @staticmethod
    def _assert_fingerprint(call: PersistedExternalCall, fingerprint: str) -> None:
        if call.request_fingerprint != fingerprint:
            raise ValueError(f"call {call.external_call_id} request fingerprint mismatch")

    @staticmethod
    def _assert_manifest_provenance(
        call: PersistedExternalCall,
        manifest: RawArtifactManifest,
        context: AgentExecutionContext,
    ) -> None:
        expected_context_fingerprint = execution_context_fingerprint(
            context.model_dump(mode="json")
        )
        if (
            manifest.request_fingerprint != call.request_fingerprint
            or manifest.run_id != call.run_id
            or manifest.task_id != call.task_id
            or manifest.execution_context_fingerprint != expected_context_fingerprint
        ):
            raise ValueError(
                f"call {call.external_call_id} raw manifest provenance mismatch"
            )

    @staticmethod
    def _build_result(
        call_id: str,
        ref: ArtifactRef,
        payload: Mapping[str, Any],
        context: AgentExecutionContext,
    ) -> AgentResult:
        return AgentResult(
            result_id=str(uuid4()),
            external_call_id=call_id,
            raw_artifact_ref=ref,
            status="completed",
            payload=payload,
            **context.model_dump(),
        )

    @staticmethod
    def _persisted_result(
        call: PersistedExternalCall,
        context: AgentExecutionContext,
    ) -> AgentResult:
        if call.agent_result is not None:
            return AgentResult.model_validate(call.agent_result)
        if (
            call.agent_result_id is None
            or call.raw_artifact_ref is None
            or call.validated_payload is None
        ):
            raise ValueError(f"call {call.external_call_id} has incomplete legacy result data")
        return AgentResult(
            result_id=call.agent_result_id,
            external_call_id=call.external_call_id,
            raw_artifact_ref=call.raw_artifact_ref,
            status="completed",
            payload=call.validated_payload,
            **context.model_dump(),
        )

    def _validate_and_submit(
        self,
        call_id: str,
        ref: ArtifactRef,
        validator: Validator,
        context: AgentExecutionContext,
    ) -> AgentResult:
        raw_body = self.artifacts.read(ref)
        try:
            payload = validator(raw_body)
            result = self._build_result(call_id, ref, payload, context)
        except Exception:
            self.uow.transition_call(call_id, ExternalCallState.VALIDATION_FAILED)
            raise
        self.uow.record_validated_and_submitted(call_id, payload, result)
        return result

    def _submit_legacy_validated(
        self,
        call: PersistedExternalCall,
        context: AgentExecutionContext,
    ) -> AgentResult:
        if call.raw_artifact_ref is None or call.validated_payload is None:
            raise ValueError(f"call {call.external_call_id} has incomplete validated data")
        result = self._build_result(
            call.external_call_id,
            call.raw_artifact_ref,
            call.validated_payload,
            context,
        )
        self.uow.record_submitted_result(call.external_call_id, result)
        return result

    async def _invoke_provider(
        self,
        *,
        call_id: str,
        request: dict[str, Any],
        provider: ExternalProvider,
        validator: Validator,
        context: AgentExecutionContext,
    ) -> AgentResult:
        try:
            raw = await provider.invoke(request)
        except Exception:
            self.uow.transition_call(call_id, ExternalCallState.FAILED_BEFORE_RESPONSE)
            raise
        try:
            ref = self.artifacts.persist_raw(
                call_id,
                raw.body,
                raw.mime_type,
                request_fingerprint=request_fingerprint(request),
                run_id=context.run_id,
                task_id=context.task_id,
                execution_context_fingerprint=execution_context_fingerprint(
                    self._context_data(context)
                ),
                provider_response_id=raw.provider_response_id,
                usage=raw.usage,
            )
        except Exception as persist_error:  # noqa: BLE001 - adapter boundary recovery
            try:
                call = self.uow.get_external_call(call_id)
                manifest = self.artifacts.discover_raw(call_id)
                if manifest is None:
                    raise ValueError("no durable raw manifest")
                self._assert_manifest_provenance(call, manifest, context)
            except (AttributeError, OSError, ValueError):
                self.uow.transition_call(call_id, ExternalCallState.RAW_PERSIST_FAILED)
                raise persist_error
            self.uow.record_raw_and_transition(
                call_id,
                manifest.artifact_ref,
                ExternalCallState.RAW_RESPONSE_PERSISTED,
                provider_response_id=manifest.provider_response_id,
                usage=manifest.usage,
            )
            return self._validate_and_submit(
                call_id,
                manifest.artifact_ref,
                validator,
                context,
            )
        self.uow.record_raw_and_transition(
            call_id,
            ref,
            ExternalCallState.RAW_RESPONSE_PERSISTED,
            provider_response_id=raw.provider_response_id,
            usage=raw.usage,
        )
        return self._validate_and_submit(call_id, ref, validator, context)

    async def _continue(
        self,
        call: PersistedExternalCall,
        *,
        request: dict[str, Any] | None,
        provider: ExternalProvider,
        validator: Validator,
        context: AgentExecutionContext,
        allow_provider_call: bool,
    ) -> AgentResult:
        state = call.state
        if state is ExternalCallState.PLANNED:
            if not allow_provider_call or request is None:
                raise ValueError(f"call {call.external_call_id} has no durable raw response")
            self.uow.transition_call(call.external_call_id, ExternalCallState.STARTED)
            return await self._invoke_provider(
                call_id=call.external_call_id,
                request=request,
                provider=provider,
                validator=validator,
                context=context,
            )
        if state is ExternalCallState.STARTED:
            manifest = self.artifacts.discover_raw(call.external_call_id)
            if manifest is not None:
                self._assert_manifest_provenance(call, manifest, context)
                self.uow.record_raw_and_transition(
                    call.external_call_id,
                    manifest.artifact_ref,
                    ExternalCallState.RAW_RESPONSE_PERSISTED,
                    provider_response_id=manifest.provider_response_id,
                    usage=manifest.usage,
                )
                return self._validate_and_submit(
                    call.external_call_id,
                    manifest.artifact_ref,
                    validator,
                    context,
                )
            if not allow_provider_call or request is None:
                raise ValueError(f"call {call.external_call_id} has no durable raw response")
            return await self._invoke_provider(
                call_id=call.external_call_id,
                request=request,
                provider=provider,
                validator=validator,
                context=context,
            )
        if state is ExternalCallState.RAW_RESPONSE_PERSISTED:
            if call.raw_artifact_ref is None:
                raise ValueError(f"call {call.external_call_id} has no persisted raw artifact")
            return self._validate_and_submit(
                call.external_call_id,
                call.raw_artifact_ref,
                validator,
                context,
            )
        if state is ExternalCallState.VALIDATED:
            return self._submit_legacy_validated(call, context)
        if state in {
            ExternalCallState.AGENT_RESULT_SUBMITTED,
            ExternalCallState.DOMAIN_RESULT_APPLIED,
        }:
            return self._persisted_result(call, context)
        raise ValueError(f"call {call.external_call_id} cannot resume from state {state.value}")

    async def execute(
        self,
        *,
        call_id: str,
        request: dict[str, Any],
        provider: ExternalProvider,
        validator: Validator,
        context: AgentExecutionContext,
    ) -> AgentResult:
        fingerprint = request_fingerprint(request)
        try:
            call = self.uow.get_external_call(call_id)
        except KeyError:
            self.uow.plan_external_call(
                call_id,
                fingerprint,
                run_id=context.run_id,
                task_id=context.task_id,
                execution_context=self._context_data(context),
            )
            self.uow.transition_call(call_id, ExternalCallState.STARTED)
            return await self._invoke_provider(
                call_id=call_id,
                request=request,
                provider=provider,
                validator=validator,
                context=context,
            )
        self._assert_fingerprint(call, fingerprint)
        self._assert_context(call, context)
        return await self._continue(
            call,
            request=request,
            provider=provider,
            validator=validator,
            context=context,
            allow_provider_call=True,
        )

    async def resume(
        self,
        call_id: str,
        *,
        provider: ExternalProvider,
        validator: Validator,
        context: AgentExecutionContext,
    ) -> AgentResult:
        call = self.uow.get_external_call(call_id)
        self._assert_context(call, context)
        return await self._continue(
            call,
            request=None,
            provider=provider,
            validator=validator,
            context=context,
            allow_provider_call=False,
        )
