"""One-root diagnostic scope; never authorizes a network request by itself."""

from decimal import Decimal
from typing import Literal

from pydantic import Field, model_serializer, model_validator

from co_scientist.domain.execution_config import Contract, RunEnvelope
from co_scientist.domain.generation_integration import GenerationPerformanceConfig
from co_scientist.domain.research_protocol import protocol_hash

MODE = "single-root-dev-live-v1"
SCHEMAS = ("DirectiveEthicsResultV1", "RootQueryPlanResultV1", "RootRetrievalResultV2",
           "RootLiteratureReviewResultV1", "GroundedGenerationResultV1")
FULL_MODE = "ideation-performance-dev-live-v1"
G3_MODE = "ideation-performance-dev-g3-v1"


def single_root_limits():
    return RunEnvelope(max_model_dispatches=4, max_retrieval_dispatches=6,
        max_input_tokens=517312, max_output_tokens=45056, max_reserved_usd=Decimal(1),
        max_wall_seconds=1800, lease_seconds=600, heartbeat_seconds=60,
        retrieval_response_bytes=4000000)


class SingleRootConfig(Contract):
    version: Literal["single-root-dev-live-v1"]
    performance: GenerationPerformanceConfig
    activation: Literal["REQUIRES_SEPARATE_LIVE_PERMIT"] = "REQUIRES_SEPARATE_LIVE_PERMIT"
    limits: RunEnvelope = Field(default_factory=single_root_limits)

    @model_validator(mode="after")
    def frozen_limits(self):
        if self.limits != single_root_limits():
            raise ValueError("single-root envelope differs from versioned maximum")
        tasks = [self.task(s) for s in SCHEMAS if s != "RootRetrievalResultV2"]
        if (sum(Decimal(t["reserved_usd"]) for t in tasks) > self.limits.max_reserved_usd
                or sum(t["runtime"]["max_input_tokens"] for t in tasks) > self.limits.max_input_tokens
                or sum(t["runtime"]["max_output_tokens"] for t in tasks) > self.limits.max_output_tokens):
            raise ValueError("single-root tasks exceed frozen envelope")
        return self

    @property
    def scientific(self):
        return self.performance.scientific

    @property
    def envelope(self):
        return self.limits

    @property
    def roles(self):
        return {k: v.model_copy(update={"max_dispatches": 1})
                for k, v in self.performance.roles.items()}

    def task(self, schema):
        if schema not in SCHEMAS or schema == "RootRetrievalResultV2":
            raise ValueError("single-root role forbidden")
        t = self.performance.task(schema)
        generation = schema == "GroundedGenerationResultV1"
        t["config_hash"] = protocol_hash(self.model_dump(mode="json"))
        t["single_root_mode"] = MODE
        t["runtime"].update(max_dispatches=1, http_timeout_seconds=300, deadline_seconds=360)
        capability = f"{MODE}:{t['role']}"
        t["runtime"]["capability_id"] = capability
        t["capability"].update(provider="openai" if generation else "deepseek",
            status="CAPABILITY_UNVERIFIED", capability_id=capability)
        return t

    def dispatch_limits(self):
        from co_scientist.domain.dispatch_limits import DispatchLimits
        from co_scientist.domain.pilot_pricing import effective_task_pricing

        t = self.task("GroundedGenerationResultV1")
        e = self.limits
        return DispatchLimits(max_model_calls=e.max_model_dispatches, max_literature_calls=e.max_retrieval_dispatches,
            max_input_tokens=e.max_input_tokens, max_output_tokens=e.max_output_tokens, max_usd=e.max_reserved_usd,
            max_wall_seconds=e.max_wall_seconds, output_tokens_per_call=t["runtime"]["max_output_tokens"],
            pricing=effective_task_pricing(t))


def single_root(manifest):
    document = manifest.get("effective_execution_config", {})
    return document.get("version") == MODE


class FullIdeationConfig(Contract):
    """Separate full-loop envelope. Loading it does not authorize HTTP."""

    version: Literal["ideation-performance-dev-live-v1", "ideation-performance-dev-g3-v1"]
    performance: GenerationPerformanceConfig
    activation: Literal["REQUIRES_SEPARATE_LIVE_PERMIT"] = "REQUIRES_SEPARATE_LIVE_PERMIT"
    continuous_policy: dict | None = None

    @model_serializer(mode="wrap")
    def serialize_legacy(self, handler):
        value = handler(self)
        if self.continuous_policy is None:
            value.pop("continuous_policy", None)
        return value

    @model_validator(mode="after")
    def cycle_identity(self):
        target = 3 if self.version == G3_MODE else 10
        expected = "2608-ideation-search-g3-v1" if target == 3 else "2608-ideation-search-v1"
        if (self.scientific.search.reproduction_transitions != target
                or self.scientific.search.version != expected):
            raise ValueError("execution mode/search cycle identity mismatch")
        if self.continuous_policy is not None:
            from co_scientist.domain.continuous_execution import ContinuousPolicy

            policy = ContinuousPolicy.model_validate(self.continuous_policy)
            if self.version != G3_MODE or self.envelope.max_reserved_usd != policy.risk_usd:
                raise ValueError("continuous policy requires independent G3 risk envelope")
            if set(policy.outputs) != set(self.roles):
                raise ValueError("continuous policy requires all role output bindings")
            from co_scientist.domain.execution_config import ROLE_SCHEMAS

            initial = Decimal(0)
            retry_costs = []
            for schema, role in ROLE_SCHEMAS.items():
                task = self.task(schema)
                cost = Decimal(task["reserved_usd"])
                initial += cost * self.roles[role].max_dispatches
                retry_costs.extend([cost] * ((policy.max_attempts-1)*self.roles[role].max_dispatches))
            if initial + sum(sorted(retry_costs, reverse=True)[:policy.max_retry_dispatches]) > policy.risk_usd:
                raise ValueError("continuous initial and retry plan exceeds frozen risk budget")
        if self.version == G3_MODE and self.continuous_policy is None:
            caps = {"directive_ethics": 1, "query_planning": 4, "source_review": 4,
                    "generation": 8, "candidate_ethics": 20, "reflection": 10,
                    "ranking": 60, "evolution": 12}
            if ({k: v.max_dispatches for k, v in self.roles.items()} != caps
                    or self.envelope.max_model_dispatches != 119
                    or self.envelope.max_retrieval_dispatches != 24
                    or self.envelope.max_reserved_usd != Decimal(15)
                    or self.envelope.max_wall_seconds != 7200):
                raise ValueError("G3 role/Run envelope differs from approved preparation")
        return self

    @property
    def scientific(self):
        return self.performance.scientific

    @property
    def envelope(self):
        return self.performance.envelope

    @property
    def roles(self):
        return self.performance.roles

    def task(self, schema):
        t = self.performance.task(schema)
        t["config_hash"] = protocol_hash(self.model_dump(mode="json"))
        t["live_execution_mode"] = self.version
        capability = f"{self.version}:{t['role']}"
        t["runtime"]["capability_id"] = capability
        t["capability"].update(provider="openai" if schema == "GroundedGenerationResultV1" else "deepseek",
            status="CAPABILITY_UNVERIFIED", capability_id=capability)
        if self.continuous_policy is not None:
            from co_scientist.domain.continuous_execution import ContinuousPolicy

            policy = ContinuousPolicy.model_validate(self.continuous_policy)
            t["continuous_policy"] = policy.model_dump(mode="json")
            t["runtime"].update(max_wire_bytes=policy.transport_body_bytes,
                max_response_bytes=policy.response_body_bytes,
                max_output_tokens=policy.outputs[t["role"]].ceiling,
                max_dispatches=min(t["runtime"]["max_dispatches"]+policy.max_retry_dispatches,
                    t["runtime"]["max_dispatches"]*policy.max_attempts))
            t["estimator"] = "model-tokenizer-calibrated-v1"
            if schema == "GroundedGenerationResultV1":
                t["capability"].update(max_context_tokens=1050000, max_output_tokens=128000)
            if t["runtime"]["max_output_tokens"] > t["capability"]["max_output_tokens"]:
                raise ValueError("adaptive output ceiling exceeds declared provider capacity")
            prices = t["pricing"]
            t["reserved_usd"] = str((Decimal(t["runtime"]["max_input_tokens"])*Decimal(prices["input_usd_per_million"])
                + Decimal(t["runtime"]["max_output_tokens"])*Decimal(prices["output_usd_per_million"]))/1000000)
        return t

    def dispatch_limits(self):
        return self.performance.dispatch_limits()


def full_ideation(manifest):
    return manifest.get("effective_execution_config", {}).get("version") in {FULL_MODE, G3_MODE}


def validate_full_scope(task, *, max_attempts: int | None = None):
    from co_scientist.domain.execution_config import ROLE_SCHEMAS

    p = task.payload
    b = p.get("inputs", {}).get("ideation_task_binding", {})
    if (p.get("output_schema_id") not in {*ROLE_SCHEMAS, "RootRetrievalResultV2"}
            or not 1 <= b.get("attempt", 0) <= (
                max_attempts or (3 if p.get("inputs", {}).get("effective_execution", {}).get("continuous_policy") else 1))):
        raise ValueError("full Ideation task outside original-attempt scope")
    # Detailed slot/content/parent/epoch validation remains Supervisor-owned;
    # this scope check cannot grant prerequisite or scientific authority.


def validate_scope(task):
    p = task.payload
    b = p.get("inputs", {}).get("ideation_task_binding", {})
    schema = p.get("output_schema_id")
    slot = None if schema == "DirectiveEthicsResultV1" else "root-slot-0"
    if (schema not in SCHEMAS or b.get("root_slot_id") != slot or b.get("slot_id") != slot
            or b.get("attempt") != 1 or b.get("redesign_of") or b.get("scientific_parent_ids")):
        raise ValueError("single-root task outside diagnostic envelope")
