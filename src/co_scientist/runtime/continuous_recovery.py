"""One retry controller outside provider SDKs; raw remains the evidence source."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from pydantic import ValidationError

from co_scientist.domain.continuous_execution import policy_for, retry_delay


def classify_failure(runtime, call, task, error, transport=None):
    capture = runtime.artifacts.discover_raw(call.external_call_id + ":http-v2")
    if capture is not None:
        status = capture.usage.get("status")
        raw = runtime.artifacts.read(capture.artifact_ref)
        try:
            doc = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            if status in {429, 500, 502, 503, 504}:
                doc = {}
            elif status is not None and not 200 <= status < 300:
                return None, None, None
            else:
                return "INVALID_JSON", "Return one complete valid JSON response; no prose outside JSON.", None
        if not isinstance(doc, dict):
            return None, None, None
        if status in {429, 500, 502, 503, 504}:
            error_info = doc.get("error", {})
            code = str(error_info.get("code") or error_info.get("type", "")) if isinstance(error_info, dict) else ""
            if code in {"insufficient_quota", "billing_hard_limit_reached", "account_deactivated",
                        "invalid_api_key", "permission_denied"}:
                return None, None, None
            headers = capture.usage.get("headers", {})
            wait = headers.get("retry-after")
            delay = None
            if wait:
                try:
                    delay = max(0, float(wait))
                except ValueError:
                    try:
                        delay = max(0, (parsedate_to_datetime(wait)-datetime.now(UTC)).total_seconds())
                    except (ValueError, TypeError):
                        pass
            return "TRANSIENT_HTTP", None, delay
        if status is not None and not 200 <= status < 300:
            return None, None, None
        if doc.get("model") != call.model_or_tool:
            return None, None, None
        if any(item.get("type") == "refusal" for output in doc.get("output", [])
               for item in output.get("content", [])):
            return None, None, None
        if doc.get("status") == "incomplete" and doc.get("incomplete_details", {}).get("reason") == "max_output_tokens":
            return "OUTPUT_LENGTH", None, None
        choices = doc.get("choices", [])
        if choices and choices[0].get("finish_reason") == "length":
            return "OUTPUT_LENGTH", None, None
        if call.state.value == "accounting_incomplete_v2":
            return None, None, None  # Parse/accounting failures do not justify blind resend.
        if doc.get("status") in {"failed", "cancelled"}:
            return None, None, None
        content = (choices[0].get("message", {}).get("content", "") if choices else
                   next((x.get("text", "") for o in doc.get("output", []) for x in o.get("content", [])
                         if x.get("type") == "output_text"), ""))
        try:
            result = json.loads(content)
        except ValueError:
            return "INVALID_JSON", "Return one valid JSON object matching the frozen schema, without markdown or prose.", None
        if task.payload["output_schema_id"] == "RootLiteratureReviewResultV1":
            visible = task.payload["inputs"]["model_input"]["retrieval_result"]["sources"]
            wanted = {x["source_id"] for x in visible}
            actual = set(result.get("reviewed_source_ids", []))
            if actual != wanted:
                return "SOURCE_COVERAGE", ("Reproduce the complete source review from the unchanged supplied sources. "
                    "Missing IDs: " + json.dumps(sorted(wanted-actual)) + "; invalid IDs: "
                    + json.dumps(sorted(actual-wanted)) + ". Give source-specific evidence and limitations; IDs alone are not review."), None
        # DomainValidationError wraps the Pydantic error as __cause__; a Worker
        # TaskGroup adds another envelope. Never project arbitrary exception text.
        pending, seen = [error], set()
        details = []
        while pending and len(seen) < 32:
            exc = pending.pop()
            if id(exc) in seen:
                continue
            seen.add(id(exc))
            if isinstance(exc, BaseExceptionGroup):
                pending.extend(exc.exceptions[:16])
            if exc.__cause__ is not None:
                pending.append(exc.__cause__)
            if isinstance(exc, ValidationError):
                # Unknown provider-authored field names and messages are not
                # trusted diagnostics (and may contain secrets or instructions).
                fields = {"candidate", "hypothesis_id", "content_id", "title", "hypothesis", "mechanism",
                          "assumptions", "predictions", "falsifiers", "operator", "rationale",
                          "parent_contributions", "schema_version", "research_plan_version", "binding"}
                for item in exc.errors(include_input=False, include_context=False, include_url=False)[:16]:
                    details.append({"location": [p if isinstance(p, int) or p in fields else "<unknown-field>"
                                                  for p in item["loc"][:8]], "type": item["type"]})
        if task.payload["output_schema_id"] == "BaselineEvolutionResultV1" and isinstance(result, dict):
            frozen = task.payload["inputs"]
            operator = frozen["model_input"].get("operator")
            expected = {"mutation": 1, "crossover": 2}.get(operator)
            actual = result.get("parent_contributions")
            if expected is not None and isinstance(actual, list) and len(actual) != expected:
                details.insert(0, {"location": ["parent_contributions"], "type": "parent_record_count",
                    "actual_count": len(actual), "expected_count": expected, "operator": operator,
                    "frozen_scientific_parent_ids": frozen["ideation_task_binding"]["scientific_parent_ids"]})
        details = details[:16]
        correction = "Regenerate from unchanged scientific inputs. Fix these format errors: " + json.dumps(details)[:3000] + (
            ". Feedback projection: bounded-schema-diagnostics-v2. Follow the exact frozen schema; "
            "no extra fields or missing required content.")
        if task.payload["output_schema_id"] == "BaselineEvolutionResultV1":
            correction += (" Combine all contributions and critique-driven changes for each scientific parent "
                "into its single entry, in frozen parent order; feedback is not another scientific parent. "
                "Keep the operator, parent identities, evidence, candidate inputs and full ordered critiques unchanged.")
        return "SCHEMA", correction, None
    # Query the durable observation table, never infer delivery from exception text.
    from sqlalchemy import select

    from co_scientist.adapters.persistence.sqlite import ExternalCallMilestoneRow
    with runtime.uow.session_factory() as session:
        entered = session.scalar(select(ExternalCallMilestoneRow.observation_id).where(
            ExternalCallMilestoneRow.external_call_id == call.external_call_id,
            ExternalCallMilestoneRow.milestone == "inner_transport_entered")) is not None
    if not entered and transport is not None:
        import hashlib

        from co_scientist.runtime.bounded_transport import BoundedTransport

        if isinstance(transport, BoundedTransport) and transport.single_root_gate is not None:
            suffix = ":attempt:"+str(call.attempt)+":"+hashlib.sha256(call.external_call_id.encode()).hexdigest()
            with transport._db() as db:
                dispatched = any(row["id"].endswith(suffix) for row in db.execute("SELECT id FROM attempts"))
            if not dispatched:
                return "NOT_SENT", None, None
    # Missing best-effort milestones alone do not prove absence of dispatch.
    return "DELIVERY_UNKNOWN", None, None


def prepare_retry(worker, task, call_id, error) -> bool:
    policy = policy_for(worker.runtime.uow.run_manifest(task.run_id))
    if policy is None:
        return False
    try:
        call = worker.runtime.uow.get_external_call(call_id)
    except KeyError:
        return False  # No call identity: driver records a native partial stop.
    if call.provider not in {"openai", "deepseek"}:
        if call.provider == "pubmed:root":
            import httpx

            def leaves(exc):
                return [x for child in exc.exceptions for x in leaves(child)] if isinstance(exc, BaseExceptionGroup) else [exc]
            if any(isinstance(exc, (httpx.TimeoutException, httpx.ConnectError)) for exc in leaves(error)):
                return worker.runtime.uow.prepare_continuous_retry(fence=task, external_call_id=call_id,
                    reason="RETRIEVAL_UNKNOWN", correction=None,
                    delay_seconds=retry_delay(policy, task.attempt, call_id), unknown_cost=True)
        return False
    if call.applied_domain_sequence is not None or call.agent_result is not None:
        return False
    definition = worker.runtime.uow.task_definition(task.task_id)
    transport = worker.providers.resolve(call.provider).client._transport
    reason, correction, server_delay = classify_failure(worker.runtime, call, definition, error, transport)
    if reason is None:
        return False
    if reason == "OUTPUT_LENGTH":
        transport = worker.providers.resolve(call.provider).client._transport
        prior_plan = transport.artifacts.discover_raw(call_id+":context-plan-v1")
        if prior_plan is not None:
            value = json.loads(transport.artifacts.read(prior_plan.artifact_ref))
            role = definition.payload["inputs"]["effective_execution"]["role"]
            if value["output_budget"] >= policy.outputs[role].ceiling:
                return False
    delay = retry_delay(policy, task.attempt, call_id, server_delay) if reason in {
        "TRANSIENT_HTTP", "DELIVERY_UNKNOWN"} else 0
    from sqlalchemy import select

    from co_scientist.adapters.persistence.sqlite import CostEntryRow
    with worker.runtime.uow.session_factory() as session:
        unknown_cost = session.scalar(select(CostEntryRow.cost_entry_id).where(
            CostEntryRow.external_call_id == call_id)) is None and reason != "NOT_SENT"
    return worker.runtime.uow.prepare_continuous_retry(fence=task, external_call_id=call_id,
        reason=reason, correction=correction, delay_seconds=delay, unknown_cost=unknown_cost)


def prepare_retrieval_retry(worker, task, result) -> bool:
    policy = policy_for(worker.runtime.uow.run_manifest(task.run_id))
    if policy is None or result.output_schema_id != "RootRetrievalResultV2":
        return False
    aggregate = json.loads(worker.runtime.artifacts.read(result.raw_artifact_ref))
    failures = [section["failure"] for section in aggregate["sections"] if section["failure"]]
    if not failures or any(reason not in {"HTTP_RESPONSE_429", "HTTP_RESPONSE_500", "HTTP_RESPONSE_502",
            "HTTP_RESPONSE_503", "HTTP_RESPONSE_504", "RETRIEVAL_PARSE_FAILED", "SOURCE_PARSE_FAILED"}
            for reason in failures):
        return False
    import hashlib

    from co_scientist.ports.artifact_store import RawArtifactManifest

    transport = worker.providers.resolve("pubmed:root").search.provider.client._transport
    suffix = ":attempt:"+str(task.attempt)+":"+hashlib.sha256(result.external_call_id.encode()).hexdigest()
    waits = []
    for path in transport.artifacts.root.glob("raw/*"+suffix+"/*.manifest.json"):
        meta = RawArtifactManifest.model_validate_json(path.read_bytes())
        value = meta.usage.get("retry_after")
        if value is not None:
            try:
                waits.append(max(0, float(value)))
            except ValueError:
                try:
                    waits.append(max(0, (parsedate_to_datetime(value)-datetime.now(UTC)).total_seconds()))
                except (ValueError, TypeError):
                    pass
    return worker.runtime.uow.prepare_continuous_retry(fence=task, external_call_id=result.external_call_id,
        reason="RETRIEVAL_TRANSIENT", correction=None,
        delay_seconds=retry_delay(policy, task.attempt, result.external_call_id, max(waits) if waits else None), unknown_cost=False)


def recover_expired_continuous(worker, run_id):
    if policy_for(worker.runtime.uow.run_manifest(run_id)) is None:
        return 0
    if worker.runtime.uow.run_state(run_id) != "running":
        return 0
    from sqlalchemy import select

    from co_scientist.adapters.persistence.sqlite import TaskRow
    from co_scientist.domain.task import TaskLeaseFence

    with worker.runtime.uow.session_factory() as session:
        rows = session.scalars(select(TaskRow).where(TaskRow.run_id == run_id,
            TaskRow.state.in_(("leased", "running")))).all()
        candidates = [(row.task_id, row.attempt, row.lease_token) for row in rows
                      if row.lease_token and row.lease_expires_at is not None
                      and worker.runtime.uow._stored_utc(row.lease_expires_at) <= worker.clock()]
        active = [(row.task_id, row.attempt, worker.runtime.uow._stored_utc(row.lease_expires_at))
                  for row in rows if row.lease_expires_at is not None
                  and worker.runtime.uow._stored_utc(row.lease_expires_at) > worker.clock()]
    for task_id, attempt, token in candidates:
        call = worker.runtime.uow.external_call_for_task_attempt(run_id=run_id, task_id=task_id, attempt=attempt)
        if call is None or call.agent_result is not None or call.applied_domain_sequence is not None:
            continue
        capture = worker.runtime.artifacts.discover_raw(call.external_call_id+":http-v2")
        if capture is not None and call.state.value != "validation_failed":
            continue  # Existing original-attempt capture recovery owns this.
        fence = TaskLeaseFence(run_id=run_id, task_id=task_id, attempt=attempt, lease_token=token)
        if not prepare_retry(worker, fence, call.external_call_id, RuntimeError("expired attempt")):
            worker.supervisor.contain_batch2_validation_failure(run_id=run_id,
                task_id=task_id, call_id=call.external_call_id, reservation_id=call.reservation_id, fence=fence)
    for task_id, attempt, deadline in active:
        call = worker.runtime.uow.external_call_for_task_attempt(run_id=run_id, task_id=task_id, attempt=attempt)
        if call is None or (call.agent_result is None and call.raw_artifact_ref is None
                and worker.runtime.artifacts.discover_raw(call.external_call_id+":http-v2") is None):
            return min(5, max(0, (deadline-worker.clock()).total_seconds()))
    return 0


def recover_original_response(worker, task, call_id, error) -> bool:
    if policy_for(worker.runtime.uow.run_manifest(task.run_id)) is None:
        return False
    try:
        call = worker.runtime.uow.get_external_call(call_id)
    except KeyError:
        return False
    if call.state.value == "validation_failed" or call.applied_domain_sequence is not None:
        return False
    if (worker.runtime.artifacts.discover_raw(call_id+":http-v2") is None
            and call.raw_artifact_ref is None and call.agent_result is None):
        return False
    def leaves(exc):
        return [item for child in exc.exceptions for item in leaves(child)] if isinstance(exc, BaseExceptionGroup) else [exc]
    if not any(isinstance(exc, (OSError, RuntimeError)) for exc in leaves(error)):
        return False
    events = worker.runtime.uow.load(task.run_id)
    prior = [e for e in events if e.event_type == "ContinuousOriginalRecoveryPlannedV1"
             and e.payload["external_call_id"] == call_id]
    if len(prior) >= 2:
        return False
    from co_scientist.events.models import NewEvent

    worker.runtime.uow.assert_task_fence(fence=task)
    worker.runtime.uow.commit_domain_batch(run_id=task.run_id, expected_sequence=events[-1].sequence,
        events=(NewEvent(event_type="ContinuousOriginalRecoveryPlannedV1", payload={
            "task_id": task.task_id, "external_call_id": call_id,
            "attempt": task.attempt, "offline_recovery_number": len(prior)+1,
            "provider_dispatch": False}),), idempotency_key=f"original-recovery:{call_id}:{len(prior)+1}")
    return True


def terminal_provider_failure(worker, task, call_id) -> str | None:
    if policy_for(worker.runtime.uow.run_manifest(task.run_id)) is None:
        return None
    capture = worker.runtime.artifacts.discover_raw(call_id+":http-v2")
    if capture is None:
        return None
    status = capture.usage.get("status")
    try:
        data = json.loads(worker.runtime.artifacts.read(capture.artifact_ref))
    except (ValueError, UnicodeDecodeError):
        data = {}
    if not isinstance(data, dict):
        return "PROVIDER_ENVELOPE_INVALID"
    error = data.get("error", {})
    code = (error.get("code") or error.get("type")) if isinstance(error, dict) else None
    if status in {401, 402, 403} or code in {"insufficient_quota", "billing_hard_limit_reached", "account_deactivated", "invalid_api_key", "permission_denied", "model_not_found", "billing_not_active", "payment_required"}:
        return "PROVIDER_PERMISSION_OR_BILLING"
    if status == 200 and data.get("model") != capture.usage.get("model"):
        return "PROVIDER_MODEL_IDENTITY"
    return None
