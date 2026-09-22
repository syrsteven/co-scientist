"""Immutable execution snapshots stored in Supervisor-created tasks."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from co_scientist.agents.payloads import (
    CoreOutputSchemaId,
    CoreScientificResultV1,
    EvolutionResultV1,
    GenerationResultV1,
    MetaReviewResultV1,
    ProximityResultV1,
    RankingResultV1,
    ReflectionResultV1,
)
from co_scientist.domain.budget import BudgetEstimate
from co_scientist.runtime.external_calls import request_fingerprint


class WorkerTaskPayload(BaseModel):
    """Immutable identity and inputs required to execute one task."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    skill_id: str
    skill_version: str
    output_schema_id: CoreOutputSchemaId
    output_schema_version: int = Field(ge=1)
    research_plan_version: int = Field(ge=1)
    provider_id: str
    model_or_tool: str
    inputs: dict[str, Any]
    input_snapshot_hash: str
    prompt_hash: str
    budget_estimate: BudgetEstimate

    @model_validator(mode="after")
    def validate_input_snapshot(self) -> WorkerTaskPayload:
        if request_fingerprint(self.inputs) != self.input_snapshot_hash:
            raise ValueError("task input snapshot hash does not match inputs")
        return self


def _task_input_mismatches(
    inputs: Mapping[str, Any], result: BaseModel, bindings: Mapping[str, str]
) -> list[str]:
    mismatches: list[str] = []
    for input_name, result_name in bindings.items():
        if input_name not in inputs:
            mismatches.append(f"missing:{input_name}")
        elif inputs[input_name] != getattr(result, result_name):
            mismatches.append(input_name)
    return mismatches


def _literature_binding_mismatches(
    *,
    inputs: Mapping[str, Any],
    result: MetaReviewResultV1,
    provider_id: str,
    operation: Literal["search", "summary"] | None,
) -> list[str]:
    resolved_operation = operation or provider_id.rsplit(":", 1)[-1]
    if resolved_operation not in {"search", "summary"}:
        return []
    try:
        overview = json.loads(result.overview)
    except json.JSONDecodeError:
        return ["literature_overview"]
    if not isinstance(overview, Mapping):
        return ["literature_overview"]
    mismatches: list[str] = []
    if overview.get("operation") != resolved_operation:
        mismatches.append("literature_operation")
    if overview.get("query") != inputs.get("query"):
        mismatches.append("literature_query")
    if resolved_operation == "summary":
        scheduled_pmids = inputs.get("pmids")
        documents = overview.get("source_documents")
        if not isinstance(scheduled_pmids, list) or not isinstance(documents, list):
            mismatches.append("literature_sources")
        else:
            source_ids = [
                document.get("source_id")
                for document in documents
                if isinstance(document, Mapping)
            ]
            if (
                len(source_ids) != len(documents)
                or len(set(source_ids)) != len(source_ids)
                or set(source_ids)
                != {f"pubmed:{str(pmid).removeprefix('pubmed:')}" for pmid in scheduled_pmids}
            ):
                mismatches.append("literature_sources")
    return mismatches


def validate_result_task_binding(
    *,
    task_inputs: Mapping[str, Any],
    task_research_plan_version: int,
    provider_id: str,
    result: CoreScientificResultV1,
    literature_operation: Literal["search", "summary"] | None = None,
) -> None:
    """Bind one typed scientific result to the immutable task input snapshot."""

    mismatches: list[str] = []
    protocol = task_inputs.get("scientific_protocol")
    if (isinstance(protocol, Mapping) and protocol.get("version") == "research-v1"
            and isinstance(result, GenerationResultV1 | EvolutionResultV1)):
        drafts = result.hypotheses if isinstance(result, GenerationResultV1) else result.children
        if any(not getattr(draft, field) for draft in drafts
               for field in ("mechanism_chain", "assumptions", "predictions", "falsifiers")):
            mismatches.append("scientific_content_completeness")
    if result.research_plan_version != task_research_plan_version:
        mismatches.append("research_plan_version")
    if isinstance(result, ReflectionResultV1):
        mismatches.extend(
            _task_input_mismatches(
                task_inputs,
                result,
                {
                    "hypothesis_id": "hypothesis_id",
                    "content_hash": "content_hash",
                    "review_stage": "stage",
                },
            )
        )
        evidence = task_inputs.get("literature_evidence")
        if isinstance(evidence, Mapping):
            source_ids = evidence.get("source_ids")
            if not isinstance(source_ids, list) or not source_ids:
                mismatches.append("literature_sources")
            else:
                scheduled = {str(source_id) for source_id in source_ids}
                novelty = result.novelty_assessment
                claimed = set(result.evidence_ids)
                if novelty is not None:
                    claimed.update(novelty.evidence_ids)
                    claimed.update(novelty.closest_prior_work_ids)
                explicit_gap = result.recommendation != "pass" and (
                    novelty is None or novelty.verdict == "insufficient_evidence"
                )
                if (not claimed and not explicit_gap) or not claimed.issubset(scheduled):
                    mismatches.append("literature_sources")
    elif isinstance(result, RankingResultV1):
        if (isinstance(protocol, Mapping) and protocol.get("version") == "research-v1"
                and result.decision_status == "decisive"):
            rubric = task_inputs.get("evaluation_rubric")
            dimensions = rubric.get("dimensions") if isinstance(rubric, Mapping) else None
            if not isinstance(dimensions, Mapping) or not dimensions or any(
                not result.dimension_reasons.get(key, "").strip() for key in dimensions
            ):
                mismatches.append("evaluation_rubric.dimension_reasons")
        mismatches.extend(
            _task_input_mismatches(
                task_inputs,
                result,
                {
                    "match_id": "match_id",
                    "epoch_id": "epoch_id",
                    "left_id": "left_id",
                    "left_content_hash": "left_content_hash",
                    "right_id": "right_id",
                    "right_content_hash": "right_content_hash",
                    "research_plan_version": "research_plan_version",
                    "evaluation_rules_hash": "evaluation_rules_hash",
                    "ranking_prompt_hash": "ranking_prompt_hash",
                    "judge_profile_hash": "judge_profile_hash",
                    "rating_policy_version": "rating_policy_version",
                    "admission_policy_version": "admission_policy_version",
                },
            )
        )
    elif isinstance(result, ProximityResultV1):
        mismatches.extend(
            _task_input_mismatches(
                task_inputs,
                result,
                {
                    "edge_id": "edge_id",
                    "left_id": "left_id",
                    "left_content_hash": "left_content_hash",
                    "right_id": "right_id",
                    "right_content_hash": "right_content_hash",
                },
            )
        )
    elif isinstance(result, MetaReviewResultV1):
        mismatches.extend(
            _literature_binding_mismatches(
                inputs=task_inputs,
                result=result,
                provider_id=provider_id,
                operation=literature_operation,
            )
        )
        source_hashes = task_inputs.get("source_content_hashes")
        if source_hashes is not None and result.source_content_hashes != source_hashes:
            mismatches.append("source_content_hashes")
    elif isinstance(result, EvolutionResultV1):
        source_content_ids = task_inputs.get("source_content_ids")
        if isinstance(source_content_ids, list) and source_content_ids:
            expected = {str(content_id) for content_id in source_content_ids}
            if any(not child.parent_content_ids or not set(child.parent_content_ids).issubset(expected)
                   for child in result.children):
                mismatches.append("source_content_ids")
        max_children = task_inputs.get("max_children")
        if isinstance(max_children, int) and len(result.children) > max_children:
            mismatches.append("max_children")
        if isinstance(max_children, int) and any(child.supersedes_content_id is not None
                                                for child in result.children):
            mismatches.append("supersedes_content_id")
        for field, attr in (("existing_hypothesis_ids", "hypothesis_id"),
                            ("existing_content_ids", "content_id")):
            existing = task_inputs.get(field)
            if isinstance(existing, list) and any(
                getattr(child, attr) in existing for child in result.children
            ):
                mismatches.append(field)
        if len({child.content_id for child in result.children}) != len(result.children):
            mismatches.append("unique_child_content_ids")
        expected_children = task_inputs.get("expected_child_hypothesis_ids")
        if isinstance(expected_children, list) and {
            child.hypothesis_id for child in result.children
        } != {str(hypothesis_id) for hypothesis_id in expected_children}:
            mismatches.append("expected_child_hypothesis_ids")
    elif isinstance(result, GenerationResultV1):
        expected_hypotheses = task_inputs.get("expected_hypothesis_ids")
        if isinstance(expected_hypotheses, list) and {
            draft.hypothesis_id for draft in result.hypotheses
        } != {str(hypothesis_id) for hypothesis_id in expected_hypotheses}:
            mismatches.append("expected_hypothesis_ids")
    if mismatches:
        fields = ", ".join(sorted(set(mismatches)))
        raise ValueError(f"typed result does not match task inputs: {fields}")
