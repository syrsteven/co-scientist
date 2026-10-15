"""Version-neutral fields for decomposition continuation, never provenance authority."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from co_scientist.agents.payloads import (
    ClaimDecompositionResultV1,
    ClaimDecompositionResultV2,
    ClaimDecompositionResultV3,
)
from co_scientist.agents.result import AgentResult


class ClaimDecompositionApplicationView(BaseModel):
    """Common scientific fields; version-specific provenance stays in result/events."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    output_schema_id: str
    output_schema_version: int
    research_plan_version: int
    hypothesis_id: str
    hypothesis_content_hash: str
    critical_claims: tuple[dict[str, Any], ...]


def decomposition_application_view(result: AgentResult) -> ClaimDecompositionApplicationView:
    """Select by frozen schema identity, never by a payload's apparent shape."""

    identity = (result.output_schema_id, result.output_schema_version)
    if result.skill_id != "claim_decomposition":
        raise ValueError("unknown frozen claim decomposition result contract")
    decomposition: (
        ClaimDecompositionResultV1 | ClaimDecompositionResultV2 | ClaimDecompositionResultV3
    )
    if identity == ("ClaimDecompositionResultV1", 1):
        decomposition = ClaimDecompositionResultV1.model_validate(result.payload)
    elif identity == ("ClaimDecompositionResultV2", 2):
        decomposition = ClaimDecompositionResultV2.model_validate(result.payload)
    elif identity == ("ClaimDecompositionResultV3", 3):
        decomposition = ClaimDecompositionResultV3.model_validate(result.payload)
    else:
        raise ValueError("unknown frozen claim decomposition result contract")
    common_fields = ("claim_id", "text", "claim_type", "subject", "relation", "object")
    return ClaimDecompositionApplicationView(
        output_schema_id=identity[0], output_schema_version=identity[1],
        research_plan_version=decomposition.research_plan_version,
        hypothesis_id=decomposition.hypothesis_id,
        hypothesis_content_hash=decomposition.hypothesis_content_hash,
        critical_claims=tuple({
            **{field: getattr(claim, field) for field in common_fields},
            "importance": "critical",
            "hypothesis_content_hash": decomposition.hypothesis_content_hash,
        } for claim in decomposition.claims if claim.importance == "critical"),
    )
