"""Deterministic LiteraturePort outcomes, not retrieval or appraisal accuracy."""

import json
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from co_scientist_next.calls import TaskCalls
from co_scientist_next.contracts import CallResponse
from co_scientist_next.literature import (
    AccessLevel,
    ExecutionStatus,
    FetchRequest,
    FetchResult,
    LiteraturePort,
    SearchRequest,
    SearchResult,
    SourceRecord,
)
from co_scientist_next.store import Store

FIXTURES = json.loads(
    (Path(__file__).resolve().parents[2] / "examples/w0-t2-contracts.json").read_text()
)
LIT = FIXTURES["literature"]
TIME = LIT["executed_at"]
SOURCE = SourceRecord(LIT["source_ref"], LIT["citation"], LIT["title"])


class FixtureLiterature:
    """A local fixed response, never a source selection or query strategy."""

    def __init__(self, access=AccessLevel.ABSTRACT):
        self.access = access

    def search(self, request: SearchRequest) -> SearchResult:
        return SearchResult(
            request,
            ExecutionStatus.SUCCEEDED,
            TIME,
            (SOURCE,),
            reported_total=1,
            scope_complete=True,
        )

    def fetch(self, request: FetchRequest) -> FetchResult:
        text = {
            AccessLevel.METADATA: None,
            AccessLevel.ABSTRACT: LIT["abstract"],
            AccessLevel.FULL_TEXT: LIT["full_text"],
            AccessLevel.SUPPLEMENTARY: "SYNTHETIC supplementary material",
        }[self.access]
        return FetchResult(
            request,
            ExecutionStatus.SUCCEEDED,
            TIME,
            self.access,
            source=SOURCE,
            text=text,
            limitation=LIT["full_text_unavailable"]
            if self.access != request.desired_access
            else None,
        )


def query(cursor=None):
    return SearchRequest(LIT["source"], LIT["query"], LIT["scope"], cursor)


def test_success_empty_technical_failure_and_incomplete_are_distinct():
    empty = SearchResult(
        query(), ExecutionStatus.SUCCEEDED, TIME, reported_total=0, scope_complete=True
    )
    failed = SearchResult(query(), ExecutionStatus.FAILED, TIME, error=LIT["technical_failure"])
    partial = SearchResult(
        query(), ExecutionStatus.INCOMPLETE, TIME, (SOURCE,), error=LIT["technical_failure"]
    )
    assert empty.searched_empty_within_scope
    assert not failed.searched_empty_within_scope
    assert failed.reported_total is None and failed.error
    assert not partial.searched_empty_within_scope
    assert partial.items == (SOURCE,) and partial.error
    assert empty.request == failed.request == partial.request
    assert replace(SOURCE, title=None).title is None  # Unavailable metadata is not fabricated.
    with pytest.raises(ValueError, match="zero-result"):
        replace(failed, reported_total=0)
    with pytest.raises(ValueError, match="scope completion"):
        replace(failed, scope_complete=True)
    with pytest.raises(ValueError, match="nonempty"):
        replace(failed, error=None)


def test_empty_page_or_unreported_pagination_is_not_an_exhausted_empty_search():
    page = SearchResult(query(), ExecutionStatus.SUCCEEDED, TIME, next_cursor="page-2")
    assert not page.searched_empty_within_scope
    with pytest.raises(ValueError, match="scope completion"):
        replace(page, scope_complete=True)
    # Even the final empty page says nothing about items seen on earlier pages.
    last_page = SearchResult(
        query("last-page"), ExecutionStatus.SUCCEEDED, TIME, reported_total=10, scope_complete=True
    )
    assert not last_page.searched_empty_within_scope
    unknown_scope = SearchResult(query(), ExecutionStatus.SUCCEEDED, TIME)
    assert not unknown_scope.searched_empty_within_scope
    with pytest.raises(ValueError, match="reported total"):
        SearchResult(
            query(), ExecutionStatus.SUCCEEDED, TIME, reported_total=10, scope_complete=True
        )


@pytest.mark.parametrize(
    "access",
    [AccessLevel.METADATA, AccessLevel.ABSTRACT, AccessLevel.FULL_TEXT, AccessLevel.SUPPLEMENTARY],
)
def test_port_keeps_obtained_access_separate_from_requested_full_text(access):
    port: LiteraturePort = FixtureLiterature(access)
    search = port.search(query())
    fetched = port.fetch(FetchRequest(search.items[0].source_ref))
    assert fetched.request.desired_access == AccessLevel.FULL_TEXT
    assert fetched.access == access
    assert fetched.source == SOURCE
    assert fetched.executed_at == TIME
    if access == AccessLevel.METADATA:
        assert fetched.text is None
    else:
        assert fetched.text.startswith("SYNTHETIC")
    if access != AccessLevel.FULL_TEXT:
        assert fetched.limitation


def test_fetch_failure_and_partial_access_remain_locatable():
    request = FetchRequest(SOURCE.source_ref)
    failed = FetchResult(
        request, ExecutionStatus.FAILED, TIME, AccessLevel.NONE, error=LIT["technical_failure"]
    )
    assert failed.source is None and failed.text is None
    partial = FetchResult(
        request,
        ExecutionStatus.INCOMPLETE,
        TIME,
        AccessLevel.ABSTRACT,
        source=SOURCE,
        text=LIT["abstract"],
        limitation=LIT["full_text_unavailable"],
        error=LIT["technical_failure"],
    )
    assert partial.status == ExecutionStatus.INCOMPLETE and partial.text
    with pytest.raises(ValueError, match="successful fetch"):
        replace(failed, status=ExecutionStatus.SUCCEEDED, error=None)
    with pytest.raises(ValueError, match="nonfailed execution"):
        replace(partial, status=ExecutionStatus.FAILED)


def test_fetch_contract_rejects_mislabeled_empty_text_missing_limit_and_wrong_source():
    abstract = FixtureLiterature().fetch(FetchRequest(SOURCE.source_ref))
    with pytest.raises(ValueError, match="nonempty"):
        replace(abstract, limitation=None)
    with pytest.raises(ValueError, match="nonempty"):
        replace(abstract, access=AccessLevel.FULL_TEXT, text=None)
    with pytest.raises(ValueError, match="Metadata-only"):
        replace(abstract, access=AccessLevel.METADATA)
    with pytest.raises(ValueError, match="does not match"):
        replace(abstract, source=replace(SOURCE, source_ref="another-paper"))


def running_task(store):
    project = store.create_project("Synthetic shared-contract record")
    revision = store.revise_brief(project, {"question": "fixture only"})
    run = store.create_run(revision, ["fixture.contract.v1"], policy_ref="fixture-only")
    task_id = store.tasks(run)[0]["id"]
    with store.db:
        store.db.execute("UPDATE tasks SET status='running' WHERE id=?", (task_id,))
    return TaskCalls(store, task_id)


def test_literature_actual_request_access_and_limited_text_persist_through_m15(tmp_path):
    with Store(tmp_path / "literature.sqlite") as store:
        calls = running_task(store)
        request = FetchRequest(SOURCE.source_ref)
        fetched = FixtureLiterature().fetch(request)
        response = calls.execute(
            "fetch",
            "synthetic/literature-v1",
            asdict(request),
            lambda actual: CallResponse(asdict(fetched)),
        )
        saved = store.one("SELECT * FROM attempts")
        assert json.loads(saved["request"]) == {
            "source_ref": SOURCE.source_ref,
            "desired_access": "full_text",
        }
        assert response.output["access"] == "abstract"
        assert response.output["text"] == LIT["abstract"]
        assert response.output["limitation"] == LIT["full_text_unavailable"]
        assert json.loads(saved["response"]) == response.output
        assert all(v is None for v in json.loads(saved["usage"]).values())


def test_presentation_order_and_counterevidence_are_stored_not_scientifically_evaluated(tmp_path):
    with Store(tmp_path / "presentations.sqlite") as store:
        calls = running_task(store)
        core = FIXTURES["presentation"]["candidate_A_core"]
        for i, order in enumerate((["A", "B"], ["B", "A"])):
            request = {
                "fixture_only": True,
                "order": order,
                "core_A": core,
                "selection_policy": "synthetic-symmetric-v1",
            }
            calls.execute(
                f"presentation-{i}",
                "fixture/record-only-v1",
                request,
                lambda actual: CallResponse({"fixture_only": True, "no_judge": True}),
            )
        rows = store.rows("SELECT * FROM attempts ORDER BY ordinal,started_at")
        inputs = [json.loads(row["request"]) for row in rows]
        assert inputs[0]["order"] == ["A", "B"] and inputs[1]["order"] == ["B", "A"]
        assert inputs[0]["core_A"] == inputs[1]["core_A"] == core
        assert inputs[0]["core_A"]["counterevidence"] == ["SYNTHETIC E2"]
        # Stable call-key replay rejects a changed actual request. This is an M15
        # I/O guarantee, not a cross-Match core-content or bias detection policy.
        changed = {**inputs[0], "core_A": {**core, "counterevidence": []}}
        with pytest.raises(ValueError, match="different actual input"):
            calls.execute(
                "presentation-0",
                "fixture/record-only-v1",
                changed,
                lambda actual: pytest.fail("must not send changed replay request"),
            )
