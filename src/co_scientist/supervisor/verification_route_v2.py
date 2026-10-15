"""Pure construction of frozen V2 verification inputs from durable search events.

The Supervisor owns event and external-call provenance checks and task enqueue.
This module never retrieves literature or guesses EvidenceUnit identities.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, cast

from co_scientist.domain.claim_verification import (
    EvidenceSnapshot,
    SearchCoverageItemV2,
    SearchCoverageV2,
    SearchIntent,
)
from co_scientist.domain.evidence_units import evidence_units_for_snapshot
from co_scientist.events.models import DomainEvent, NewEvent
from co_scientist.ports.external_provider import thaw_json

Event = DomainEvent | NewEvent
RawCallValidator = Callable[[str, Mapping[str, Any]], bool]

_INTENTS = ("support", "refute", "prior_work", "competing_mechanism")
_SNAPSHOT_FIELDS = tuple(EvidenceSnapshot.model_fields)


def build_verification_inputs_v2(
    events: Sequence[Event], *, hypothesis_id: str, content_hash: str,
    max_sources_per_claim: int, max_evidence_tokens: int,
    raw_call_valid: RawCallValidator,
) -> dict[str, Any] | None:
    """Return task inputs when retrieval is terminal and all raw links validate.

    Missing required intent remains absent from SearchCoverageV2 and therefore
    incomplete; a planned but unfinished authorized query is not terminal.
    """

    scoped = [event for event in events
              if event.payload.get("hypothesis_id") == hypothesis_id
              and event.payload.get("hypothesis_content_hash") == content_hash]
    if not any(event.event_type == "ClaimSearchPlanned" for event in scoped):
        return None
    claims = [thaw_json(event.payload) for event in scoped
              if event.event_type == "HypothesisClaimCreated"
              and event.schema_version == 2
              and event.payload.get("importance") == "critical"]
    if not claims or len({claim["claim_id"] for claim in claims}) != len(claims):
        raise ValueError("V2 verification requires unique frozen critical claims")
    claim_ids = {str(claim["claim_id"]) for claim in claims}
    requests = [event for event in scoped if event.event_type in {
        "ToolRequestAuthorized", "ToolRequestDenied",
    }]
    if not requests:
        return None
    by_query: dict[str, Event] = {}
    for event in requests:
        query_id = str(event.payload["query_id"])
        if query_id in by_query:
            raise ValueError("duplicate frozen claim search query identity")
        if (event.payload.get("claim_id") not in claim_ids
                or event.payload.get("claim_content_hash") != content_hash
                or event.payload.get("intent") not in _INTENTS):
            raise ValueError("search request is outside frozen V2 claim scope")
        by_query[query_id] = event
    search_events = [event for event in scoped
                     if event.event_type == "ClaimSearchResultRecorded"]
    retrieval_events = [event for event in scoped
                        if event.event_type == "ClaimRetrievalCompleted"]
    search_results = {str(event.payload["query_id"]): event for event in search_events}
    retrievals = {str(event.payload["query_id"]): event for event in retrieval_events}
    if len(search_results) != len(search_events) or len(retrievals) != len(retrieval_events):
        raise ValueError("duplicate search or retrieval event for frozen query")
    snapshot_events = [event for event in scoped
                       if event.event_type == "EvidenceSnapshotRecorded"]
    if (set(search_results) - set(by_query)
            or set(retrievals) - set(by_query)
            or any(str(event.payload.get("query_id")) not in by_query
                   for event in snapshot_events)):
        raise ValueError("retrieval evidence is outside frozen search scope")
    snapshot_by_query: dict[str, list[EvidenceSnapshot]] = {}
    snapshot_identity: dict[str, EvidenceSnapshot] = {}
    for event in snapshot_events:
        fields = {name: event.payload[name] for name in _SNAPSHOT_FIELDS}
        snapshot = EvidenceSnapshot.model_validate(fields)
        if (snapshot.raw_artifact_id != event.payload.get("source_call_id")
                or snapshot.raw_sha256 != event.payload.get("raw_artifact_ref", {}).get("sha256")):
            raise ValueError("EvidenceSnapshot raw provenance differs from retrieval")
        previous = snapshot_identity.setdefault(snapshot.snapshot_id, snapshot)
        if previous != snapshot:
            raise ValueError("EvidenceSnapshot identity has conflicting content")
        snapshot_by_query.setdefault(str(event.payload["query_id"]), []).append(snapshot)

    coverage_items: list[SearchCoverageItemV2] = []
    search_records: list[dict[str, Any]] = []
    for intent in _INTENTS:
        for claim_id in sorted(claim_ids):
            group = sorted((event for event in requests
                            if event.payload["claim_id"] == claim_id
                            and event.payload["intent"] == intent),
                           key=lambda event: str(event.payload["query_id"]))
            if not group:
                continue
            query_ids: list[str] = []
            result_count = 0
            for request in group:
                qid = str(request.payload["query_id"])
                query_ids.append(qid)
                if request.event_type == "ToolRequestDenied":
                    continue
                search = search_results.get(qid)
                if search is None:
                    return None
                if (search.payload.get("claim_id") != claim_id
                        or search.payload.get("intent") != intent):
                    raise ValueError("search result differs from frozen request binding")
                raw_ref = search.payload.get("raw_artifact_ref")
                call_id = search.payload.get("source_call_id")
                if (not isinstance(raw_ref, Mapping) or not isinstance(call_id, str)
                        or not raw_call_valid(call_id, raw_ref)):
                    return None
                pmids = search.payload.get("pmids")
                if not isinstance(pmids, (list, tuple)) or any(
                    not isinstance(pmid, str) or not pmid for pmid in pmids
                ):
                    raise ValueError("persisted PubMed search result is malformed")
                result_count += len(pmids)
                search_records.append({
                    "query_id": qid, "claim_id": claim_id, "intent": intent,
                    "query": request.payload["query"], "pmids": list(pmids),
                })
                if pmids:
                    retrieval = retrievals.get(qid)
                    if retrieval is None:
                        return None
                    if (retrieval.payload.get("claim_id") != claim_id
                            or retrieval.payload.get("intent") != intent
                            or any(event.payload.get("claim_id") != claim_id
                                   or event.payload.get("intent") != intent
                                   for event in snapshot_events
                                   if event.payload.get("query_id") == qid)):
                        raise ValueError("retrieval differs from frozen request binding")
                    retrieval_ref = retrieval.payload.get("raw_artifact_ref")
                    retrieval_call_id = retrieval.payload.get("source_call_id")
                    if (not isinstance(retrieval_ref, Mapping)
                            or not isinstance(retrieval_call_id, str)
                            or not raw_call_valid(retrieval_call_id, retrieval_ref)):
                        return None
                    snapshots = snapshot_by_query.get(qid, [])
                    expected_ids = {f"pubmed:{pmid}" for pmid in pmids}
                    source_ids = tuple(retrieval.payload.get("source_ids", ()))
                    snapshot_ids = tuple(retrieval.payload.get("snapshot_ids", ()))
                    if (len(expected_ids) != len(pmids)
                            or len(set(source_ids)) != len(source_ids)
                            or len(set(snapshot_ids)) != len(snapshot_ids)
                            or len({item.snapshot_id for item in snapshots}) != len(snapshots)
                            or set(source_ids) != expected_ids
                            or {item.source_id for item in snapshots} != expected_ids
                            or set(snapshot_ids) != {
                                item.snapshot_id for item in snapshots
                            } or any(item.raw_artifact_id != retrieval_call_id
                                     for item in snapshots)):
                        raise ValueError("retrieved sources do not match frozen PubMed result")
                elif snapshot_by_query.get(qid) or qid in retrievals:
                    raise ValueError("empty search has unexpected retrieval evidence")
            complete = all(
                event.event_type == "ToolRequestAuthorized" for event in group
            )
            coverage_items.append(SearchCoverageItemV2(
                claim_id=claim_id, intent=cast(SearchIntent, intent),
                query_ids=tuple(query_ids),
                raw_persisted=complete, response_validated=complete,
                applied=complete, pagination_complete=complete,
                result_count=result_count,
            ))
    coverage = SearchCoverageV2(
        contract_version="search-coverage-v2", items=tuple(coverage_items),
    )
    priority = {"refute": 0, "prior_work": 1, "competing_mechanism": 2, "support": 3}
    available = list(snapshot_identity.values())
    available.sort(key=lambda item: (
        priority.get(str(next((event.payload["intent"] for event in snapshot_events
                               if event.payload.get("snapshot_id") == item.snapshot_id), "")), 4),
        item.source_id, item.snapshot_id,
    ))
    selected: list[EvidenceSnapshot] = []
    source_counts: dict[str, int] = {}
    selected_tokens = 0
    for snapshot in available:
        event = next(event for event in snapshot_events
                     if event.payload.get("snapshot_id") == snapshot.snapshot_id)
        claim_id = str(event.payload["claim_id"])
        tokens = (len(snapshot.title) + len(snapshot.abstract or "") + 3) // 4
        if (source_counts.get(claim_id, 0) >= max_sources_per_claim
                or selected_tokens + tokens > max_evidence_tokens):
            continue
        selected.append(snapshot)
        selected_tokens += tokens
        source_counts[claim_id] = source_counts.get(claim_id, 0) + 1
    return {
        "hypothesis_id": hypothesis_id, "content_hash": content_hash,
        "critical_claims": claims, "search_records": search_records,
        "evidence_snapshots": [item.model_dump(mode="json") for item in selected],
        "evidence_units": [unit.model_dump(mode="json") for item in selected
                           for unit in evidence_units_for_snapshot(item)],
        "search_coverage": coverage.model_dump(mode="json"),
        "searched_queries": [str(event.payload["query"]) for event in requests],
        "retrieved_source_ids": sorted({item.source_id for item in available}),
        "search_scope": "Frozen PubMed queries with title/abstract retrieval",
        "limitations": [
            "Only PubMed title/abstract evidence was retrieved.",
            "No retrieval is not proof of scientific novelty.",
            *(["Some snapshots were omitted by the frozen evidence limit."]
              if len(selected) < len(available) else []),
        ],
    }
