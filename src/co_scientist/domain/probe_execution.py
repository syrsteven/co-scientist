"""Versioned operational ceiling for the two-call ClaimLineage compatibility probe.

This is not a scientific budget or an admission policy.  It can only reject
external dispatches that the ordinary Run budget would otherwise allow.
"""

from collections.abc import Mapping
from decimal import ROUND_CEILING, Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from co_scientist.domain.claim_verification import scientific_hash
from co_scientist.domain.dispatch_limits import DispatchLimits
from co_scientist.domain.pilot_pricing import DeepSeekPilotPricing


class ProbeExecutionEnvelopeV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal["compatibility-probe-execution-v1"] = "compatibility-probe-execution-v1"
    max_population_evolution_calls: Literal[1] = 1
    max_offspring_decomposition_calls: Literal[1] = 1
    max_total_model_calls: Literal[2] = 2
    max_literature_calls: Literal[0] = 0
    max_retries: Literal[0] = 0
    max_structural_reasks: Literal[0] = 0
    max_input_tokens: Literal[131072] = 131072
    max_output_tokens: Literal[16384] = 16384
    output_tokens_per_call: Literal[8192] = 8192
    max_reserved_usd: Decimal = Field(default=Decimal("0.06094848"), gt=0)
    max_wall_seconds: int = Field(default=1200, ge=1)
    pricing: DeepSeekPilotPricing

    @model_validator(mode="after")
    def validate_exact_bound(self) -> "ProbeExecutionEnvelopeV1":
        if (
            self.pricing.model != "deepseek-flash"
            or self.pricing.input_token_limit != 65536
            or self.pricing.reserve_usd_per_call != Decimal("0.03047424")
            or self.max_reserved_usd != 2 * self.pricing.reserve_usd_per_call
            or self.max_input_tokens != 2 * self.pricing.input_token_limit
            or self.max_output_tokens != 2 * self.output_tokens_per_call
        ):
            raise ValueError("probe envelope differs from frozen two-call pricing/token bound")
        return self

    def dispatch_limits(self) -> DispatchLimits:
        """Independent HTTP ledger; normal scientific limits remain an inner ledger."""

        return DispatchLimits(
            max_model_calls=self.max_total_model_calls,
            max_literature_calls=self.max_literature_calls,
            max_input_tokens=self.max_input_tokens,
            max_output_tokens=self.max_output_tokens,
            max_usd=self.max_reserved_usd,
            max_wall_seconds=self.max_wall_seconds,
            output_tokens_per_call=self.output_tokens_per_call,
            pricing=self.pricing,
        )


def probe_envelope_for_manifest(
    manifest: Mapping[str, Any],
) -> ProbeExecutionEnvelopeV1 | None:
    """Reject a stale/tampered operational selector; no legacy default is invented."""

    profile = manifest.get("profile")
    selected = profile.get("probe_execution_envelope") if isinstance(profile, Mapping) else None
    frozen = manifest.get("probe_execution_envelope")
    frozen_hash = manifest.get("probe_execution_envelope_hash")
    if selected is None and frozen is None and frozen_hash is None:
        return None
    if not isinstance(selected, Mapping) or not isinstance(frozen, Mapping):
        raise TypeError("probe execution envelope profile/manifest mismatch")
    policy = ProbeExecutionEnvelopeV1.model_validate(frozen)
    if (dict(selected) != policy.model_dump(mode="json")
            or frozen_hash != scientific_hash(policy.model_dump(mode="json"))):
        raise ValueError("probe execution envelope hash or profile mismatch")
    return policy


class GenerationCapabilityProbeEnvelopeV1(BaseModel):
    """Standalone diagnostic authorization, never baseline readiness authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    version: Literal["generation-capability-probe-v1"] = "generation-capability-probe-v1"
    provider: Literal["deepseek"] = "deepseek"
    model: Literal["deepseek-flash"] = "deepseek-flash"
    endpoint: Literal["https://api.deepseek.com/chat/completions"] = (
        "https://api.deepseek.com/chat/completions")
    thinking_mode: Literal["disabled"] = "disabled"
    temperature: float = Field(default=1.6, strict=True)
    max_tokens: Literal[1024] = 1024
    response_format: Literal["json_object"] = "json_object"
    stream: Literal[False] = False
    max_dispatches: Literal[1] = 1
    max_retries: Literal[0] = 0
    max_reasks: Literal[0] = 0
    max_literature_calls: Literal[0] = 0
    max_input_tokens: Literal[16384] = 16384
    max_wire_bytes: Literal[12288] = 12288
    http_timeout_seconds: Literal[60] = 60
    max_wall_seconds: Literal[120] = 120
    max_reserved_usd: Decimal = Decimal("0.03047424")
    capability_id: Literal["deepseek-flash-disabled-generation-probe-v1"] = (
        "deepseek-flash-disabled-generation-probe-v1")
    pricing: DeepSeekPilotPricing

    @model_validator(mode="after")
    def validate_probe(self) -> "GenerationCapabilityProbeEnvelopeV1":
        if (self.temperature != 1.6 or self.max_reserved_usd != Decimal("0.03047424")
                or self.pricing.version != "deepseek-flash-generation-probe-2026-10-10-v1"
                or self.pricing.input_token_limit != self.max_input_tokens
                or self.pricing.input_usd_per_million != Decimal("0.30")
                or self.pricing.output_usd_per_million != Decimal("1.20")
                or self.pricing.reserve_usd_per_call != self.max_reserved_usd):
            raise ValueError("Generation probe parameters/pricing differ from frozen policy")
        return self

    def dispatch_limits(self) -> DispatchLimits:
        return DispatchLimits(max_model_calls=1, max_literature_calls=0,
            max_input_tokens=self.max_input_tokens, max_output_tokens=self.max_tokens,
            max_usd=self.max_reserved_usd, max_wall_seconds=self.max_wall_seconds,
            output_tokens_per_call=self.max_tokens, pricing=self.pricing)


class GenerationProbePermitV1(BaseModel):
    """Explicit task/request-bound permit; live permits need separate user authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    version: Literal["generation-probe-permit-v1"] = "generation-probe-permit-v1"
    mode: Literal["OFFLINE_MOCK", "LIVE_SINGLE_DISPATCH"]
    authorization_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    execution_root_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    envelope_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    fixture_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    request_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    run_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    attempt: Literal[1] = 1


class GenerationCapabilityProbeEnvelopeV2(BaseModel):
    """Resource revision only; scientific fixture/prompt/schema stay unchanged.

    Reserve worst-case peak uncached token cost plus 25%, rounded UP to cents.
    The frozen estimate is not an invoice or a claim about cache/discount pricing.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    version: Literal["generation-capability-probe-v2"] = "generation-capability-probe-v2"
    provider: Literal["deepseek"] = "deepseek"
    model: Literal["deepseek-flash"] = "deepseek-flash"
    endpoint: Literal["https://api.deepseek.com/chat/completions"] = (
        "https://api.deepseek.com/chat/completions")
    thinking_mode: Literal["disabled"] = "disabled"
    temperature: float = Field(default=1.6, strict=True)
    max_tokens: Literal[16384] = 16384
    response_format: Literal["json_object"] = "json_object"
    stream: Literal[False] = False
    max_dispatches: Literal[1] = 1
    max_retries: Literal[0] = 0
    max_reasks: Literal[0] = 0
    max_literature_calls: Literal[0] = 0
    max_input_tokens: Literal[65536] = 65536
    max_wire_bytes: Literal[61440] = 61440
    http_timeout_seconds: Literal[300] = 300
    max_wall_seconds: Literal[360] = 360
    reservation_margin: Literal["1.25"] = "1.25"
    capability_id: Literal["deepseek-flash-disabled-generation-probe-v2"] = (
        "deepseek-flash-disabled-generation-probe-v2")
    pricing: DeepSeekPilotPricing

    @property
    def max_reserved_usd(self) -> Decimal:
        return (self.pricing.minimum_reserve(self.max_tokens) * Decimal(
            self.reservation_margin)).quantize(Decimal("0.01"), rounding=ROUND_CEILING)

    @model_validator(mode="after")
    def validate_probe(self) -> "GenerationCapabilityProbeEnvelopeV2":
        if (self.temperature != 1.6
                or self.pricing.version != "deepseek-flash-generation-probe-2026-10-10-limits-v2"
                or self.pricing.input_token_limit != self.max_input_tokens
                or self.pricing.input_usd_per_million != Decimal("0.30")
                or self.pricing.output_usd_per_million != Decimal("1.20")
                or self.pricing.reserve_usd_per_call != self.max_reserved_usd):
            raise ValueError("Generation V2 probe pricing/reservation identity mismatch")
        return self

    def dispatch_limits(self) -> DispatchLimits:
        return DispatchLimits(max_model_calls=1, max_literature_calls=0,
            max_input_tokens=self.max_input_tokens, max_output_tokens=self.max_tokens,
            max_usd=self.max_reserved_usd, max_wall_seconds=self.max_wall_seconds,
            output_tokens_per_call=self.max_tokens, pricing=self.pricing)


class GenerationProbePermitV2(BaseModel):
    """Independent V2 authorization; a V1 permit cannot unlock V2."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    version: Literal["generation-probe-permit-v2"] = "generation-probe-permit-v2"
    mode: Literal["OFFLINE_MOCK", "LIVE_SINGLE_DISPATCH"]
    authorization_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    execution_root_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    envelope_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    fixture_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    request_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    wire_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    run_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    call_id: str = Field(min_length=1)
    attempt: Literal[1] = 1


def generation_probe_envelope(value: Any
        ) -> GenerationCapabilityProbeEnvelopeV1 | GenerationCapabilityProbeEnvelopeV2:
    if isinstance(value, Mapping) and value.get("version") == "generation-capability-probe-v2":
        return GenerationCapabilityProbeEnvelopeV2.model_validate(value)
    if isinstance(value, Mapping) and value.get("version") == "generation-capability-probe-v1":
        return GenerationCapabilityProbeEnvelopeV1.model_validate(value)
    raise ValueError("explicit Generation probe envelope version required")


def generation_probe_permit(value: Any) -> GenerationProbePermitV1 | GenerationProbePermitV2:
    if isinstance(value, Mapping) and value.get("version") == "generation-probe-permit-v2":
        return GenerationProbePermitV2.model_validate(value)
    if isinstance(value, Mapping) and value.get("version") == "generation-probe-permit-v1":
        return GenerationProbePermitV1.model_validate(value)
    raise ValueError("explicit Generation probe permit version required")
