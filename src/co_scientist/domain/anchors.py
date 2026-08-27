"""Canonical frozen benchmark hypotheses and their admission evidence."""

from __future__ import annotations

from typing import Any

from co_scientist.domain.hypothesis import HypothesisContent


def core_preview_anchor_sets(anchor_count: int) -> list[dict[str, Any]]:
    """Return the complete immutable Core Preview anchor contract."""

    contents = (
        (
            "transparent-regeneration-baseline-v1",
            HypothesisContent(
                content_id="transparent-regeneration-baseline-content-v1",
                title="Ordered transparent lens regeneration baseline",
                claim=(
                    "Lens epithelial repair can restore an ordered, transparent tissue "
                    "architecture when regenerative programs resolve without persistent "
                    "myofibroblast activation."
                ),
                mechanism_chain=(
                    "epithelial injury response",
                    "coordinated proliferative and differentiation program",
                    "ordered fiber architecture and optical transparency",
                ),
                assumptions=(
                    "the epithelial compartment remains viable",
                    "profibrotic signaling resolves after repair initiation",
                ),
                predictions=(
                    "epithelial markers remain organized during repair",
                    "alpha-SMA accumulation remains transient or absent",
                    "light-scattering opacity decreases as architecture recovers",
                ),
                falsifiers=(
                    "persistent myofibroblast conversion despite transparent repair",
                    "transparent recovery without restored tissue organization",
                ),
                generation_strategy="frozen Core Preview transparent benchmark",
            ),
        ),
        (
            "fibrotic-regeneration-baseline-v1",
            HypothesisContent(
                content_id="fibrotic-regeneration-baseline-content-v1",
                title="Disorganized fibrotic lens repair baseline",
                claim=(
                    "Sustained profibrotic signaling after lens epithelial injury drives "
                    "myofibroblast conversion, disorganized matrix deposition, and an "
                    "opaque repair outcome."
                ),
                mechanism_chain=(
                    "epithelial injury response",
                    "persistent TGF-beta-associated myofibroblast activation",
                    "disorganized extracellular matrix and optical opacity",
                ),
                assumptions=(
                    "injury permits a sustained profibrotic signaling state",
                    "matrix remodeling does not restore ordered fiber architecture",
                ),
                predictions=(
                    "alpha-SMA-positive cells persist after the acute repair phase",
                    "matrix organization remains irregular",
                    "light scattering remains elevated",
                ),
                falsifiers=(
                    "opaque repair with no persistent profibrotic activation",
                    "sustained myofibroblast activation followed by transparent organization",
                ),
                generation_strategy="frozen Core Preview fibrotic benchmark",
            ),
        ),
    )
    if anchor_count != len(contents):
        raise ValueError("Core Preview requires exactly two frozen anchor members")

    source_ids = {
        anchor_id: f"core-preview-curated-source:{anchor_id}"
        for anchor_id, _content in contents
    }
    hashes = {anchor_id: content.content_hash for anchor_id, content in contents}
    shared_proximity = {
        "edge_id": "anchor-reference-edge-v1",
        "left_id": contents[0][0],
        "left_content_hash": hashes[contents[0][0]],
        "right_id": contents[1][0],
        "right_content_hash": hashes[contents[1][0]],
        "research_plan_version": 1,
        "similarity": 2,
        "mechanism_overlap": ["epithelial injury response"],
        "duplicate_likelihood": 0.0,
        "cluster_suggestion": "reference-baselines",
        "rationale": (
            "The anchors share an injury context but encode distinct transparent and "
            "fibrotic repair outcomes."
        ),
        "access_issues": [],
        "epoch_id": "epoch-1",
    }

    members: list[dict[str, Any]] = []
    for anchor_id, content in contents:
        source_id = source_ids[anchor_id]
        other_id = next(item_id for item_id, _item in contents if item_id != anchor_id)
        content_document = content.model_dump(mode="json")
        reviews = [
            {
                "review_id": f"anchor-review:initial:{anchor_id}",
                "hypothesis_id": anchor_id,
                "content_hash": content.content_hash,
                "research_plan_version": 1,
                "stage": "initial_review",
                "recommendation": "pass",
                "safety_status": "passed",
                "dimension_scores": {"benchmark_integrity": 1.0},
                "critical_flaws": [],
                "evidence_ids": [source_id],
                "epoch_id": "epoch-1",
            },
            {
                "review_id": f"anchor-review:full:{anchor_id}",
                "hypothesis_id": anchor_id,
                "content_hash": content.content_hash,
                "research_plan_version": 1,
                "stage": "full_review",
                "recommendation": "pass",
                "safety_status": "passed",
                "dimension_scores": {"benchmark_integrity": 1.0},
                "critical_flaws": [],
                "evidence_ids": [source_id],
                "epoch_id": "epoch-1",
            },
        ]
        novelty = {
            "assessment_id": f"anchor-novelty:{anchor_id}",
            "hypothesis_id": anchor_id,
            "content_hash": content.content_hash,
            "research_plan_version": 1,
            "verdict": "partially_novel",
            "closest_prior_work_ids": [source_ids[other_id]],
            "evidence_ids": [source_id, source_ids[other_id]],
            "epoch_id": "epoch-1",
        }
        members.append(
            {
                "anchor_id": anchor_id,
                "kind": "baseline_reference",
                "content": content_document,
                "content_hash": content.content_hash,
                "evidence": {
                    "sources": [
                        {
                            "source_id": source_id,
                            "title": content.title,
                            "provenance": "frozen Core Preview benchmark definition v1",
                            "supports": ["content", "review", "novelty", "proximity"],
                        }
                    ],
                    "reviews": reviews,
                    "novelty_assessment": novelty,
                    "proximity_assessment": dict(shared_proximity),
                },
            }
        )
    return [{"anchor_set_id": "core-preview-anchors-v1", "members": members}]
