"""Immutable execution snapshots stored in Supervisor-created tasks."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from co_scientist.agents.payloads import (
    ClaimDecompositionResultV1,
    ClaimDecompositionResultV2,
    ClaimSearchPlanResultV1,
    ClaimVerificationResultV1,
    ClaimVerificationResultV2,
    CoreOutputSchemaId,
    CoreScientificResultV1,
    EvolutionResultV1,
    GenerationResultV1,
    MetaReviewResultV1,
    PopulationEvolutionResultV1,
    ProximityResultV1,
    RankingResultV1,
    ReflectionResultV1,
)
from co_scientist.domain.budget import BudgetEstimate
from co_scientist.domain.claim_verification import (
    ClaimDecompositionOutputPolicy,
    ClaimVerificationPolicy,
    EvidenceSnapshot,
)
from co_scientist.domain.ideation_prerequisites import (
    RESULT_MODELS,
    BoundResultV1,
    RootLiteratureReviewResultV1,
    RootRetrievalResultV2,
    validate_binding,
    validate_prerequisite_inputs,
    validate_source_review,
)
from co_scientist.domain.source_units import source_units_for_content
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
        if ("ideation_task_binding" in self.inputs
                and self.output_schema_id not in RESULT_MODELS):
            raise ValueError("prerequisite binding cannot select a historical task schema")
        if self.output_schema_id in RESULT_MODELS:
            binding = validate_prerequisite_inputs(self.inputs)
            expected = {
                "skill_id": self.skill_id, "skill_version": self.skill_version,
                "schema_id": self.output_schema_id, "schema_version": self.output_schema_version,
                "directive_version": self.research_plan_version, "provider": self.provider_id,
                "model": self.model_or_tool, "prompt_hash": self.prompt_hash,
            }
            if any(getattr(binding, key) != value for key, value in expected.items()):
                raise ValueError("prerequisite task binding identity mismatch")
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
    result: CoreScientificResultV1 | ClaimDecompositionResultV2 | ClaimVerificationResultV2,
    literature_operation: Literal["search", "summary"] | None = None,
) -> None:
    """Bind one typed scientific result to the immutable task input snapshot."""

    mismatches: list[str] = []
    if ("ideation_task_binding" in task_inputs
            and not isinstance(result, BoundResultV1 | RootRetrievalResultV2)):
        raise ValueError("prerequisite binding cannot accept a historical result schema")
    if isinstance(result, BoundResultV1 | RootRetrievalResultV2):
        if "ideation_task_binding" not in task_inputs:
            raise ValueError("missing prerequisite task binding")
        expected_binding = validate_prerequisite_inputs(task_inputs)
        validate_binding(expected_binding, result.binding)
        if isinstance(result, RootLiteratureReviewResultV1):
            validate_source_review(result, task_inputs)
        if (provider_id != expected_binding.provider
                or task_research_plan_version != expected_binding.directive_version):
            raise ValueError("prerequisite result binding provider/version mismatch")
    protocol = task_inputs.get("scientific_protocol")
    if (isinstance(protocol, Mapping) and protocol.get("version") in {"research-v1", "research-v2"}
            and isinstance(result, GenerationResultV1 | EvolutionResultV1 | PopulationEvolutionResultV1)):
        drafts = (result.hypotheses if isinstance(result, GenerationResultV1) else
                  result.children if isinstance(result, EvolutionResultV1) else
                  (result.child,) if result.child is not None else ())
        if any(not getattr(draft, field) for draft in drafts
               for field in ("mechanism_chain", "assumptions", "predictions", "falsifiers")):
            mismatches.append("scientific_content_completeness")
    if result.research_plan_version != task_research_plan_version:
        mismatches.append("research_plan_version")
    if isinstance(result, ClaimDecompositionResultV1):
        if (task_inputs.get("claim_output_protocol") == "deepseek-claim-source-units-v3"
                and result.result_tool_resolution is None):
            mismatches.append("result_tool_resolution")
        if (task_inputs.get("claim_output_protocol") != "deepseek-claim-source-units-v3"
                and result.result_tool_resolution is not None):
            mismatches.append("unexpected_result_tool_resolution")
        mismatches.extend(_task_input_mismatches(
            task_inputs, result,
            {"hypothesis_id": "hypothesis_id", "content_hash": "hypothesis_content_hash"},
        ))
        policy_data = task_inputs.get("claim_verification_policy")
        if isinstance(policy_data, Mapping):
            policy = ClaimVerificationPolicy.model_validate(policy_data)
            if (sum(claim.importance == "critical" for claim in result.claims)
                    > policy.max_critical_claims_per_hypothesis):
                mismatches.append("critical_claim_limit")
        output_policy_data = task_inputs.get("claim_decomposition_output")
        if output_policy_data is not None:
            output_policy = ClaimDecompositionOutputPolicy.model_validate(output_policy_data)
            if len(result.claims) > output_policy.max_total_claims:
                mismatches.append("total_claim_limit")
        content = task_inputs.get("hypothesis_content")
        if not isinstance(content, Mapping):
            mismatches.append("hypothesis_content")
        else:
            passages = [str(content.get(key, "")) for key in ("title", "claim")]
            for key in ("mechanism_chain", "assumptions", "predictions", "falsifiers"):
                values = content.get(key)
                if isinstance(values, list | tuple):
                    passages.extend(str(value) for value in values)
            if task_inputs.get("claim_output_protocol") in {
                    "deepseek-claim-source-units-v2", "deepseek-claim-source-units-v3",
                    "deepseek-claim-source-units-v4",
                    "claim-source-units-provider-json-v5"}:
                try:
                    units = {u.source_unit_id: u for u in source_units_for_content(task_inputs)}
                    for claim in result.claims:
                        refs = claim.source_unit_refs
                        if (not refs or claim.source_relation is None
                                or len({ref.source_unit_id for ref in refs}) != len(refs)
                                or any(units.get(ref.source_unit_id) != ref for ref in refs)
                                or claim.source_span != "\n".join(ref.exact_text for ref in refs)
                                or (claim.source_relation in {"direct", "paraphrase"}
                                    and len(refs) != 1)
                                or (claim.source_relation == "synthesized_from"
                                    and len(refs) < 2)):
                            mismatches.append("claim.source_units")
                except (ValueError, TypeError):
                    mismatches.append("claim.source_units")
            elif any(not any(claim.source_span in passage for passage in passages)
                     for claim in result.claims):
                mismatches.append("claim.source_span")
    elif isinstance(result, ClaimSearchPlanResultV1):
        if (task_inputs.get("claim_output_protocol") == "deepseek-claim-source-units-v3"
                and result.result_tool_resolution is None):
            mismatches.append("result_tool_resolution")
        if (task_inputs.get("claim_output_protocol") != "deepseek-claim-source-units-v3"
                and result.result_tool_resolution is not None):
            mismatches.append("unexpected_result_tool_resolution")
        mismatches.extend(_task_input_mismatches(
            task_inputs, result,
            {"hypothesis_id": "hypothesis_id", "content_hash": "hypothesis_content_hash"},
        ))
        claims = task_inputs.get("critical_claims")
        policy_data = task_inputs.get("claim_verification_policy")
        if not isinstance(claims, list) or not isinstance(policy_data, Mapping):
            mismatches.append("critical_claims")
        else:
            policy = ClaimVerificationPolicy.model_validate(policy_data)
            allowed = {str(c["claim_id"]): str(c["hypothesis_content_hash"])
                       for c in claims if isinstance(c, Mapping) and c.get("importance") == "critical"}
            counts: dict[str, int] = {}
            generation_query = " ".join(str(task_inputs.get("generation_query", "")).lower().split())
            normalized: set[str] = set()
            for proposal in result.proposals:
                counts[proposal.claim_id] = counts.get(proposal.claim_id, 0) + 1
                key = " ".join(proposal.query.lower().split())
                if (proposal.claim_id not in allowed
                        or proposal.claim_content_hash != allowed.get(proposal.claim_id)
                        or proposal.round > policy.max_search_rounds_per_claim
                        or counts[proposal.claim_id] > policy.max_queries_per_claim
                        or key in normalized or len(proposal.query) > 600
                        or (proposal.intent != "support" and key == generation_query)):
                    mismatches.append("search_proposals")
                normalized.add(key)
            if set(counts) != set(allowed):
                mismatches.append("critical_claim_coverage")
            if policy.max_queries_per_claim >= 2 and any(
                not {"refute", "prior_work"}.issubset({p.intent for p in result.proposals
                                                      if p.claim_id == claim_id})
                for claim_id in allowed
            ):
                mismatches.append("independent_reflection_search")
    elif isinstance(result, ClaimDecompositionResultV2):
        mismatches.extend(_task_input_mismatches(
            task_inputs, result,
            {"hypothesis_id": "hypothesis_id", "content_hash": "hypothesis_content_hash"},
        ))
        try:
            from co_scientist.domain.source_units import (
                resolve_source_units_v2,
                source_units_v2_for_content,
            )

            v2_source_units = source_units_v2_for_content(task_inputs)
            allowed_ids = {unit.source_unit_id for unit in v2_source_units}
            verification_data = task_inputs.get("claim_verification_policy")
            output_data = task_inputs.get("claim_decomposition_output")
            if isinstance(verification_data, Mapping):
                policy = ClaimVerificationPolicy.model_validate(verification_data)
                if sum(claim.importance == "critical" for claim in result.claims) > (
                    policy.max_critical_claims_per_hypothesis
                ):
                    mismatches.append("critical_claim_limit")
            if isinstance(output_data, Mapping):
                output_policy = ClaimDecompositionOutputPolicy.model_validate(output_data)
                if len(result.claims) > output_policy.max_total_claims:
                    mismatches.append("total_claim_limit")
            for v2_claim in result.claims:
                resolved = resolve_source_units_v2(
                    v2_claim.source_unit_ids,
                    expected_hypothesis_id=result.hypothesis_id,
                    expected_content_hash=result.hypothesis_content_hash,
                    allowed_units=v2_source_units,
                )
                if v2_claim.source_unit_refs != resolved or not set(v2_claim.source_unit_ids).issubset(
                    allowed_ids
                ):
                    mismatches.append("claim.source_unit_ids")
        except (ValueError, TypeError):
            mismatches.append("claim.source_unit_ids")
    elif isinstance(result, ClaimVerificationResultV2):
        mismatches.extend(_task_input_mismatches(
            task_inputs, result,
            {"hypothesis_id": "hypothesis_id", "content_hash": "hypothesis_content_hash"},
        ))
        claims = task_inputs.get("critical_claims")
        snapshots = task_inputs.get("evidence_snapshots")
        evidence_units = task_inputs.get("evidence_units")
        if not isinstance(claims, list) or not isinstance(snapshots, list) or not isinstance(
            evidence_units, list
        ):
            mismatches.append("claim_evidence_units")
        else:
            from co_scientist.domain.evidence_units import (
                EvidenceUnitV1,
                evidence_units_for_snapshot,
            )

            snapshot_models = [EvidenceSnapshot.model_validate(item) for item in snapshots]
            expected_units = tuple(
                unit for snapshot in snapshot_models for unit in evidence_units_for_snapshot(snapshot)
            )
            try:
                supplied_units = tuple(EvidenceUnitV1.model_validate(item) for item in evidence_units)
            except (TypeError, ValueError):
                supplied_units = ()
                mismatches.append("evidence_unit_identity")
            if supplied_units != expected_units:
                mismatches.append("evidence_unit_snapshot_binding")
            critical = {
                str(claim["claim_id"]): str(claim["hypothesis_content_hash"])
                for claim in claims
                if isinstance(claim, Mapping) and claim.get("importance") == "critical"
            }
            if len(critical) != len(claims) or not critical:
                mismatches.append("critical_claims")
            v2_assessment_ids = {item.claim_id for item in result.claim_assessments}
            if v2_assessment_ids != set(critical):
                mismatches.append("critical_claim_coverage")
            # Per-binding provenance is handled by the claim-level binder so one bad
            # binding cannot discard independently valid same-call evidence work.
    elif isinstance(result, ClaimVerificationResultV1):
        mismatches.extend(_task_input_mismatches(
            task_inputs, result,
            {"hypothesis_id": "hypothesis_id", "content_hash": "hypothesis_content_hash"},
        ))
        claims = task_inputs.get("critical_claims")
        snapshots = task_inputs.get("evidence_snapshots")
        search_records = task_inputs.get("search_records")
        if not isinstance(claims, list) or not isinstance(snapshots, list) or not isinstance(search_records, list):
            mismatches.append("claim_evidence_inputs")
        else:
            claim_hashes = {str(c["claim_id"]): str(c["hypothesis_content_hash"])
                            for c in claims if isinstance(c, Mapping)}
            snapshot_by_id = {str(s["snapshot_id"]): s for s in snapshots if isinstance(s, Mapping)}
            if ({r.claim_id for r in result.claim_reviews} != set(claim_hashes)
                    or set(result.prior_art.critical_claim_ids) != set(claim_hashes)):
                mismatches.append("critical_claim_coverage")
            for binding in result.bindings:
                snapshot = snapshot_by_id.get(binding.evidence_snapshot_id)
                if (binding.claim_content_hash != claim_hashes.get(binding.claim_id)
                        or snapshot is None):
                    mismatches.append("binding_identity")
                    continue
                passage = f"{snapshot.get('title', '')}\n{snapshot.get('abstract') or ''}"
                if binding.source_span_or_excerpt_location not in passage:
                    mismatches.append("binding_source_span")
                if (snapshot.get("content_level") == "title"
                        and binding.evidence_strength != "title_only"):
                    mismatches.append("binding_evidence_level")
            source_ids = {str(s.get("source_id")) for s in snapshots if isinstance(s, Mapping)}
            queries = {str(s.get("query")) for s in search_records if isinstance(s, Mapping)}
            if (not set(result.prior_art.source_ids).issubset(source_ids)
                    or set(result.prior_art.searched_queries) != queries):
                mismatches.append("prior_art_scope")
            if not search_records and result.prior_art.status != "indeterminate":
                mismatches.append("unsearched_prior_art_status")
            if (result.prior_art.status == "components_known_bridge_not_found"
                    and (result.prior_art.direct_prior_art or not any(
                        b.relation == "supports" for b in result.bindings
                    ))):
                mismatches.append("missing_bridge_basis")
            if result.prior_art.status == "direct_prior_art_found" and not result.prior_art.direct_prior_art:
                mismatches.append("direct_prior_art_basis")
            binding_by_id = {b.evidence_snapshot_id: b for b in result.bindings}
            if any(set(review.supporting_evidence_ids + review.contradictory_evidence_ids
                       + review.prior_art_evidence_ids + review.competing_mechanism_evidence_ids)
                   - set(binding_by_id) for review in result.claim_reviews):
                mismatches.append("claim_review_evidence")
    elif isinstance(result, ReflectionResultV1):
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
        claim_verification = task_inputs.get("claim_verification")
        if isinstance(claim_verification, Mapping) and result.stage.value == "full_review":
            if result.novelty_assessment is not None:
                mismatches.append("legacy_novelty_assessment_for_research_v2")
            claim_review_source_ids = claim_verification.get("source_ids")
            if (not isinstance(claim_review_source_ids, list)
                    or not set(result.evidence_ids).issubset(set(claim_review_source_ids))):
                mismatches.append("claim_review_source_ids")
        if isinstance(evidence, Mapping):
            literature_source_ids = evidence.get("source_ids")
            if not isinstance(literature_source_ids, list) or not literature_source_ids:
                mismatches.append("literature_sources")
            else:
                scheduled = {str(source_id) for source_id in literature_source_ids}
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
        if (task_inputs.get("rating_policy_version") == "trueskill_v1"
                and result.evidence_context_hash != task_inputs.get("evidence_context_hash")):
            mismatches.append("evidence_context_hash")
        if (isinstance(protocol, Mapping) and protocol.get("version") in {"research-v1", "research-v2"}
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
    elif isinstance(result, PopulationEvolutionResultV1):
        mismatches.extend(_task_input_mismatches(task_inputs, result, {
            "generation_id": "generation_id", "selection_decision_id": "selection_decision_id",
            "operator": "operator", "mutation_subtype": "mutation_subtype",
            "parent_content_hashes": "parent_content_hashes",
        }))
        if tuple(task_inputs.get("parent_ids", ())) != result.parent_ids:
            mismatches.append("parent_ids")
        if result.proposal_id != f"{result.generation_id}:proposal:{task_inputs.get('slot')}":
            mismatches.append("proposal_id")
        decision = task_inputs.get("parent_selection_decision")
        if isinstance(decision, Mapping) and result.random_seed != decision.get("random_seed"):
            mismatches.append("random_seed")
        review_context = task_inputs.get("review_context")
        if isinstance(review_context, Mapping):
            available_reviews = {str(review.get("review_id"))
                                 for context in review_context.values()
                                 if isinstance(context, Mapping)
                                 for review in context.get("reviews", [])
                                 if isinstance(review, Mapping)}
            if not set(result.source_review_ids).issubset(available_reviews):
                mismatches.append("source_review_ids")
            if result.valid and not result.source_review_ids:
                mismatches.append("source_review_ids")
        available_feedback = task_inputs.get("research_feedback")
        feedback_id = (available_feedback.get("feedback_id")
                       if isinstance(available_feedback, Mapping) else None)
        if any(item != feedback_id for item in result.source_feedback_ids):
            mismatches.append("source_feedback_ids")
        if result.mutation_subtype == "targeted_revision" and result.valid and (
            not set(result.target_feedback_ids).issubset(result.source_feedback_ids)
        ):
            mismatches.append("target_feedback_ids")
        child = result.child
        if child is not None:
            expected_contents = set(task_inputs.get("source_content_ids", []))
            if (set(child.parent_content_ids) != expected_contents
                    or child.supersedes_content_id is not None):
                mismatches.append("source_content_ids")
            if child.hypothesis_id in task_inputs.get("existing_hypothesis_ids", []):
                mismatches.append("existing_hypothesis_ids")
            if child.content_id in task_inputs.get("existing_content_ids", []):
                mismatches.append("existing_content_ids")
            if result.operator == "crossover":
                child_science = "\n".join((child.title, child.claim,
                                            *child.mechanism_chain, *child.predictions))
                parent_contents = task_inputs.get("hypothesis_contents", {})
                parent_science = ["\n".join((str(content.get("title", "")),
                                             str(content.get("claim", "")),
                                             *content.get("mechanism_chain", [])))
                                  for content in parent_contents.values()
                                  if isinstance(content, Mapping)]
                if (not result.new_causal_bridge
                        or not result.critical_new_claim
                        or result.new_causal_bridge not in child_science
                        or result.critical_new_claim not in child_science
                        or any(result.new_causal_bridge in text for text in parent_science)):
                    mismatches.append("nontrivial_crossover_bridge")
    elif isinstance(result, GenerationResultV1):
        expected_hypotheses = task_inputs.get("expected_hypothesis_ids")
        if isinstance(expected_hypotheses, list) and {
            draft.hypothesis_id for draft in result.hypotheses
        } != {str(hypothesis_id) for hypothesis_id in expected_hypotheses}:
            mismatches.append("expected_hypothesis_ids")
    if mismatches:
        fields = ", ".join(sorted(set(mismatches)))
        raise ValueError(f"typed result does not match task inputs: {fields}")
