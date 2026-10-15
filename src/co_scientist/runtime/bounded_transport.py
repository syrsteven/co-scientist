"""Fail-closed HTTP budget ledger shared by normal runtime and benchmark adapters.

Reserves whole per-call envelopes without refunds, including failed/unknown
deliveries. Exact request repeats reuse durable raw responses. A started request
without raw is never automatically resent. No scientific state is mutated here.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import time
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from co_scientist.adapters.artifacts.filesystem import FilesystemArtifactStore
from co_scientist.domain.dispatch_limits import DispatchLimits
from co_scientist.domain.execution_config import EffectiveExecutionConfig, validate_wire
from co_scientist.domain.pilot_pricing import DeepSeekPilotPricing, OpenAIJudgePilotPricing
from co_scientist.ports.external_provider import capture_http_response
from co_scientist.runtime.transport_observability import record_transport_milestone

if TYPE_CHECKING:
    from co_scientist.domain.generation_integration import GenerationPerformanceConfig
    from co_scientist.domain.single_root import FullIdeationConfig, SingleRootConfig


def require_bounded_client(client: httpx.AsyncClient,
                           pricing: DeepSeekPilotPricing | OpenAIJudgePilotPricing,
                           output: int) -> None:
    transport = client._transport
    if (not isinstance(transport, BoundedTransport) or transport.limits.pricing != pricing
            or transport.limits.output_tokens_per_call != output):
        raise ValueError("bounded pricing requires the matching durable dispatch transport")


class DispatchLimitError(RuntimeError):
    pass


class SlotRetrievalHTTPError(RuntimeError):
    """An observed non-2xx retrieval response, not an unknown delivery."""

    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__(f"retrieval HTTP {status}; no automatic retry")


class ResponseCapacityError(RuntimeError):
    """Bounded incomplete evidence; never a complete HTTP/domain response."""

    def __init__(self, prefix: bytes, status: int) -> None:
        self.response_prefix, self.http_status = prefix, status
        super().__init__("RESPONSE_CAPACITY_EXCEEDED; incomplete response, cost unknown")


async def read_bounded_response(response: httpx.Response, limit: int) -> bytes:
    chunks = bytearray()
    async for chunk in response.aiter_bytes():
        if len(chunks) + len(chunk) > limit:
            chunks.extend(chunk[:limit - len(chunks)])
            raise ResponseCapacityError(bytes(chunks), response.status_code)
        chunks.extend(chunk)
    return bytes(chunks)


class BoundedTransport(httpx.AsyncBaseTransport):
    def __init__(self, root: Path, limits: DispatchLimits, *,
                 inner: httpx.AsyncBaseTransport | None = None,
                 retrieval_isolation_policy: str | None = None,
                 authority_hash: str | None = None,
                 effective_config: EffectiveExecutionConfig | GenerationPerformanceConfig | SingleRootConfig | FullIdeationConfig | None = None,
                 single_root_gate=None) -> None:
        if retrieval_isolation_policy not in {None, "baseline-slot-http-response-isolation-v1"}:
            raise ValueError("unsupported retrieval isolation policy")
        if retrieval_isolation_policy is not None and (
            not isinstance(authority_hash, str) or not authority_hash.startswith("sha256:")
            or len(authority_hash) != 71
            or any(c not in "0123456789abcdef" for c in authority_hash[7:])):
            raise ValueError("retrieval isolation requires frozen run/profile authority")
        self.retrieval_isolation_policy = retrieval_isolation_policy
        self.effective_config = effective_config
        self.single_root_gate = single_root_gate
        self.root, self.limits = Path(root), limits
        self.root.mkdir(parents=True, exist_ok=True)
        self.inner = inner or httpx.AsyncHTTPTransport(retries=0)
        self._closed = False
        self.artifacts = FilesystemArtifactStore(self.root / "artifacts")
        identity = limits.model_dump(mode="json")
        if effective_config is not None:
            identity = {"limits": identity, "effective_config": effective_config.model_dump(mode="json")}
        if retrieval_isolation_policy is not None:
            identity = {"limits": identity, "retrieval_isolation_policy": retrieval_isolation_policy,
                        "authority_hash": authority_hash}
        if single_root_gate is not None:
            identity = {"limits": identity, "single_root": {
                "run_id": single_root_gate.run_id, "root": str(single_root_gate.root),
                "mock_only": single_root_gate.mock_only}}
        self.identity = "sha256:" + hashlib.sha256(
            json.dumps(identity, sort_keys=True).encode()).hexdigest()
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS policy (id INTEGER PRIMARY KEY, hash TEXT NOT NULL,
                    started REAL, blocked TEXT);
                CREATE TABLE IF NOT EXISTS attempts (id TEXT PRIMARY KEY, kind TEXT NOT NULL,
                    started REAL NOT NULL, input_bound INTEGER NOT NULL,
                    output_bound INTEGER NOT NULL, reserved_usd TEXT NOT NULL);
            """)
            db.execute("INSERT OR IGNORE INTO policy VALUES (1,?,NULL,NULL)", (self.identity,))
            if db.execute("SELECT hash FROM policy").fetchone()[0] != self.identity:
                raise ValueError("dispatch policy changed on resume")

    def _db(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.root / "dispatch.sqlite3", timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        return db

    def snapshot(self) -> dict:
        with self._db() as db:
            rows = db.execute("SELECT * FROM attempts").fetchall()
            state = db.execute("SELECT * FROM policy").fetchone()
        return {"model_calls": sum(r["kind"] == "model" for r in rows),
                "literature_calls": sum(r["kind"] == "literature" for r in rows),
                "input_bound": sum(r["input_bound"] for r in rows),
                "output_bound": sum(r["output_bound"] for r in rows),
                "reserved_usd": str(sum((Decimal(r["reserved_usd"]) for r in rows), Decimal(0))),
                "started": state["started"], "blocked": state["blocked"]}

    def _reserve(self, key: str, kind: str, execution: dict | None = None) -> bool:
        cap = self.limits
        inp = (cap.pricing.input_token_limit or 0) if kind == "model" else 0
        out = cap.output_tokens_per_call if kind == "model" else 0
        cost = cap.pricing.reserve_usd_per_call if kind == "model" else Decimal(0)
        if execution is not None:
            inp, out = execution["runtime"]["max_input_tokens"], execution["runtime"]["max_output_tokens"]
            cost = Decimal(execution["reserved_usd"])
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            state = db.execute("SELECT * FROM policy").fetchone()
            if state["blocked"]:
                raise DispatchLimitError(state["blocked"])
            if db.execute("SELECT 1 FROM attempts WHERE id=?", (key,)).fetchone():
                return False
            now = time.time()
            if state["started"] is not None and now - state["started"] >= cap.max_wall_seconds:
                raise DispatchLimitError("wall-clock dispatch ceiling")
            rows = db.execute("SELECT * FROM attempts").fetchall()
            if execution is not None and execution.get("continuous_policy") is not None:
                from co_scientist.domain.continuous_execution import ContinuousPolicy

                policy = ContinuousPolicy.model_validate(execution["continuous_policy"])
                is_retry = ":attempt:" in key and int(key.split(":attempt:", 1)[1].split(":", 1)[0]) > 1
                retries = sum(":attempt:" in r["id"] and
                    int(r["id"].split(":attempt:", 1)[1].split(":", 1)[0]) > 1 for r in rows)
                if is_retry and retries >= policy.max_retry_dispatches:
                    raise DispatchLimitError("Run retry dispatch ceiling")
            if execution is not None and sum(r["id"].startswith("role:" + execution["role"] + ":")
                    for r in rows) >= execution["runtime"]["max_dispatches"]:
                raise DispatchLimitError("role dispatch ceiling")
            count = sum(r["kind"] == kind for r in rows)
            if count >= (cap.max_model_calls if kind == "model" else cap.max_literature_calls):
                raise DispatchLimitError(f"{kind} dispatch ceiling")
            if sum(r["input_bound"] for r in rows) + inp > cap.max_input_tokens:
                raise DispatchLimitError("input token reservation ceiling")
            if sum(r["output_bound"] for r in rows) + out > cap.max_output_tokens:
                raise DispatchLimitError("output token reservation ceiling")
            if sum((Decimal(r["reserved_usd"]) for r in rows), Decimal(0)) + cost > cap.max_usd:
                raise DispatchLimitError("cost reservation ceiling")
            db.execute("UPDATE policy SET started=COALESCE(started,?)", (now,))
            db.execute("INSERT INTO attempts VALUES (?,?,?,?,?,?)",
                       (key, kind, now, inp, out, str(cost)))
        return True

    def _after_raw(self) -> None:
        """Offline crash-injection seam."""

    def _validate_response(self, kind: str, status: int, raw: bytes,
                           execution: dict | None = None) -> None:
        reason = None
        if not 200 <= status < 300:
            if execution is not None and execution.get("continuous_policy") is not None:
                # The durable captured HTTP status is classified by the one
                # task-level retry controller. No SDK or transport retry here.
                return
            if kind == "literature" and (self.retrieval_isolation_policy is not None
                    or getattr(self.effective_config, "continuous_policy", None) is not None):
                raise SlotRetrievalHTTPError(status)
            reason = f"provider HTTP {status}; no automatic retry"
        elif kind == "model":
            try:
                body = json.loads(raw)
                usage = body["usage"]
                inp = usage.get("input_tokens", usage.get("prompt_tokens"))
                out = usage.get("output_tokens", usage.get("completion_tokens"))
                if (body.get("model") != (execution["capability"]["model"] if execution else self.limits.pricing.model)
                        or type(inp) is not int or type(out) is not int
                        or not 0 <= inp <= (execution["runtime"]["max_input_tokens"] if execution else (self.limits.pricing.input_token_limit or 0))
                        or not 0 <= out <= (execution["runtime"]["max_output_tokens"] if execution else self.limits.output_tokens_per_call)):
                    reason = "provider model/usage violates frozen envelope"
            except (KeyError, TypeError, ValueError):
                reason = "critical provider model/usage unavailable"
        if reason:
            if execution is not None and execution.get("continuous_policy") is not None:
                raise DispatchLimitError(reason)
            with self._db() as db:
                db.execute("UPDATE policy SET blocked=?", (reason,))
            raise DispatchLimitError(reason)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        record_transport_milestone("request_constructed")
        raw_request = await request.aread()
        from co_scientist.domain.single_root import FullIdeationConfig, SingleRootConfig

        if isinstance(self.effective_config, (SingleRootConfig, FullIdeationConfig)):
            if self.single_root_gate is None:
                raise DispatchLimitError("single-root requires task-bound HTTP permit")
            self.single_root_gate.check(request, raw_request)
        execution = request.extensions.get("effective_execution")
        if self.effective_config is not None and request.method == "POST":
            if not isinstance(execution, dict) or execution != self.effective_config.task(execution.get("schema_id", "")):
                raise DispatchLimitError("transport task/runtime identity mismatch")
            validate_wire(execution, raw_request)
        elif execution is not None:
            raise DispatchLimitError("transport runtime is not frozen")
        record_transport_milestone("request_serialized")
        literature = (request.url.host == "eutils.ncbi.nlm.nih.gov" and request.url.path in {
            "/entrez/eutils/esearch.fcgi", "/entrez/eutils/esummary.fcgi", "/entrez/eutils/efetch.fcgi"})
        allowed = (str(request.url) in {"https://api.deepseek.com/chat/completions",
                    "https://api.deepseek.com/beta/chat/completions"}
                   if self.limits.pricing.model == "deepseek-flash" else
                   str(request.url) == "https://api.openai.com/v1/responses")
        if execution is not None:
            allowed = str(request.url) == execution["capability"]["endpoint"]
        kind = "literature" if literature else "model"
        if request.url.scheme != "https" or (not literature and not allowed):
            raise DispatchLimitError("unexpected provider endpoint")
        if request.method != ("GET" if literature else "POST"):
            raise DispatchLimitError("unexpected provider method")
        if kind == "model":
            payload = json.loads(raw_request)
            output = payload.get("max_tokens", payload.get("max_output_tokens"))
            continuous = execution is not None and execution.get("continuous_policy") is not None
            plan = request.extensions.get("context_plan") if continuous else None
            if continuous:
                from co_scientist.runtime.context_planning import validate_plan

                if plan is None:
                    raise DispatchLimitError("missing frozen context plan")
                assert execution is not None
                validate_plan(payload, execution, plan)
            expected_output = plan["output_budget"] if plan is not None else execution["runtime"]["max_output_tokens"] if execution else self.limits.output_tokens_per_call
            if (payload.get("model") != (execution["capability"]["model"] if execution else self.limits.pricing.model)
                    or output != expected_output):
                raise DispatchLimitError("request model/output differs from frozen envelope")
            if not continuous and len(raw_request) + 4096 > (execution["runtime"]["max_input_tokens"] if execution else (self.limits.pricing.input_token_limit or 0)):
                raise DispatchLimitError("request input exceeds UTF-8 bytes + 4096 bound")
        key = hashlib.sha256(request.method.encode() + b"\0" + str(request.url).encode()
                             + b"\0" + raw_request).hexdigest()
        if execution is not None:
            key = "role:" + execution["role"] + ":" + key
            if execution.get("continuous_policy") is not None:
                from co_scientist.runtime.transport_observability import (
                    current_external_call_observation,
                )

                observation = current_external_call_observation()
                if observation is None:
                    raise DispatchLimitError("continuous dispatch requires attempt authority")
                key += ":attempt:" + str(observation.fence.attempt) + ":" + hashlib.sha256(observation.external_call_id.encode()).hexdigest()
        elif kind == "literature" and getattr(self.effective_config, "continuous_policy", None) is not None:
            from co_scientist.runtime.transport_observability import (
                current_external_call_observation,
            )

            observation = current_external_call_observation()
            if observation is None:
                raise DispatchLimitError("retrieval retry requires durable task authority")
            key += ":attempt:" + str(observation.fence.attempt) + ":" + hashlib.sha256(observation.external_call_id.encode()).hexdigest()
        fresh = self._reserve(key, kind, execution)
        if fresh:
            record_transport_milestone("bounded_transport_reserved")
        manifest = self.artifacts.discover_raw(key)
        if manifest is None:
            if not fresh:
                raise DispatchLimitError("delivery_state_unknown; never resend without raw")
            started = self.snapshot()["started"]
            remaining = self.limits.max_wall_seconds - (time.time() - started)
            async with asyncio.timeout(max(0, remaining)):
                if not isinstance(self.inner, BoundedTransport):
                    record_transport_milestone("inner_transport_entered")
                response = await self.inner.handle_async_request(request)
                record_transport_milestone("response_headers_received")
                try:
                    if execution is None and self.effective_config is None:
                        raw = await response.aread()
                    else:
                        try:
                            if execution is not None:
                                limit = execution["runtime"]["max_response_bytes"]
                            else:
                                assert self.effective_config is not None
                                limit = self.effective_config.envelope.retrieval_response_bytes
                            raw = await read_bounded_response(response, limit)
                        except ResponseCapacityError as error:
                            self.artifacts.persist_raw(key + ":incomplete", error.response_prefix,
                                "application/octet-stream", request_fingerprint=key, run_id=self.identity,
                                task_id=key, execution_context_fingerprint=self.identity,
                                usage={"version": "incomplete-http-evidence-v1", "complete": False,
                                       "http_status": error.http_status, "cost": "UNKNOWN"})
                            raise
                    record_transport_milestone("response_body_complete")
                    capture_http_response(raw, response.status_code, dict(response.headers))
                    self.artifacts.persist_raw(
                        key, raw, response.headers.get("content-type", "application/json"),
                        request_fingerprint=key, run_id=self.identity, task_id=key,
                        execution_context_fingerprint=self.identity,
                        usage={"http_status": response.status_code, **(
                            {"retry_after": response.headers.get("retry-after")}
                            if getattr(self.effective_config, "continuous_policy", None) is not None else {})})
                    record_transport_milestone("raw_persisted")
                finally:
                    await response.aclose()
            self._after_raw()
            manifest = self.artifacts.discover_raw(key)
        assert manifest is not None
        if manifest.execution_context_fingerprint != self.identity:
            raise ValueError("raw dispatch identity mismatch")
        raw = self.artifacts.read(manifest.artifact_ref)
        status = int(manifest.usage["http_status"])
        capture_http_response(raw, status, {"content-type": manifest.artifact_ref.mime_type})
        if execution is not None and execution.get("continuous_policy") is not None:
            from co_scientist.runtime.context_planning import record_usage_observation

            record_usage_observation(self, request.extensions["context_plan"], raw)
        if execution is None:
            self._validate_response(kind, status, raw)
        else:
            self._validate_response(kind, status, raw, execution)
        return httpx.Response(status, content=raw,
                              headers={"content-type": manifest.artifact_ref.mime_type})

    async def aclose(self) -> None:
        if self._closed:
            return
        # This wrapper owns exactly one close of its inner transport. Mark it
        # first so a failing close is never duplicated by nested cleanup.
        self._closed = True
        await self.inner.aclose()
