"""Explicit performance-method composition; never changes scientific baseline v1."""

from decimal import Decimal
from typing import Any, Literal

from pydantic import Field, model_validator

from co_scientist.domain.execution_config import Contract, EffectiveExecutionConfig
from co_scientist.domain.research_protocol import protocol_hash

PROFILE = "generation-performance-v1"
PROMPT_SHA = "82d9d972ac8c4281925110fde200d0ccca25a5e21c6fd9cd7accfdcbfe82e12d"


class GenerationPerformanceConfig(Contract):
    version: Literal["generation-performance-v1"]
    # This immutable baseline supplies ONLY unchanged roles/scheduling. Its
    # Generation task is never used by this explicitly different method.
    baseline: EffectiveExecutionConfig
    model: Literal["gpt-6.1-sol"] = "gpt-6.1-sol"
    api: Literal["openai-responses-strict-v1"] = "openai-responses-strict-v1"
    reasoning_effort: Literal["medium"] = "medium"
    prompt_sha256: Literal["82d9d972ac8c4281925110fde200d0ccca25a5e21c6fd9cd7accfdcbfe82e12d"] = "82d9d972ac8c4281925110fde200d0ccca25a5e21c6fd9cd7accfdcbfe82e12d"
    activation: Literal["OFFLINE_FAKE_ONLY"] = "OFFLINE_FAKE_ONLY"
    max_input_tokens: int = Field(default=124096, ge=4097, le=200000)
    max_output_tokens: Literal[32768] = 32768
    max_wire_bytes: int = Field(default=120000, gt=0)
    max_response_bytes: Literal[4000000] = 4000000
    pricing_version: Literal["sol-generation-conservative-2026-10-12-v1"] = "sol-generation-conservative-2026-10-12-v1"

    @model_validator(mode="after")
    def bounds(self):
        if (self.baseline.estimator == "utf8-wire-bytes-plus-4096-v1"
                and self.max_wire_bytes + 4096 > self.max_input_tokens):
            raise ValueError("wire exceeds conservative input bound")
        old = self.baseline.roles["generation"]
        extra = (self.reserve - self.baseline.pricing.cost(old.max_input_tokens, old.max_output_tokens)) * old.max_dispatches
        cost = sum(self.baseline.pricing.cost(r.max_input_tokens, r.max_output_tokens) * r.max_dispatches
                   for r in self.baseline.roles.values())
        if cost + extra > self.envelope.max_reserved_usd:
            raise ValueError("performance plan exceeds frozen run budget")
        if (sum(r.max_input_tokens*r.max_dispatches for r in self.baseline.roles.values())
                + (self.max_input_tokens-old.max_input_tokens)*old.max_dispatches > self.envelope.max_input_tokens
                or sum(r.max_output_tokens*r.max_dispatches for r in self.baseline.roles.values())
                + (self.max_output_tokens-old.max_output_tokens)*old.max_dispatches > self.envelope.max_output_tokens):
            raise ValueError("performance plan exceeds run token envelope")
        return self

    @property
    def reserve(self):
        return (Decimal(self.max_input_tokens)*Decimal('2.50')+Decimal(self.max_output_tokens)*10)/1000000

    @property
    def scientific(self):
        return self.baseline.scientific

    @property
    def envelope(self):
        return self.baseline.envelope

    @property
    def roles(self):
        return self.baseline.roles

    def task(self, schema: str) -> dict[str, Any]:
        task = self.baseline.task(schema)
        task['config_hash'] = protocol_hash(self.model_dump(mode='json'))
        if schema != 'GroundedGenerationResultV1':
            return task
        return {**task, 'version': PROFILE, 'temperature': None,
            'prompt_sha256': self.prompt_sha256,
            'runtime': {**task['runtime'], 'capability_id': 'offline-sol-performance-v1',
                'reasoning_effort': 'medium', 'max_input_tokens': self.max_input_tokens,
                'max_output_tokens': self.max_output_tokens, 'max_wire_bytes': self.max_wire_bytes,
                'max_response_bytes': self.max_response_bytes},
            'capability': {'version': PROFILE, 'capability_id': 'offline-sol-performance-v1',
                'provider': 'fake', 'model': self.model, 'api': self.api,
                'endpoint': 'https://api.openai.com/v1/responses', 'thinking': 'enabled',
                'status': 'OFFLINE_FAKE_ONLY'},
            'pricing': {'version': self.pricing_version, 'model': self.model,
                'checked_at': '2026-10-12', 'source_url': 'https://developers.openai.com/api/docs/pricing',
                'input_usd_per_million': '2.50', 'output_usd_per_million': '10'},
            'reserved_usd': str(self.reserve)}

    def dispatch_limits(self):
        # Shared ledger's global envelope remains unchanged; each exact task
        # supplies its own frozen model/endpoint/reservation.
        return self.baseline.dispatch_limits()


def performance_task(task: dict) -> bool:
    return task.get('version') == PROFILE


def performance_schema() -> dict:
    from co_scientist.domain.ideation_prerequisites import CandidateProposalV1

    candidate = CandidateProposalV1.model_json_schema()
    candidate['required'] = list(candidate['properties'])
    for field in candidate['properties'].values():
        field.pop('default', None)
    return {'type': 'object', 'properties': {'candidate': candidate},
            'required': ['candidate'], 'additionalProperties': False}
