"""Explicit one-shot authorization at the last boundary before bounded HTTP.

The permit issuer is supplied by a separately authorized execution command.
There is no default issuer and no credential/environment authorization fallback.
"""

import copy
import hashlib
from pathlib import Path

import httpx

from co_scientist.domain.research_protocol import protocol_hash
from co_scientist.domain.single_root import (
    MODE,
    full_ideation,
    single_root,
    validate_full_scope,
    validate_scope,
)
from co_scientist.runtime.transport_observability import current_external_call_observation


class SingleRootPermitGate:
    def __init__(self, *, runtime, supervisor, run_id, root: Path, issuer, mock_only=True):
        self.runtime, self.supervisor, self.run_id = runtime, supervisor, run_id
        self.root, self.issuer, self.mock_only = root.resolve(), issuer, mock_only

    def check(self, request: httpx.Request, wire: bytes):
        context = current_external_call_observation()
        manifest = self.runtime.uow.run_manifest(self.run_id)
        from co_scientist.domain.continuous_execution import policy_for

        policy = policy_for(manifest)
        if policy is not None:
            from datetime import UTC, datetime

            created = self.runtime.uow.load(self.run_id)[0].occurred_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            if (datetime.now(UTC)-created).total_seconds() >= manifest["effective_execution_config"]["performance"]["baseline"]["envelope"]["max_wall_seconds"]:
                raise ValueError("RUN_WATCHDOG: dispatch forbidden")
        max_attempts = policy.max_attempts if policy is not None else 1
        if context is None or context.run_id != self.run_id or not 1 <= context.fence.attempt <= max_attempts:
            raise ValueError("single-root requires active original-attempt authority")
        manifest = self.runtime.uow.run_manifest(self.run_id)
        full = full_ideation(manifest)
        if not single_root(manifest) and not full:
            raise ValueError("single-root mode not frozen")
        task = self.runtime.uow.task_definition(context.task_id)
        if full:
            validate_full_scope(task, max_attempts=max_attempts)
        else:
            validate_scope(task)
        self.supervisor.authorize_batch2_task(task, operation="execute")
        call = self.runtime.uow.get_external_call(context.external_call_id)
        schema = task.payload["output_schema_id"]
        execution = task.payload["inputs"].get("effective_execution")
        if schema == "RootRetrievalResultV2":
            if (request.method != "GET" or request.url.scheme != "https"
                    or request.url.host != "eutils.ncbi.nlm.nih.gov"
                    or request.url.path not in {"/entrez/eutils/esearch.fcgi", "/entrez/eutils/efetch.fcgi"}):
                raise ValueError("single-root retrieval endpoint forbidden")
        elif (request.method != "POST" or str(request.url) != execution["capability"]["endpoint"]
              or request.extensions.get("effective_execution") != execution):
            raise ValueError("single-root provider endpoint/runtime forbidden")
        execution_mode = manifest["effective_execution_config"]["version"] if full else MODE
        expected = {"version": execution_mode + ":permit-v1", "mode": "MOCK_ONLY" if self.mock_only else "LIVE_SINGLE_DISPATCH",
            "run_id": self.run_id, "task_id": context.task_id, "call_id": context.external_call_id,
            "attempt": context.fence.attempt, "reservation_id": context.reservation_id,
            "fence": context.fence.model_dump(mode="json"), "execution_root": str(self.root),
            "task_hash": protocol_hash(task.model_dump(mode="json")),
            "request_hash": call.request_fingerprint, "config_hash": manifest["effective_execution_config_hash"],
            "method": request.method, "url": str(request.url),
            "wire_hash": hashlib.sha256(wire).hexdigest(), "max_dispatches": 1,
            "provider": call.provider, "model_or_tool": call.model_or_tool,
            "pricing_version": execution["pricing"]["version"] if execution else "PUBMED_NO_MODEL_CHARGE",
            "reserved_usd": execution["reserved_usd"] if execution else "0"}
        if self.issuer is None or self.issuer(copy.deepcopy(expected)) != expected:
            raise ValueError("missing or mismatched single-dispatch permit")
        # Immutable artifact, including call/task identity; no credentials/body.
        import json

        key = "single-root-permit:" + protocol_hash(expected)
        self.runtime.artifacts.persist_raw(key, json.dumps(expected, sort_keys=True).encode(),
            "application/json", request_fingerprint=protocol_hash(expected), run_id=self.run_id,
            task_id=context.task_id, execution_context_fingerprint=protocol_hash(expected))
        self.runtime.artifacts.persist_raw(key + ":wire", wire, "application/octet-stream",
            request_fingerprint=expected["wire_hash"], run_id=self.run_id,
            task_id=context.task_id, execution_context_fingerprint=protocol_hash(expected))


def validate_worker_providers(worker, run_id, config):
    from co_scientist.adapters.literature.pubmed import PubMedBridge
    from co_scientist.adapters.llm.multi_provider import NativeJSONProvider
    from co_scientist.adapters.llm.performance_responses import PerformanceResponsesProvider
    from co_scientist.agents.executor import RootPubMedProvider
    from co_scientist.runtime.bounded_transport import BoundedTransport

    deepseek = worker.providers.resolve("deepseek")
    sol = worker.providers.resolve("openai")
    retrieval = worker.providers.resolve("pubmed:root")
    if (type(deepseek) is not NativeJSONProvider or type(sol) is not PerformanceResponsesProvider
            or type(retrieval) is not RootPubMedProvider
            or type(retrieval.search) is not PubMedBridge or type(retrieval.summary) is not PubMedBridge):
        raise ValueError("single-root Worker requires production adapters, not fake verdicts")
    clients = [deepseek.client, sol.client, retrieval.search.provider.client, retrieval.summary.provider.client]
    if any(client is not clients[0] for client in clients):
        raise ValueError("single-root providers must share bounded execution ledger")
    t = clients[0]._transport
    if (not isinstance(t, BoundedTransport) or t.effective_config != config
            or t.single_root_gate is None or t.single_root_gate.run_id != run_id
            or t.single_root_gate.runtime.uow is not worker.runtime.uow
            or t.single_root_gate.issuer is None):
        raise ValueError("single-root Worker lacks exact durable execution/permit boundary")


def compose(runner, manifest, config, run_id):
    """Explicit opt-in composition. Merely loading YAML never enables sockets."""
    from types import SimpleNamespace

    from co_scientist.adapters.literature.pubmed import PubMedBridge, PubMedProvider
    from co_scientist.adapters.llm.multi_provider import NativeJSONProvider
    from co_scientist.adapters.llm.performance_responses import PerformanceResponsesProvider
    from co_scientist.agents.executor import RootPubMedProvider
    from co_scientist.runtime.bounded_transport import BoundedTransport
    from co_scientist.runtime.registry import ProviderRegistry

    authorization = runner.single_root_authorization
    if authorization is None or authorization["run_id"] != run_id:
        raise ValueError("single-root requires separate execution authorization")
    if full_ideation(manifest) and authorization.get("execution_mode") != config.version:
        raise ValueError("full Ideation requires its own bounded Run authorization")
    inner = authorization["transport"]
    mock = isinstance(inner, httpx.MockTransport)
    if not mock:
        if inner is not None or authorization.get("mode") != "LIVE_SINGLE_DISPATCH":
            raise ValueError("unsupported single-root transport/authorization")
        inner = httpx.AsyncHTTPTransport(retries=0, trust_env=False)
    gate = SingleRootPermitGate(runtime=SimpleNamespace(uow=runner.uow, artifacts=runner.artifacts),
        supervisor=runner.supervisor, run_id=run_id, root=runner.data_dir,
        issuer=authorization["permit_issuer"], mock_only=mock)
    transport = BoundedTransport(runner.data_dir / "dispatch" / run_id, config.dispatch_limits(),
        inner=inner, effective_config=config, single_root_gate=gate)
    client = httpx.AsyncClient(transport=transport, trust_env=False, follow_redirects=False)
    runner._native_client = client
    deepseek = NativeJSONProvider(client, provider="deepseek",
        api_key="offline-unused" if mock else runner.environment["DEEPSEEK_API_KEY"], response_capture_version=2)
    sol = PerformanceResponsesProvider.for_single_root(client,
        api_key="offline-unused" if mock else runner.environment["OPENAI_API_KEY"])
    pubmed = PubMedProvider(client, tool="co-scientist-single-root-dev-v1",
                            email=runner.environment.get("CO_SCIENTIST_PUBMED_EMAIL"))
    runner._build_worker(ProviderRegistry({"deepseek": deepseek, "openai": sol,
        manifest["profile"]["providers"]["literature"] + ":root":
            RootPubMedProvider(PubMedBridge(pubmed, "search"), PubMedBridge(pubmed, "summary"))}))
    from datetime import timedelta

    runner.worker.lease_duration = timedelta(seconds=config.envelope.lease_seconds)
    runner.worker.heartbeat_interval = timedelta(seconds=config.envelope.heartbeat_seconds)
