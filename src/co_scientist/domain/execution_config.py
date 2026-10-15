"""Opt-in, immutable execution resolution. No legacy defaults or live approval."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from co_scientist.domain.bayesian_ranking import TrueSkillConfig
from co_scientist.domain.budget import BudgetEstimate
from co_scientist.domain.population_evolution import BaselineSearchPolicy, ShortSearchPolicy
from co_scientist.domain.research_protocol import protocol_hash

if TYPE_CHECKING:
    from co_scientist.domain.generation_integration import GenerationPerformanceConfig
    from co_scientist.domain.single_root import FullIdeationConfig, SingleRootConfig

ROLE_SCHEMAS = {
    "DirectiveEthicsResultV1": "directive_ethics",
    "CandidateEthicsResultV1": "candidate_ethics",
    "RootQueryPlanResultV1": "query_planning",
    "RootLiteratureReviewResultV1": "source_review",
    "GroundedGenerationResultV1": "generation",
    "BaselineReflectionResultV1": "reflection",
    "BaselineRankingResultV1": "ranking",
    "BaselineEvolutionResultV1": "evolution",
}


class Contract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ScientificProfile(Contract):
    version: Literal["2608-scientific-execution-v1"]
    spec_sha256: Literal["000103561ed701648b3ca9b43521e174571cb4b638f6280263f55f5f6ff59874"]
    generation_temperature: float = Field(strict=True)
    search: BaselineSearchPolicy | ShortSearchPolicy
    trueskill: TrueSkillConfig

    @model_validator(mode="after")
    def frozen(self) -> ScientificProfile:
        if self.generation_temperature != 1.6 or self.trueskill != TrueSkillConfig():
            raise ValueError("frozen scientific profile mismatch")
        return self


class ProviderCapability(Contract):
    version: Literal["provider-capability-runtime-v1"]
    capability_id: str = Field(min_length=1)
    provider: Literal["fake", "deepseek"]
    model: str = Field(min_length=1)
    api: Literal["chat-completions-json-v1"]
    endpoint: Literal["https://api.deepseek.com/chat/completions"]
    thinking: Literal["enabled", "disabled"]
    response_format: Literal["json_object"]
    supported_sampling: tuple[Literal["temperature"], ...]
    supported_reasoning_efforts: tuple[Literal["low", "high", "max"], ...]
    max_context_tokens: int = Field(gt=0, strict=True)
    max_output_tokens: int = Field(gt=0, strict=True)
    status: Literal["OFFLINE_FAKE_ONLY", "CAPABILITY_UNVERIFIED"]

    @model_validator(mode="after")
    def offline(self) -> ProviderCapability:
        if self.status == "OFFLINE_FAKE_ONLY" and self.provider != "fake":
            raise ValueError("fake capability cannot authorize real provider")
        if len(set(self.supported_sampling)) != len(self.supported_sampling):
            raise ValueError("duplicate sampling capability")
        return self


class RoleRuntime(Contract):
    capability_id: str
    max_input_tokens: int = Field(gt=4096, strict=True)
    max_output_tokens: int = Field(gt=0, strict=True)
    max_wire_bytes: int = Field(gt=0, strict=True)
    max_response_bytes: int = Field(gt=0, strict=True)
    http_timeout_seconds: int = Field(gt=0, strict=True)
    deadline_seconds: int = Field(gt=0, strict=True)
    max_dispatches: int = Field(gt=0, strict=True)
    reasoning_effort: Literal["low", "high", "max"] | None = None


class PricingSnapshot(Contract):
    version: str = Field(min_length=1)
    model: Literal["deepseek-flash"]
    checked_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    source_url: str = Field(pattern=r"^https://")
    input_usd_per_million: Decimal = Field(gt=0)
    output_usd_per_million: Decimal = Field(gt=0)
    basis: Literal["frozen-cache-miss-upper-estimate"]

    def cost(self, inputs: int, outputs: int) -> Decimal:
        return (inputs * self.input_usd_per_million + outputs * self.output_usd_per_million) / Decimal(1_000_000)


class RunEnvelope(Contract):
    max_model_dispatches: int = Field(gt=0, strict=True)
    max_retrieval_dispatches: int = Field(ge=0, strict=True)
    max_input_tokens: int = Field(gt=0, strict=True)
    max_output_tokens: int = Field(gt=0, strict=True)
    max_reserved_usd: Decimal = Field(gt=0)
    max_wall_seconds: int = Field(gt=0, strict=True)
    lease_seconds: int = Field(gt=0, strict=True)
    heartbeat_seconds: int = Field(gt=0, strict=True)
    retrieval_response_bytes: int = Field(gt=0, strict=True)


class EffectiveExecutionConfig(Contract):
    version: Literal["effective-execution-config-v1"]
    scientific: ScientificProfile
    capabilities: tuple[ProviderCapability, ...]
    roles: Mapping[str, RoleRuntime]
    pricing: PricingSnapshot
    envelope: RunEnvelope
    estimator: Literal["utf8-wire-bytes-plus-4096-v1", "model-tokenizer-calibrated-v1"]

    @field_serializer("roles")
    def serialize_roles(self, roles: Mapping[str, RoleRuntime]) -> dict[str, Any]:
        return {k: v.model_dump(mode="json") for k, v in roles.items()}

    @model_validator(mode="after")
    def cross_layer(self) -> EffectiveExecutionConfig:
        if set(self.roles) != set(ROLE_SCHEMAS.values()):
            raise ValueError("exact independent role bindings required")
        ids = [c.capability_id for c in self.capabilities]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate capability identity")
        e = self.envelope
        if e.heartbeat_seconds * 2 >= e.lease_seconds:
            raise ValueError("lease requires heartbeat safety margin")
        inputs = outputs = calls = 0
        cost = Decimal(0)
        for name, role in self.roles.items():
            c = self.capability(role)
            if (c.model != self.pricing.model or role.max_output_tokens > c.max_output_tokens
                    or role.max_input_tokens + role.max_output_tokens > c.max_context_tokens
                    or (self.estimator == "utf8-wire-bytes-plus-4096-v1"
                        and role.max_wire_bytes + 4096 > role.max_input_tokens)
                    or role.http_timeout_seconds + 30 > role.deadline_seconds
                    or role.deadline_seconds > e.max_wall_seconds
                    or (c.thinking == "disabled" and role.reasoning_effort is not None)
                    or (role.reasoning_effort is not None and role.reasoning_effort not in c.supported_reasoning_efforts)):
                raise ValueError("invalid cross-layer role bounds")
            if name == "generation" and (c.thinking != "disabled"
                    or "temperature" not in c.supported_sampling):
                raise ValueError("Generation requires declared nonthinking temperature capability")
            calls += role.max_dispatches
            inputs += role.max_input_tokens * role.max_dispatches
            outputs += role.max_output_tokens * role.max_dispatches
            cost += self.pricing.cost(role.max_input_tokens, role.max_output_tokens) * role.max_dispatches
        if (calls > e.max_model_dispatches or inputs > e.max_input_tokens
                or outputs > e.max_output_tokens or cost > e.max_reserved_usd
                or e.max_retrieval_dispatches < 24):
            raise ValueError("run envelope cannot reserve declared role plan")
        object.__setattr__(self, "roles", MappingProxyType(dict(self.roles)))
        return self

    def capability(self, role: RoleRuntime) -> ProviderCapability:
        values = [c for c in self.capabilities if c.capability_id == role.capability_id]
        if len(values) != 1:
            raise ValueError("missing exact capability; no fallback")
        return values[0]

    def task(self, schema: str) -> dict[str, Any]:
        name = ROLE_SCHEMAS[schema]
        role = self.roles[name]
        cap = self.capability(role)
        return {"version": "effective-task-execution-v1", "config_hash": protocol_hash(self.model_dump(mode="json")),
            "role": name, "schema_id": schema, "runtime": role.model_dump(mode="json"),
            "capability": cap.model_dump(mode="json"), "pricing": self.pricing.model_dump(mode="json"),
            "estimator": self.estimator, "temperature": self.scientific.generation_temperature if name == "generation" else None,
            "reserved_usd": str(self.pricing.cost(role.max_input_tokens, role.max_output_tokens))}

    def dispatch_limits(self):
        """Reuse durable HTTP ledger; role bounds override its per-call envelope."""
        from co_scientist.domain.dispatch_limits import DispatchLimits
        from co_scientist.domain.pilot_pricing import effective_task_pricing

        upper = self.task("BaselineEvolutionResultV1")
        upper["runtime"]["max_input_tokens"] = max(r.max_input_tokens for r in self.roles.values())
        upper["runtime"]["max_output_tokens"] = max(r.max_output_tokens for r in self.roles.values())
        upper["reserved_usd"] = str(self.pricing.cost(upper["runtime"]["max_input_tokens"],
                                                     upper["runtime"]["max_output_tokens"]))
        e = self.envelope
        return DispatchLimits(max_model_calls=e.max_model_dispatches,
            max_literature_calls=e.max_retrieval_dispatches, max_input_tokens=e.max_input_tokens,
            max_output_tokens=e.max_output_tokens, max_usd=e.max_reserved_usd,
            max_wall_seconds=e.max_wall_seconds, output_tokens_per_call=upper["runtime"]["max_output_tokens"],
            pricing=effective_task_pricing(upper))


def frozen_execution(manifest: Mapping[str, Any]) -> EffectiveExecutionConfig | GenerationPerformanceConfig | SingleRootConfig | FullIdeationConfig | None:
    document = manifest.get("effective_execution_config")
    if document is None:
        if "effective_execution_config_hash" in manifest:
            raise ValueError("missing frozen effective config")
        return None
    from co_scientist.domain.generation_integration import PROFILE, GenerationPerformanceConfig
    from co_scientist.domain.single_root import (
        FULL_MODE,
        G3_MODE,
        MODE,
        FullIdeationConfig,
        SingleRootConfig,
    )

    config = (FullIdeationConfig.model_validate(document) if document.get("version") in {FULL_MODE, G3_MODE} else
              SingleRootConfig.model_validate(document) if document.get("version") == MODE else
              GenerationPerformanceConfig.model_validate(document) if document.get("version") == PROFILE
              else EffectiveExecutionConfig.model_validate(document))
    if protocol_hash(config.model_dump(mode="json")) != manifest.get("effective_execution_config_hash"):
        raise ValueError("effective config identity mismatch")
    return config


def validate_task_execution(manifest: Mapping[str, Any], schema: str,
                            inputs: Mapping[str, Any], estimate: BudgetEstimate) -> None:
    config = frozen_execution(manifest)
    if config is None:
        if "effective_execution" in inputs:
            raise ValueError("unfrozen task runtime")
        return
    if schema not in ROLE_SCHEMAS:
        if "effective_execution" in inputs:
            raise ValueError("unexpected runtime on retrieval task")
        return
    expected = config.task(schema)
    if inputs.get("effective_execution") != expected:
        raise ValueError("task runtime differs from frozen run")
    b = inputs["ideation_task_binding"]
    cap = expected["capability"]
    if any(b[k] != cap[v] for k, v in (("provider", "provider"), ("model", "model"),
            ("api", "api"), ("thinking_mode", "thinking"), ("capability_id", "capability_id"))):
        raise ValueError("task capability identity mismatch")
    if (estimate.model_calls != 1 or estimate.cost_usd != Decimal(expected["reserved_usd"])
            or estimate.input_tokens != expected["runtime"]["max_input_tokens"]
            or estimate.output_tokens != expected["runtime"]["max_output_tokens"]):
        raise ValueError("task reservation differs from effective token/pricing bounds")


def validate_wire(task: Mapping[str, Any], wire: bytes) -> None:
    if task.get("continuous_policy") is not None:
        from co_scientist.domain.continuous_execution import ContinuousPolicy

        policy = ContinuousPolicy.model_validate(task["continuous_policy"])
        if len(wire) > policy.transport_body_bytes:
            raise ValueError("HTTP_BODY_CAPACITY_EXCEEDED")
        # Token capacity is checked against the actual serialized body by the
        # context planner and again at the final bounded HTTP boundary.
        return
    if task.get("version") == "generation-performance-v1":
        r = task["runtime"]
        if (len(wire) > r["max_wire_bytes"] or len(wire) + 4096 > r["max_input_tokens"]
                or r["max_input_tokens"] + r["max_output_tokens"] > 272000):
            raise ValueError("CONTEXT_CAPACITY_EXCEEDED: performance wire")
        return
    r = RoleRuntime.model_validate(task["runtime"])
    c = ProviderCapability.model_validate(task["capability"])
    if task["version"] != "effective-task-execution-v1" or task["estimator"] != "utf8-wire-bytes-plus-4096-v1":
        raise ValueError("unsupported task runtime version/estimator")
    if len(wire) > r.max_wire_bytes or len(wire) + 4096 > r.max_input_tokens:
        raise ValueError("CONTEXT_CAPACITY_EXCEEDED: complete wire")
    if r.max_input_tokens + r.max_output_tokens > c.max_context_tokens:
        raise ValueError("input/output context exceeds capability")
    if r.max_output_tokens > c.max_output_tokens:
        raise ValueError("output exceeds capability")


def generation_input_capacity(manifest: Mapping[str, Any]) -> int:
    """Preflight subset only; provider still checks complete wire."""
    config = frozen_execution(manifest)
    if config is not None:
        if config.version in {"generation-performance-v1", "single-root-dev-live-v1", "ideation-performance-dev-live-v1", "ideation-performance-dev-g3-v1"}:
            return config.task("GroundedGenerationResultV1")["runtime"]["max_wire_bytes"]
        return config.roles["generation"].max_wire_bytes
    p = manifest["ideation_prerequisite_contract"]["policy"]
    return min(p["generation_input_max_bytes"], p["generation_input_max_tokens"])
