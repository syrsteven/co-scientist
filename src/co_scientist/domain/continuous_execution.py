"""Explicit opt-in capacity and retry policy; historical execution stays unchanged."""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any, Literal

from pydantic import Field, model_validator

from co_scientist.domain.execution_config import Contract


class OutputPolicy(Contract):
    initial: int = Field(gt=0)
    ceiling: int = Field(gt=0)
    observed_p99: int = Field(ge=0)
    reasoning_p99: int = Field(ge=0)
    samples: int = Field(ge=0)

    @model_validator(mode="after")
    def ordered(self):
        if self.initial > self.ceiling:
            raise ValueError("adaptive output initial exceeds ceiling")
        return self

    def budget(self, input_tokens: int, source_count: int, attempt: int,
               length_failures: int) -> int:
        # Observations include reasoning tokens; the extra reasoning allowance
        # is useful only when no complete output-usage history exists.
        history = math.ceil(self.observed_p99 * 1.75) if self.samples >= 5 else self.initial
        size = source_count * 300 if source_count else min(input_tokens // 8, self.ceiling)
        return min(self.ceiling, max(self.initial, history, size) * 2 ** length_failures)


class ContinuousPolicy(Contract):
    version: Literal["continuous-ideation-policy-v1"]
    max_attempts: Literal[3] = 3
    max_retry_dispatches: int = Field(ge=0, le=48)
    max_retrieval_retry_attempts: int = Field(default=4, ge=0, le=8)
    unknown_delivery_retries: Literal[1] = 1
    transport_body_bytes: int = Field(ge=4_000_000, le=32_000_000)
    response_body_bytes: int = Field(ge=8_000_000, le=64_000_000)
    safety_fraction: float = Field(ge=0.05, le=0.5)
    safety_tokens: int = Field(ge=256)
    deepseek_tokenizer_path: str
    deepseek_tokenizer_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    openai_encoding: Literal["o200k_base"]
    openai_tokenizer_path: str
    openai_tokenizer_sha256: Literal["446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d"]
    openai_encoding_status: Literal["usage-calibrated-estimate-not-official-model-map"]
    calibration_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    outputs: dict[str, OutputPolicy]
    retry_base_seconds: int = Field(ge=1)
    retry_max_seconds: int = Field(ge=1, le=300)
    risk_usd: Decimal = Field(gt=0)


def policy_for(manifest: Any) -> ContinuousPolicy | None:
    config = manifest.get("effective_execution_config", {})
    value = config.get("continuous_policy")
    return ContinuousPolicy.model_validate(value) if value is not None else None


def execution_policy(execution: dict) -> ContinuousPolicy | None:
    value = execution.get("continuous_policy")
    return ContinuousPolicy.model_validate(value) if value is not None else None


def retry_delay(policy: ContinuousPolicy, attempt: int, seed: str,
                retry_after: float | None = None) -> float:
    import hashlib

    if retry_after is not None and retry_after >= 0:
        # A server wait longer than the execution budget is not shortened.
        return retry_after
    jitter = int(hashlib.sha256(f"{seed}:{attempt}".encode()).hexdigest()[:8], 16) / 2**32
    return min(policy.retry_max_seconds, policy.retry_base_seconds * 2**(attempt - 1)) * (1+jitter/4)


def durable_task_payload(events, task_id: str) -> dict | None:
    """Latest additive attempt snapshot; original enqueue remains immutable."""
    from co_scientist.ports.external_provider import thaw_json

    snapshots = [thaw_json(e.payload["task_definition"]) for e in events
                 if e.event_type == "ContinuousAttemptPreparedV1" and e.payload["task_id"] == task_id]
    if snapshots:
        return snapshots[-1]
    enqueues = [thaw_json(e.payload) for e in events
                if e.event_type == "TaskEnqueued" and e.payload["task_id"] == task_id]
    return enqueues[0] if len(enqueues) == 1 else None


def logical_binding(binding):
    """Attempt may change only under durable retry authorization."""
    return binding.model_copy(update={"attempt": 1})
