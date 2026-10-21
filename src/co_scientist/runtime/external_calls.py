"""Raw-first execution and recovery for external calls."""

import hashlib
import json
from collections.abc import Callable, Mapping
from contextlib import nullcontext
from decimal import Decimal
from typing import Any
from uuid import uuid4

from co_scientist.adapters.persistence.sqlite import PersistedExternalCall
from co_scientist.agents.result import AgentExecutionContext, AgentResult
from co_scientist.domain.states import ExternalCallState
from co_scientist.domain.task import TaskLeaseFence, lease_fence_fingerprint
from co_scientist.ports.artifact_store import ArtifactRef, RawArtifactManifest
from co_scientist.ports.external_provider import (
    CapturedHTTPResponseV2,
    ExternalProvider,
    HTTPResponseCaptureError,
    RawExternalResponse,
    controlled_http_capture,
    thaw_json,
)
from co_scientist.runtime.transport_observability import (
    ExternalCallObservationContext,
    failure_diagnostic_for_exception,
    observe_external_call,
    record_transport_milestone,
)

Validator = Callable[[bytes], Mapping[str, Any]]
WriteGuard = Callable[[], None]


def request_fingerprint(request: dict[str, Any]) -> str:
    """Hash the canonical JSON representation of a provider request."""

    canonical = json.dumps(request, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def execution_context_fingerprint(context: Mapping[str, Any]) -> str:
    """Hash a canonical execution-context document for artifact provenance."""

    return request_fingerprint(dict(context))


def provider_configuration_fingerprint(configuration: dict[str, Any]) -> str:
    """Normalize exact Decimal prices; never alter the provider request fingerprint."""
    def encode(value: Any) -> str:
        if isinstance(value, Decimal) and value.is_finite():
            return str(value)
        raise TypeError("unsupported provider configuration value")
    normalized = json.loads(json.dumps(configuration, default=encode))
    return request_fingerprint(normalized)


def prompt_hash(prompt: str) -> str:
    """Hash the exact UTF-8 prompt bytes bound to one external request."""

    return "sha256:" + hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def baseline_task_call_history(uow: Any, *, run_id: str, task_id: str,
                               through_attempt: int | None = None
                               ) -> tuple[PersistedExternalCall, ...]:
    """Read all durable attempts before recovery can alter leases/reservations."""
    from co_scientist.adapters.persistence.sqlite import TaskRow

    with uow.session_factory() as session:
        row = session.get(TaskRow, task_id)
        if row is None or row.run_id != run_id:
            raise ValueError("missing durable task attempt authority")
        last = max(row.attempt, through_attempt or 0)
    return tuple(call for attempt in range(1, last + 1)
        if (call := uow.external_call_for_task_attempt(
            run_id=run_id, task_id=task_id, attempt=attempt)) is not None)


def assert_baseline_no_unknown_delivery(runtime: Any, *, run_id: str, task_id: str,
                                        through_attempt: int | None = None) -> None:
    """No inferred usage/refund, and HTTP artifacts are not domain raw authority."""
    from co_scientist.domain.ideation_core_boundary import batch2_execution_enabled

    if not batch2_execution_enabled(runtime.uow.run_manifest(run_id)):
        return
    from co_scientist.domain.continuous_execution import policy_for

    if policy_for(runtime.uow.run_manifest(run_id)) is not None and runtime.uow.task_state(task_id) == "failed":
        return  # Durable technical closure; unknown cost remains reserved.
    history = baseline_task_call_history(runtime.uow, run_id=run_id, task_id=task_id,
                                         through_attempt=through_attempt)
    with runtime.uow.session_factory() as session:
        from co_scientist.adapters.persistence.sqlite import TaskRow

        row = session.get(TaskRow, task_id)
        if row is None:
            raise ValueError("missing durable task attempt authority")
        current_attempt = max(row.attempt, through_attempt or 0)
        if runtime.uow.run_manifest(run_id).get("effective_execution_config", {}).get("continuous_policy"):
            current_attempt = max(current_attempt, json.loads(row.payload_json).get("inputs", {})
                .get("ideation_task_binding", {}).get("attempt", current_attempt))
    for call in history:
        from co_scientist.domain.continuous_execution import policy_for

        if policy_for(runtime.uow.run_manifest(run_id)) is not None and call.attempt < current_attempt:
            approved = [e for e in runtime.uow.load(run_id) if e.event_type == "ContinuousAttemptPreparedV1"
                and e.payload["external_call_id"] == call.external_call_id
                and e.payload["authorized_attempt"] == call.attempt+1]
            if len(approved) == 1 and call.applied_domain_sequence is None and (
                    call.agent_result is None or approved[0].payload["reason"].startswith("RETRIEVAL_")):
                continue
        if call.state == ExternalCallState.VALIDATION_FAILED:
            if runtime.uow.task_state(task_id) == "failed":
                continue  # Already contained; only an unresolved crash boundary blocks recovery.
            raise ValueError("INVALID_RESULT_REQUIRES_CONTAINMENT: never retry a scientific/schema failure")
        if call.state not in {ExternalCallState.STARTED, ExternalCallState.FAILED_BEFORE_RESPONSE,
                              ExternalCallState.RAW_PERSIST_FAILED,
                              ExternalCallState.HTTP_CAPTURE_STARTED_V2,
                              ExternalCallState.HTTP_CAPTURE_FAILED_V2}:
            if call.attempt < current_attempt and call.state != ExternalCallState.PLANNED:
                raise ValueError("PREVIOUS_ATTEMPT_REPLAY_REQUIRED: never resend completed domain raw")
            continue
        if call.raw_artifact_ref is None:
            manifest = runtime.artifacts.discover_raw(call.external_call_id)
            if manifest is None:
                http_capture = runtime.artifacts.discover_raw(call.external_call_id + ":http-v2")
                if http_capture is None:
                    raise ValueError("DELIVERY_UNKNOWN: baseline forbids across-attempt resend")
                context = AgentExecutionContext.model_validate(call.execution_context)
                if (http_capture.call_id != call.external_call_id + ":http-v2"
                        or http_capture.run_id != call.run_id
                        or http_capture.task_id != call.task_id
                        or http_capture.request_fingerprint != call.request_fingerprint
                        or http_capture.execution_context_fingerprint
                            != execution_context_fingerprint(context.model_dump(mode="json"))
                        or http_capture.usage.get("version") != 2):
                    raise ValueError("HTTP capture provenance mismatch")
                runtime.artifacts.read(http_capture.artifact_ref)
                if call.attempt < current_attempt:
                    raise ValueError("PREVIOUS_ATTEMPT_REPLAY_REQUIRED: never rebind capture")
                continue
            context = AgentExecutionContext.model_validate(call.execution_context)
            ExternalCallRunner._assert_manifest_provenance(call, manifest, context)
        if call.attempt < current_attempt:
            raise ValueError("PREVIOUS_ATTEMPT_REPLAY_REQUIRED: never resend completed domain raw")


class ExternalCallRunner:
    """Advance durable external calls without repeating committed work."""

    def __init__(self, runtime: Any) -> None:
        self.uow = runtime.uow
        self.artifacts = runtime.artifacts

    def _http_capture_enabled(self, provider: Any, run_id: str) -> bool:
        if not callable(getattr(provider, "parse_captured_response", None)):
            return False
        if getattr(provider, "response_capture_version", None) == 2:
            return True
        from co_scientist.domain.ideation_core_boundary import batch2_execution_enabled

        return batch2_execution_enabled(self.uow.run_manifest(run_id))

    def _capture_http_v2(self, call_id: str, response: CapturedHTTPResponseV2,
                         request: dict[str, Any], provider: Any,
                         context: AgentExecutionContext, reservation_id: str,
                         fence: TaskLeaseFence, write_guard: WriteGuard | None) -> None:
        self._guard(write_guard)
        self.uow.assert_external_call_fence(call_id=call_id, reservation_id=reservation_id,
                                            fence=fence)
        call = self.uow.get_external_call(call_id)
        self._assert_context(call, context)
        self._assert_fingerprint(call, request_fingerprint(request))
        if provider.provider != context.provider or request.get("model") != context.model_or_tool:
            raise ValueError("capture provider identity mismatch")
        metadata = {"version": 2, "status": response.status, "headers": dict(response.headers),
                    "request": request, "provider": context.provider,
                    "model": context.model_or_tool, "attempt": context.attempt,
                    "provider_configuration_hash": provider_configuration_fingerprint(provider.generation)}
        capture_id = call_id + ":http-v2"
        manifest = self.artifacts.discover_raw(capture_id)
        if manifest is None:
            self.artifacts.persist_raw(capture_id, response.body, "application/octet-stream",
                request_fingerprint=call.request_fingerprint, run_id=context.run_id,
                task_id=context.task_id, execution_context_fingerprint=execution_context_fingerprint(
                    self._context_data(context)), usage=metadata)
            manifest = self.artifacts.discover_raw(capture_id)
            if manifest is None:
                raise ValueError("durable HTTP capture confirmation missing")
        else:
            if (self.artifacts.read(manifest.artifact_ref) != response.body
                    or manifest.usage.get("status") != response.status):
                raise ValueError("immutable HTTP capture conflict")
        self._assert_http_capture_v2(call, manifest, context, provider)
        fact = {k: manifest.usage[k] for k in ("version", "status", "headers", "provider",
                                              "model", "attempt", "provider_configuration_hash")}
        fact.update(artifact_ref=manifest.artifact_ref.model_dump(mode="json"),
                    request_fingerprint=manifest.request_fingerprint,
                    execution_context_fingerprint=manifest.execution_context_fingerprint,
                    run_id=manifest.run_id, task_id=manifest.task_id,
                    reservation_id=reservation_id)
        self.artifacts.confirm_raw(manifest)
        self.uow.record_http_capture_v2(call_id, fact, reservation_id=reservation_id, fence=fence)

    def _assert_http_capture_v2(self, call: PersistedExternalCall,
                               manifest: RawArtifactManifest, context: AgentExecutionContext,
                               provider: Any) -> None:
        self._assert_context(call, context)
        if (manifest.call_id != call.external_call_id + ":http-v2"
                or manifest.run_id != call.run_id or manifest.task_id != call.task_id
                or manifest.request_fingerprint != call.request_fingerprint
                or manifest.execution_context_fingerprint != execution_context_fingerprint(
                    self._context_data(context)) or manifest.usage.get("version") != 2
                or request_fingerprint(manifest.usage["request"]) != call.request_fingerprint
                or manifest.usage.get("provider") != call.provider
                or provider.provider != call.provider
                or manifest.usage.get("model") != call.model_or_tool
                or manifest.usage.get("attempt") != call.attempt
                or manifest.usage.get("provider_configuration_hash")
                    != provider_configuration_fingerprint(provider.generation)):
            raise ValueError("HTTP capture provenance mismatch")
        self.artifacts.read(manifest.artifact_ref)  # Verify body hash before interpretation.

    def _resume_http_v2(self, call: PersistedExternalCall, provider: Any,
                        context: AgentExecutionContext, reservation_id: str,
                        fence: TaskLeaseFence, write_guard: WriteGuard | None) -> RawExternalResponse:
        manifest = self.artifacts.discover_raw(call.external_call_id + ":http-v2")
        if manifest is None:
            raise ValueError("missing durable HTTP capture; never resend")
        self._assert_http_capture_v2(call, manifest, context, provider)
        response = CapturedHTTPResponseV2(body=self.artifacts.read(manifest.artifact_ref),
            status=manifest.usage["status"], headers=manifest.usage["headers"])
        self._capture_http_v2(call.external_call_id, response, manifest.usage["request"], provider,
                             context, reservation_id, fence, write_guard)
        raw = provider.parse_captured_response(response, manifest.usage["request"])
        fact = self.uow.get_external_call(call.external_call_id).usage["http_capture_v2"]
        return RawExternalResponse(body=raw.body, mime_type=raw.mime_type,
            provider_response_id=raw.provider_response_id,
            usage={**thaw_json(raw.usage), "http_capture_v2": fact})

    @staticmethod
    def _context_data(context: AgentExecutionContext) -> dict[str, Any]:
        return context.model_dump(mode="json")

    @staticmethod
    def _guard(write_guard: WriteGuard | None) -> None:
        if write_guard is not None:
            write_guard()

    def _record_failure_diagnostic(
        self,
        *,
        call_id: str,
        error: BaseException,
        reservation_id: str,
        fence: TaskLeaseFence,
    ) -> None:
        try:
            diagnostic = failure_diagnostic_for_exception(error)
            self.uow.record_external_call_failure_diagnostic(
                call_id,
                diagnostic.model_dump(mode="json"),
                reservation_id=reservation_id,
                fence=fence,
                capture_layer="external_call_runner",
            )
        except Exception:  # noqa: BLE001,S110 - preserve original exception/state path
            pass

    def _assert_context(
        self,
        call: PersistedExternalCall,
        context: AgentExecutionContext,
    ) -> None:
        terminal_legacy_states = {
            ExternalCallState.AGENT_RESULT_SUBMITTED,
            ExternalCallState.DOMAIN_RESULT_APPLIED,
        }
        allows_legacy_reconstruction = (
            call.execution_context is None
            and call.agent_result is None
            and call.state in terminal_legacy_states
        )
        if (
            context.run_id != call.run_id
            or context.task_id != call.task_id
            or context.idempotency_key != call.task_idempotency_key
            or context.provider != call.provider
            or context.model_or_tool != call.model_or_tool
            or (call.execution_context is None and not allows_legacy_reconstruction)
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
    def _assert_prompt_hash(
        request: Mapping[str, Any],
        context: AgentExecutionContext,
    ) -> None:
        prompt = request.get("system_prompt")
        if prompt is None:
            return
        if not isinstance(prompt, str):
            raise TypeError("system_prompt must be a string")
        if context.prompt_hash != prompt_hash(prompt):
            raise ValueError("execution context prompt hash does not match request")

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
            raise ValueError(f"call {call.external_call_id} raw manifest provenance mismatch")

    @staticmethod
    def _assert_manifest_matches_response(
        manifest: RawArtifactManifest,
        raw: RawExternalResponse,
    ) -> None:
        ref = manifest.artifact_ref
        expected_sha256 = "sha256:" + hashlib.sha256(raw.body).hexdigest()
        if (
            ref.sha256 != expected_sha256
            or ref.byte_length != len(raw.body)
            or ref.mime_type != raw.mime_type
            or manifest.provider_response_id != raw.provider_response_id
            or manifest.usage != thaw_json(raw.usage)
        ):
            raise ValueError("raw manifest does not match current provider response")

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
        reservation_id: str,
        fence: TaskLeaseFence,
        write_guard: WriteGuard | None,
    ) -> AgentResult:
        raw_body = self.artifacts.read(ref)
        try:
            payload = validator(raw_body)
            result = self._build_result(call_id, ref, payload, context)
        except Exception:
            self._guard(write_guard)
            self.uow.transition_call(
                call_id,
                ExternalCallState.VALIDATION_FAILED,
                reservation_id=reservation_id,
                fence=fence,
            )
            raise
        self._guard(write_guard)
        self.uow.record_validated_and_submitted(
            call_id,
            payload,
            result,
            reservation_id=reservation_id,
            fence=fence,
        )
        return result

    def _submit_legacy_validated(
        self,
        call: PersistedExternalCall,
        context: AgentExecutionContext,
        reservation_id: str,
        fence: TaskLeaseFence,
        write_guard: WriteGuard | None,
    ) -> AgentResult:
        if call.raw_artifact_ref is None or call.validated_payload is None:
            raise ValueError(f"call {call.external_call_id} has incomplete validated data")
        result = self._build_result(
            call.external_call_id,
            call.raw_artifact_ref,
            call.validated_payload,
            context,
        )
        self._guard(write_guard)
        self.uow.record_submitted_result(
            call.external_call_id,
            result,
            reservation_id=reservation_id,
            fence=fence,
        )
        return result

    async def _invoke_provider(
        self,
        *,
        call_id: str,
        request: dict[str, Any],
        provider: ExternalProvider,
        validator: Validator,
        context: AgentExecutionContext,
        reservation_id: str,
        fence: TaskLeaseFence,
        write_guard: WriteGuard | None,
    ) -> AgentResult:
        observation = ExternalCallObservationContext(
            run_id=context.run_id,
            task_id=context.task_id,
            external_call_id=call_id,
            reservation_id=reservation_id,
            fence=fence,
            record_milestone=self.uow.record_external_call_milestone,
        )
        with observe_external_call(observation):
            return await self._invoke_provider_observed(
                call_id=call_id,
                request=request,
                provider=provider,
                validator=validator,
                context=context,
                reservation_id=reservation_id,
                fence=fence,
                write_guard=write_guard,
            )

    async def _invoke_provider_observed(
        self,
        *,
        call_id: str,
        request: dict[str, Any],
        provider: ExternalProvider,
        validator: Validator,
        context: AgentExecutionContext,
        reservation_id: str,
        fence: TaskLeaseFence,
        write_guard: WriteGuard | None,
    ) -> AgentResult:
        try:
            capture_enabled = self._http_capture_enabled(provider, context.run_id)
            if capture_enabled:
                self.uow.start_http_capture_v2(call_id,
                    reservation_id=reservation_id, fence=fence)
            capture_scope = (controlled_http_capture(lambda response: self._capture_http_v2(
                call_id, response, request, provider, context, reservation_id, fence, write_guard))
                if capture_enabled else nullcontext())
            with capture_scope:
                raw = await provider.invoke(request)
            capture = self.uow.get_external_call(call_id).usage.get("http_capture_v2")
            if capture is not None:
                raw = RawExternalResponse(body=raw.body, mime_type=raw.mime_type,
                    provider_response_id=raw.provider_response_id,
                    usage={**thaw_json(raw.usage), "http_capture_v2": capture})
            record_transport_milestone("usage_parsed", source="external_call_runner")
        except Exception as error:
            self._guard(write_guard)
            from co_scientist.runtime.bounded_transport import ResponseCapacityError

            if isinstance(error, ResponseCapacityError):
                # Incomplete bytes are diagnostic only: never :http-v2/domain raw.
                self.artifacts.persist_raw(call_id + ":incomplete-http-v1", error.response_prefix,
                    "application/octet-stream", request_fingerprint=request_fingerprint(request),
                    run_id=context.run_id, task_id=context.task_id,
                    execution_context_fingerprint=execution_context_fingerprint(self._context_data(context)),
                    usage={"version": "incomplete-http-evidence-v1", "complete": False,
                           "http_status": error.http_status, "cost": "UNKNOWN"})
            self._record_failure_diagnostic(
                call_id=call_id,
                error=error,
                reservation_id=reservation_id,
                fence=fence,
            )
            captured = self.uow.get_external_call(call_id).state in {
                ExternalCallState.HTTP_RESPONSE_CAPTURED_V2,
                ExternalCallState.ACCOUNTING_INCOMPLETE_V2}
            self.uow.transition_call(
                call_id,
                ExternalCallState.ACCOUNTING_INCOMPLETE_V2 if captured
                    else (ExternalCallState.HTTP_CAPTURE_FAILED_V2
                          if isinstance(error, (HTTPResponseCaptureError, ResponseCapacityError))
                          else ExternalCallState.FAILED_BEFORE_RESPONSE),
                reservation_id=reservation_id,
                fence=fence,
            )
            raise
        try:
            self._guard(write_guard)
            self.uow.assert_external_call_fence(
                call_id=call_id,
                reservation_id=reservation_id,
                fence=fence,
            )
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
            record_transport_milestone("raw_persisted", source="external_call_runner")
        except Exception as persist_error:  # noqa: BLE001 - adapter boundary recovery
            try:
                call = self.uow.get_external_call(call_id)
                manifest = self.artifacts.discover_raw(call_id)
                if manifest is None:
                    raise ValueError("no durable raw manifest")
                self._assert_manifest_provenance(call, manifest, context)
                self._assert_manifest_matches_response(manifest, raw)
            except (AttributeError, OSError, ValueError):
                self._guard(write_guard)
                self._record_failure_diagnostic(
                    call_id=call_id,
                    error=persist_error,
                    reservation_id=reservation_id,
                    fence=fence,
                )
                self.uow.transition_call(
                    call_id,
                    ExternalCallState.DOMAIN_RAW_PERSIST_FAILED_V2 if
                        self.uow.get_external_call(call_id).usage.get("http_capture_v2") is not None
                        else ExternalCallState.RAW_PERSIST_FAILED,
                    reservation_id=reservation_id,
                    fence=fence,
                )
                raise persist_error
            self.artifacts.confirm_raw(manifest)
            self._guard(write_guard)
            self.uow.record_raw_and_transition(
                call_id,
                manifest.artifact_ref,
                ExternalCallState.RAW_RESPONSE_PERSISTED,
                provider_response_id=manifest.provider_response_id,
                usage=manifest.usage,
                reservation_id=reservation_id,
                fence=fence,
            )
            return self._validate_and_submit(
                call_id,
                manifest.artifact_ref,
                validator,
                context,
                reservation_id,
                fence,
                write_guard,
            )
        self._guard(write_guard)
        self.uow.record_raw_and_transition(
            call_id,
            ref,
            ExternalCallState.RAW_RESPONSE_PERSISTED,
            provider_response_id=raw.provider_response_id,
            usage=raw.usage,
            reservation_id=reservation_id,
            fence=fence,
        )
        return self._validate_and_submit(
            call_id,
            ref,
            validator,
            context,
            reservation_id,
            fence,
            write_guard,
        )

    async def _continue(
        self,
        call: PersistedExternalCall,
        *,
        request: dict[str, Any] | None,
        provider: ExternalProvider,
        validator: Validator,
        context: AgentExecutionContext,
        allow_provider_call: bool,
        reservation_id: str,
        fence: TaskLeaseFence,
        write_guard: WriteGuard | None,
    ) -> AgentResult:
        state = call.state
        http_manifest = self.artifacts.discover_raw(call.external_call_id + ":http-v2")
        if state in {ExternalCallState.HTTP_RESPONSE_CAPTURED_V2,
                     ExternalCallState.DOMAIN_RAW_PERSIST_FAILED_V2,
                     ExternalCallState.ACCOUNTING_INCOMPLETE_V2} or (
                         state in {ExternalCallState.HTTP_CAPTURE_STARTED_V2,
                                   ExternalCallState.HTTP_CAPTURE_FAILED_V2}
                         and http_manifest is not None):
            try:
                raw = self._resume_http_v2(call, provider, context, reservation_id, fence, write_guard)
            except Exception:
                current = self.uow.get_external_call(call.external_call_id).state
                if current is ExternalCallState.HTTP_RESPONSE_CAPTURED_V2:
                    self.uow.transition_call(call.external_call_id,
                        ExternalCallState.ACCOUNTING_INCOMPLETE_V2,
                        reservation_id=reservation_id, fence=fence)
                raise
            self._guard(write_guard)
            ref = self.artifacts.persist_raw(call.external_call_id, raw.body, raw.mime_type,
                request_fingerprint=call.request_fingerprint, run_id=context.run_id,
                task_id=context.task_id, execution_context_fingerprint=execution_context_fingerprint(
                    self._context_data(context)), provider_response_id=raw.provider_response_id,
                usage=raw.usage)
            self.uow.record_raw_and_transition(call.external_call_id, ref,
                ExternalCallState.RAW_RESPONSE_PERSISTED, provider_response_id=raw.provider_response_id,
                usage=raw.usage, reservation_id=reservation_id, fence=fence)
            return self._validate_and_submit(call.external_call_id, ref, validator, context,
                                             reservation_id, fence, write_guard)
        if state in {ExternalCallState.HTTP_CAPTURE_STARTED_V2,
                     ExternalCallState.HTTP_CAPTURE_FAILED_V2}:
            raise ValueError("DELIVERY_UNKNOWN: no confirmed HTTP capture; never resend")
        if state is ExternalCallState.PLANNED:
            if not allow_provider_call or request is None:
                raise ValueError(f"call {call.external_call_id} has no durable raw response")
            self._guard(write_guard)
            self.uow.transition_call(
                call.external_call_id,
                ExternalCallState.STARTED,
                reservation_id=reservation_id,
                fence=fence,
            )
            return await self._invoke_provider(
                call_id=call.external_call_id,
                request=request,
                provider=provider,
                validator=validator,
                context=context,
                reservation_id=reservation_id,
                fence=fence,
                write_guard=write_guard,
            )
        if state is ExternalCallState.STARTED:
            manifest = self.artifacts.discover_raw(call.external_call_id)
            if manifest is not None:
                self._assert_manifest_provenance(call, manifest, context)
                self.artifacts.confirm_raw(manifest)
                self._guard(write_guard)
                self.uow.record_raw_and_transition(
                    call.external_call_id,
                    manifest.artifact_ref,
                    ExternalCallState.RAW_RESPONSE_PERSISTED,
                    provider_response_id=manifest.provider_response_id,
                    usage=manifest.usage,
                    reservation_id=reservation_id,
                    fence=fence,
                )
                return self._validate_and_submit(
                    call.external_call_id,
                    manifest.artifact_ref,
                    validator,
                    context,
                    reservation_id,
                    fence,
                    write_guard,
                )
            if not allow_provider_call or request is None:
                raise ValueError(f"call {call.external_call_id} has no durable raw response")
            if self._http_capture_enabled(provider, context.run_id):
                raise ValueError("DELIVERY_UNKNOWN: NativeJSON recovery never resends")
            from co_scientist.domain.probe_execution import probe_envelope_for_manifest

            if probe_envelope_for_manifest(self.uow.run_manifest(context.run_id)) is not None:
                raise ValueError("delivery_state_unknown; probe forbids provider resend")
            from co_scientist.domain.ideation_core_boundary import batch2_execution_enabled

            if batch2_execution_enabled(self.uow.run_manifest(context.run_id)):
                raise ValueError("DELIVERY_UNKNOWN: baseline forbids provider resend")
            return await self._invoke_provider(
                call_id=call.external_call_id,
                request=request,
                provider=provider,
                validator=validator,
                context=context,
                reservation_id=reservation_id,
                fence=fence,
                write_guard=write_guard,
            )
        if state is ExternalCallState.RAW_RESPONSE_PERSISTED:
            if call.raw_artifact_ref is None:
                raise ValueError(f"call {call.external_call_id} has no persisted raw artifact")
            return self._validate_and_submit(
                call.external_call_id,
                call.raw_artifact_ref,
                validator,
                context,
                reservation_id,
                fence,
                write_guard,
            )
        if state is ExternalCallState.VALIDATED:
            return self._submit_legacy_validated(call, context, reservation_id, fence, write_guard)
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
        reservation_id: str,
        fence: TaskLeaseFence,
        write_guard: WriteGuard | None = None,
    ) -> AgentResult:
        if (
            context.attempt != fence.attempt
            or context.reservation_id != reservation_id
            or context.run_id != fence.run_id
            or context.task_id != fence.task_id
        ):
            raise ValueError("execution context does not match task lease fence")
        self._assert_prompt_hash(request, context)
        from types import SimpleNamespace

        assert_baseline_no_unknown_delivery(SimpleNamespace(uow=self.uow, artifacts=self.artifacts),
            run_id=context.run_id, task_id=context.task_id, through_attempt=context.attempt)
        fingerprint = request_fingerprint(request)
        try:
            call = self.uow.get_external_call(call_id)
        except KeyError:
            if context.lease_fence_fingerprint != lease_fence_fingerprint(fence):
                raise ValueError("execution context does not match task lease fence")
            self._guard(write_guard)
            self.uow.plan_external_call(
                call_id,
                fingerprint,
                run_id=context.run_id,
                task_id=context.task_id,
                execution_context=self._context_data(context),
                provider=context.provider,
                model_or_tool=context.model_or_tool,
                attempt=fence.attempt,
                reservation_id=reservation_id,
                fence=fence,
            )
            self._guard(write_guard)
            self.uow.transition_call(
                call_id,
                ExternalCallState.STARTED,
                reservation_id=reservation_id,
                fence=fence,
            )
            return await self._invoke_provider(
                call_id=call_id,
                request=request,
                provider=provider,
                validator=validator,
                context=context,
                reservation_id=reservation_id,
                fence=fence,
                write_guard=write_guard,
            )
        self._assert_fingerprint(call, fingerprint)
        self._assert_context(call, context)
        if call.attempt != fence.attempt or call.reservation_id != reservation_id:
            raise ValueError("external call does not match task lease reservation")
        return await self._continue(
            call,
            request=request,
            provider=provider,
            validator=validator,
            context=context,
            allow_provider_call=True,
            reservation_id=reservation_id,
            fence=fence,
            write_guard=write_guard,
        )

    async def resume(
        self,
        call_id: str,
        *,
        provider: ExternalProvider,
        validator: Validator,
        context: AgentExecutionContext,
        reservation_id: str,
        fence: TaskLeaseFence,
        write_guard: WriteGuard | None = None,
    ) -> AgentResult:
        if (
            context.attempt != fence.attempt
            or context.reservation_id != reservation_id
            or context.run_id != fence.run_id
            or context.task_id != fence.task_id
        ):
            raise ValueError("execution context does not match task lease fence")
        call = self.uow.get_external_call(call_id)
        self._assert_context(call, context)
        if call.attempt != fence.attempt or call.reservation_id != reservation_id:
            raise ValueError("external call does not match task lease reservation")
        return await self._continue(
            call,
            request=None,
            provider=provider,
            validator=validator,
            context=context,
            allow_provider_call=False,
            reservation_id=reservation_id,
            fence=fence,
            write_guard=write_guard,
        )
