"""Content-bound research input construction, called only by the Supervisor."""

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import ValidationError

from co_scientist.domain.claim_verification import ClaimVerificationAppliedEventV2
from co_scientist.domain.hypothesis import HypothesisContent
from co_scientist.domain.ideation_core_boundary import baseline_enabled, boundary_contract
from co_scientist.domain.ranking_output import strict_ranking_contract
from co_scientist.domain.research_feedback import feedback_enabled, latest_research_feedback
from co_scientist.domain.research_protocol import protocol_hash
from co_scientist.events.models import DomainEvent, NewEvent
from co_scientist.ports.external_provider import thaw_json
from co_scientist.runtime.lineage_workflow_contract import validate_lineage_workflow_contract


def baseline_critique_context(events: Sequence[DomainEvent | NewEvent], *,
                              hypothesis_id: str, content_hash: str) -> list[dict[str, Any]]:
    """Keep all same-stage critiques in durable order, never last-write-wins.

    This is an input projection, not an admission verdict. Lineage, claims and
    optional audit envelopes cannot contribute feedback through this reader.
    """
    values = []
    identities = set()
    for index, event in enumerate(events):
        payload = event.payload
        if payload.get("optional_audit") is True:
            continue
        if event.event_type == "BaselineReflectionRecordedV1":
            binding = payload["binding"]
            if (binding["hypothesis_id"], binding["content_hash"]) != (hypothesis_id, content_hash):
                continue
            source = str(payload["source_result_id"])
            review_id = source
            critiques = payload["result"]["critiques"]
            stage = "baseline_reflection"
        elif event.event_type == "ReviewCompleted":
            if (payload.get("hypothesis_id"), payload.get("content_hash")) != (hypothesis_id, content_hash):
                continue
            source = str(payload.get("source_result_id") or event.causation_id or "")
            review_id = str(payload.get("review_id") or "")
            critiques = payload.get("critical_flaws", ())
            stage = str(payload["stage"])
        else:
            continue
        if not source or not review_id:
            raise ValueError("critique missing durable result/review identity")
        if review_id in identities:
            raise ValueError("duplicate content-bound review identity")
        identities.add(review_id)
        for ordinal, critique in enumerate(critiques):
            if not isinstance(critique, str) or not critique.strip():
                raise ValueError("empty scientific critique")
            values.append({"review_id": review_id, "source_result_id": source,
                "stage": stage, "critique": critique, "ordinal": ordinal,
                "event_order": getattr(event, "sequence", index + 1),
                "hypothesis_id": hypothesis_id, "content_hash": content_hash})
    return values


def _baseline_input_view(inputs: dict[str, Any]) -> dict[str, Any]:
    """Explicit core-input projection; audit envelopes never become model facts.

    Batch 2/3 must add their frozen input contracts explicitly. No arbitrary
    caller-owned review_context/scientific_protocol/audit data is forwarded.
    """
    keys = {
        "goal_title", "research_goal", "required_causal_chain", "required_outputs",
        "research_plan_version", "hypothesis_id", "content_hash", "stage",
        "left_id", "right_id", "left_content_hash", "right_content_hash",
        "source_content_hashes", "source_content_ids", "epoch_id",
        "evaluation_rules_hash", "ranking_prompt_hash", "judge_profile_hash",
        "rating_policy_version", "admission_policy_version", "match_id",
    }
    return {key: value for key, value in inputs.items() if key in keys}


def research_inputs(
    manifest: Mapping[str, Any], events: Sequence[DomainEvent | NewEvent],
    inputs: dict[str, Any], *, skill_id: str,
) -> dict[str, Any]:
    """Read the frozen bundle, not today's prompt definition, on resume."""

    profile = manifest["profile"]
    baseline = baseline_enabled(manifest)
    if baseline:
        inputs = _baseline_input_view(inputs)
    if profile.get("lineage_workflow_contract") is not None:
        validate_lineage_workflow_contract(manifest)
    protocol = thaw_json(manifest.get("research_protocol"))
    if (profile.get("scientific_context") is not True or not isinstance(protocol, dict)
            or protocol.get("version") != profile.get("research_protocol_version")
            or protocol_hash(protocol) != manifest.get("research_protocol_hash")):
        raise ValueError("invalid frozen research protocol or scientific_context")
    goal = thaw_json(manifest.get("goal"))
    if (not isinstance(goal, dict) or not all(isinstance(goal.get(key), str) and goal[key].strip()
            for key in ("title", "goal"))
            or not all(isinstance(goal.get(key), list) and goal[key]
                       and all(isinstance(item, str) and item.strip() for item in goal[key])
                       for key in ("required_causal_chain", "required_outputs"))):
        raise ValueError("research protocol requires a complete research goal")
    contract = manifest["tournament_contract"]
    rules = {
        "evaluation_rules_id": profile["tournament"]["evaluation_rules_id"],
        "match_mode": profile["tournament"]["match_mode"],
        "research_protocol_hash": manifest["research_protocol_hash"],
    }
    if feedback_enabled(manifest):
        rules["feedback_contract_hash"] = manifest.get("feedback_contract_hash")
    output_contract = thaw_json(manifest.get("ranking_output_contract"))
    if profile.get("ranking_output_protocol") is not None or output_contract is not None:
        if (output_contract != strict_ranking_contract(profile.get("ranking_output_protocol", ""))
                or profile.get("ranking_output_protocol") != output_contract["version"]
                or manifest.get("ranking_output_contract_hash") != protocol_hash(output_contract)
                or manifest["provider_configuration"].get("ranking_output_protocol") != output_contract["version"]
                or manifest["providers"]["llm"] != "deepseek"):
            raise ValueError("invalid frozen Ranking output contract")
        rules["ranking_output_contract_hash"] = manifest["ranking_output_contract_hash"]
    if contract["evaluation_rules_hash"] != protocol_hash(rules):
        raise ValueError("research protocol does not match frozen evaluation rules")
    version = contract["research_plan_version"]
    if inputs.get("research_plan_version", version) != version:
        raise ValueError("scientific input research plan version mismatch")
    contents = {str(e.payload["hypothesis_id"]): thaw_json(e.payload)
                for e in events if e.event_type == "HypothesisContentCreated"}
    expected = {}
    for key, hash_key in (("hypothesis_id", "content_hash"), ("left_id", "left_content_hash"),
                          ("right_id", "right_content_hash")):
        if key in inputs:
            expected[inputs[key]] = inputs.get(hash_key)
    expected.update(inputs.get("source_content_hashes", {}))
    for source_id in inputs.get("source_content_ids", []):
        matches = [(key, c) for key, c in contents.items() if c.get("content_id") == source_id]
        if len(matches) != 1:
            raise ValueError("scientific task references missing or ambiguous parent content")
        key, content = matches[0]
        expected[key] = content["content_hash"]
    if skill_id != "generation" and not expected:
        raise ValueError("scientific task requires hypothesis content references")
    selected = {}
    for key, expected_hash in sorted(expected.items()):
        content = contents.get(key)
        if content is None:
            raise ValueError("scientific task references missing hypothesis content")
        parsed = HypothesisContent.model_validate(content)
        if (parsed.content_hash != expected_hash or content.get("content_hash") != expected_hash
                or content.get("research_plan_version") != version):
            raise ValueError("scientific hypothesis content hash or plan version mismatch")
        if not all(value.strip() for value in (parsed.title, parsed.claim, parsed.generation_strategy)) or not all(
            values and all(value.strip() for value in values)
            for values in (parsed.mechanism_chain, parsed.assumptions, parsed.predictions, parsed.falsifiers)
        ):
            raise ValueError("scientific hypothesis body is incomplete")
        selected[key] = content
    result = {
        **inputs, "research_goal": goal, "research_plan_version": version,
        "hypothesis_contents": selected,
        "scientific_protocol": {
            "version": protocol["version"], "bundle_hash": manifest["research_protocol_hash"],
            "common_instructions": protocol["common_instructions"],
            "role_instructions": protocol["roles"][skill_id],
        },
    }
    if baseline:
        result["core_boundary"] = boundary_contract()
        if skill_id == "reflection":
            result["scientific_protocol"]["role_instructions"] = (
                "Review the requested scientific stage; assess plausibility, prior research, "
                "testability, originality and unjustified complexity. Preserve criticism as "
                "scientific feedback. Do not claim unperformed observations or simulations. "
                "Cite only supplied, authoritative source identities."
            )
        result["scientific_protocol"]["role_instructions"] += (
            " Baseline boundary: scientific Reflection criticism, rejection recommendations "
            "and critical flaws are feedback, not independent eligibility rejection. "
            "Candidate Ethics requires a separate authoritative decision. Optional claim "
            "verification, claim lineage and semantic Proximity are not core prerequisites."
        )
    feedback = latest_research_feedback(manifest, events)
    if skill_id == "ranking" and output_contract is not None:
        result["ranking_output_contract"] = output_contract
    if skill_id in {"claim_decomposition", "claim_search_plan"} and profile.get(
        "claim_output_protocol") is not None:
        if manifest["providers"]["llm"] != "deepseek":
            raise ValueError("frozen claim output protocol requires DeepSeek")
        result["claim_output_protocol"] = profile["claim_output_protocol"]
    if feedback is not None and not baseline:
        result["research_feedback"] = feedback
        result["feedback_use_instruction"] = manifest["feedback_contract"]["context_instruction"]
    if skill_id not in {"ranking", "evolution", "population_evolution", "meta_review"}:
        return result
    sources = {}
    for event in events:
        if baseline:
            # No Batch 2 grounding representation exists yet. Audit artifacts
            # cannot masquerade as the missing authoritative grounding bundle.
            continue
        for source in event.payload.get("source_documents", []):
            sources[source["source_id"]] = thaw_json(source)
    anchors = {member["anchor_id"]: member for group in manifest.get("anchor_sets", [])
               for member in group["members"]}
    for member in anchors.values():
        for source in member["evidence"]["sources"]:
            sources[source["source_id"]] = {**thaw_json(source), "evidence_kind": "curated_benchmark_definition"}
    review_context = {}
    for key, content in selected.items():
        reviews, novelty = {}, None
        for event in events:
            payload = event.payload
            if (payload.get("hypothesis_id") != key
                    or payload.get("content_hash") != content["content_hash"]
                    or payload.get("research_plan_version") != version):
                continue
            if event.event_type == "ReviewCompleted":
                # Prior numeric scores are not independent votes for the pairwise judge.
                reviews[payload["stage"]] = {k: thaw_json(v) for k, v in payload.items()
                                             if k != "dimension_scores"}
            elif event.event_type == "NoveltyAssessmentRecorded" and not baseline:
                novelty = thaw_json(payload)
        if skill_id == "ranking":
            required = {"initial_review", *profile["review_policy"]["required_before_admission"]}
            if not required.issubset(reviews):
                raise ValueError("ranking requires content-bound review coverage")
            if profile["literature_novelty_required"] and novelty is None:
                raise ValueError("ranking requires content-bound novelty assessment")
        cited = {sid for review in reviews.values() for sid in review.get("evidence_ids", [])}
        if novelty:
            cited.update(novelty.get("evidence_ids", []))
            cited.update(novelty.get("closest_prior_work_ids", []))
        review_context[key] = {
            "content_hash": content["content_hash"], "research_plan_version": version,
            "reviews": list(reviews.values()), "novelty_assessment": novelty,
            "source_documents": [sources[sid] for sid in sorted(cited) if sid in sources],
            "unavailable_source_ids": sorted(cited - sources.keys()),
            "evidence_origin": "curated_benchmark_not_empirical_validation" if key in anchors else "run_review",
        }
        if baseline:
            review_context[key]["ordered_critiques"] = baseline_critique_context(
                events, hypothesis_id=key, content_hash=content["content_hash"])
        if not baseline and profile.get("claim_verification") is not None:
            scoped = [event for event in events
                      if event.payload.get("hypothesis_id") == key
                      and event.payload.get("hypothesis_content_hash") == content["content_hash"]]
            v2_applications = [event for event in events
                               if event.event_type == "ClaimVerificationAppliedV2"
                               and event.payload.get("hypothesis_id") == key]
            if len(v2_applications) > 1:
                raise ValueError("ranking has ambiguous V2 claim verification applications")
            v2_application = None
            if v2_applications:
                try:
                    v2_event = ClaimVerificationAppliedEventV2.model_validate(
                        v2_applications[0].payload
                    )
                except ValidationError as error:
                    raise ValueError("ranking has invalid V2 claim verification state") from error
                if (v2_event.hypothesis_content_hash != content["content_hash"]
                        or v2_event.research_plan_version != version):
                    raise ValueError("ranking V2 claim verification state is stale")
                if any(state.status != "complete"
                       for state in v2_event.application.claim_states):
                    raise ValueError("ranking blocked by incomplete V2 claim verification")
                v2_application = thaw_json(v2_event.application.model_dump(mode="json"))
            review_context[key].update({
                "structured_claims": [thaw_json(event.payload) for event in scoped
                                      if event.event_type == "HypothesisClaimCreated"],
                "claim_evidence_bindings": [thaw_json(event.payload) for event in scoped
                                            if event.event_type == "ClaimEvidenceBindingRecorded"],
                "prior_art_assessments": [thaw_json(event.payload) for event in scoped
                                          if event.event_type == "PriorArtAssessmentRecorded"],
                "claim_verifications": [thaw_json(event.payload) for event in scoped
                                        if event.event_type == "ClaimVerificationCompleted"],
                **({"claim_verification_v2_application": v2_application}
                   if v2_application is not None else {}),
                "evidence_snapshots": [
                    {"snapshot_id": event.payload["snapshot_id"],
                     "snapshot_hash": event.payload["snapshot_hash"],
                     "source_id": event.payload["source_id"],
                     "content_level": event.payload["content_level"]}
                    for event in scoped if event.event_type == "EvidenceSnapshotRecorded"
                ],
            })
        if skill_id == "ranking" and profile.get("tournament", {}).get("rating_policy_version") == "trueskill_v1":
            review_context[key]["context_hash"] = protocol_hash(review_context[key])
    result["review_context"] = review_context
    if skill_id == "ranking" and profile.get("tournament", {}).get("rating_policy_version") == "trueskill_v1":
        result["evidence_context_hash"] = protocol_hash({
            key: review_context[key]["context_hash"] for key in sorted(review_context)
        })
    if (skill_id == "meta_review"
            and manifest.get("feedback_contract", {}).get("version") == "meta-review-loop-v2"):
        result["supervisor_review_context"] = {
            "safety_gate_stage": "initial_review",
            "candidates": {
                key: {
                    "content_hash": content["content_hash"],
                    "research_plan_version": version,
                    "safety_review_records": [
                        {"review_id": e.payload.get("review_id"),
                         "stage": e.payload.get("stage"),
                         "safety_status": e.payload.get("safety_status")}
                        for e in events if e.event_type == "ReviewCompleted"
                        and e.payload.get("hypothesis_id") == key
                        and e.payload.get("content_hash") == content["content_hash"]
                        and e.payload.get("research_plan_version") == version],
                    "admitted_in_current_epoch": any(
                        e.event_type == "TournamentEntryCreated"
                        and e.payload.get("hypothesis_id") == key
                        and e.payload.get("content_hash") == content["content_hash"]
                        and e.payload.get("epoch_id") == contract["epoch_id"] for e in events),
                } for key, content in selected.items()
            },
        }
    if skill_id == "ranking":
        for key in ("epoch_id", "evaluation_rules_hash", "ranking_prompt_hash", "judge_profile_hash",
                    "rating_policy_version", "admission_policy_version"):
            if inputs.get(key) != contract[key]:
                raise ValueError("ranking input does not match frozen epoch contract")
        result["evaluation_rubric"] = {
            "dimensions": protocol["ranking_dimensions"],
            "aggregation_policy": protocol["aggregation_policy"],
            "match_mode": profile["tournament"]["match_mode"],
            "decision_policy": "research: abstain when unresolvable; binary benchmark is not enabled by this protocol",
        }
    return result
