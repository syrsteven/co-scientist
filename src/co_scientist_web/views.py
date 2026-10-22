"""Observational committed-event views; ratings come from native replay only."""

from co_scientist.domain.bayesian_ranking import TrueSkillConfig, replay_bayesian_rating
from co_scientist.ports.external_provider import thaw_json
from co_scientist.runtime.trace_snapshot import readonly_uow


def candidates(root, run_id):
    path = root / "runtime/co-scientist.db"
    if not path.exists():
        return {"source_sequence": 0, "ranked": [], "pending": []}
    with readonly_uow(path) as uow:
        events = uow.load(run_id)
        manifest = uow.run_manifest(run_id)
    rows = [e.model_dump(mode="json") for e in events]
    ratings = replay_bayesian_rating(
        events, epoch_id=manifest["tournament_contract"]["epoch_id"], policy=TrueSkillConfig()
    )
    roots = {
        e.payload["source_result_id"]
        for e in events
        if e.event_type == "GroundedGenerationRecordedV1"
        and e.payload["binding"].get("root_slot_id") is not None
    }
    result = []
    for event in events:
        if event.event_type != "HypothesisContentCreated":
            continue
        p = thaw_json(event.payload)
        key = p["hypothesis_id"]
        plan = next(
            (
                e
                for e in events
                if e.event_type == "BaselineReproductionPlannedV1"
                and e.payload["slot_id"] == p.get("slot_id")
            ),
            None,
        )
        review = lambda kind, key=key: [
            r
            for r in rows
            if r["event_type"] == kind and r["payload"]["binding"].get("hypothesis_id") == key
        ]
        rating = ratings[key].model_dump(mode="json") if key in ratings else None
        source = p.get("binding", {}).get("generation_input")
        # Preserve exact source-bound Generation inputs; do not invent claim citations.
        generation_facts = [
            r
            for r in rows
            if r["event_type"] == "GroundedGenerationRecordedV1"
            and r["payload"].get("source_result_id") == p.get("source_result_id")
        ]
        result.append(
            {
                **p,
                "generation_index": 0
                if p.get("source_result_id") in roots
                else p.get("generation_index"),
                "created_sequence": event.sequence,
                "operator": "root"
                if p.get("source_result_id") in roots
                else plan.payload["decision"]["operator"]
                if plan
                else None,
                "operator_source_sequence": plan.sequence if plan else event.sequence,
                "rating": rating,
                "rating_status": "ranked"
                if rating and rating["decisive_matches"] >= 2
                else "evaluating",
                "ethics": review("CandidateEthicsRecordedV1"),
                "reflection": review("BaselineReflectionRecordedV1"),
                "generation_facts": generation_facts,
                "source_bound_input": source,
                "claim_summary": p.get("claim", "")[:175],
                "summary_source": "verbatim claim prefix",
            }
        )
    sort = lambda c: (-(c["rating"]["mu"] if c["rating"] else float("-inf")), c["hypothesis_id"])
    return {
        "source_sequence": events[-1].sequence if events else 0,
        "ranked": sorted([c for c in result if c["rating_status"] == "ranked"], key=sort),
        "pending": sorted([c for c in result if c["rating_status"] != "ranked"], key=sort),
    }
