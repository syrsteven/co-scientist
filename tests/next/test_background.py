"""P03–P07 engineering fixtures only, no real model calls or science acceptance."""

import json
import os
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

from co_scientist_next.background import BackgroundService
from co_scientist_next.background_ops import DevelopmentReadingAdapter
from co_scientist_next.goal import DEVELOPMENT_POLICY, DevelopmentAdapter, GoalSlice
from co_scientist_next.literature_runtime import LiteratureService
from co_scientist_next.store import Store

ROOT = Path(__file__).resolve().parents[2]
FixtureTransport = runpy.run_path(str(Path(__file__).with_name("test_literature_acquisition.py")))[
    "FixtureTransport"
]


def setup_flow(store, adapter=None):
    revision = store.revise_brief(
        store.create_project("OFFLINE reading fixture"),
        {
            "question": "Explore ALS nucleoporin phosphorylation; mechanism unknown",
            "hard_constraints": ["No preselected molecule"],
        },
    )
    goal = GoalSlice(store, DevelopmentAdapter(), development_test=True)
    run = goal.create_run(revision, DEVELOPMENT_POLICY)
    goal.execute(run)
    literature = LiteratureService(store, enabled=True, transport=FixtureTransport())
    literature.submit(run, "fixture-search", {"kind": "search", "query": "human concept query"})
    literature.execute("fixture-search")
    literature.submit(
        run,
        "fixture-fetch",
        {"kind": "fetch", "source_ref": "epmc:MED:999001", "desired_access": "abstract"},
    )
    history = literature.execute("fixture-fetch")
    service = BackgroundService(store, adapter or DevelopmentReadingAdapter())
    view = service.create_view(run, history[-1]["task_id"])
    return run, service, view, literature


@pytest.fixture
def flow(tmp_path):
    with Store(tmp_path / "background.sqlite") as store:
        yield store, *setup_flow(store)


def perform(service, run, op, request=None):
    ref = f"background-{len(service.actions(run)) + 1:03d}"
    service.submit(run, ref, op, request or {})
    data = service.execute(ref)
    return data["actions"][-1]


def seeds(flow):
    _store, run, service, view, _lit = flow
    perform(service, run, "P04", {"view_id": view["id"]})
    orientation = perform(service, run, "P05")
    directed = perform(
        service, run, "P06_DIRECTED", {"orientation_ref": orientation["request_id"], "count": 2}
    )
    opened = perform(
        service, run, "P06_OPEN", {"orientation_ref": orientation["request_id"], "count": 1}
    )
    return directed["result"]["artifact"]["seeds"] + opened["result"]["artifact"]["seeds"]


def packet(flow, seed):
    _store, run, service, view, _lit = flow
    perform(service, run, "P04", {"view_id": view["id"], "seed_id": seed["id"]})
    return perform(service, run, "P05", {"seed_id": seed["id"]})


def test_full_fixture_chain_bindings_negatives_and_raw_separation(flow):
    store, run, service, view, _ = flow
    original = store.one(
        "SELECT output FROM results WHERE task_id=?", (view["acquisition_task_id"],)
    )["output"]
    all_seeds = seeds(flow)
    seed = all_seeds[0]
    prepared = packet(flow, seed)
    ready = perform(
        service,
        run,
        "P07",
        {
            "seed_id": seed["id"],
            "packet_ref": prepared["request_id"],
            "requested_specificity": "testable conceptual relationship, no residue/kinase",
        },
    )
    assert ready["result"]["artifact"]["decision"] == "ready"
    assert ready["result"]["artifact"]["hypothetical_unknowns"]
    assert store.run(run)["status"] == "awaiting_generation"
    assert all(not t["module"].startswith("generation") for t in store.tasks(run))
    assert (
        original
        == store.one("SELECT output FROM results WHERE task_id=?", (view["acquisition_task_id"],))[
            "output"
        ]
    )
    contexts = prepared["result"]["artifact"]["retained_contexts"]
    for record in contexts:
        card = record["finding_cards"][0]
        assert card["source_ref"] == view["source_ref"] and card["access"] == "abstract"
        assert (
            card["negative_findings"]
            and card["negative_quotes"]
            and card["not_established"]
            and card["transfer_assumptions"]
        )
        assert card["images_seen"] is False and card["supplements_seen"] is False
    assert ready["result"]["science_validated"] is False
    assert ready["input"]["goal_context"]["original_question"].startswith("Explore ALS")
    for a in service.actions(run):
        assert (
            a["result"]["binding"]["run_id"] == run
            and a["result"]["binding"]["goal_ref"] == view["goal_ref"]
        )
        assert a["config"]["execution_mode"] == "development_fixture"
        attempt = store.one(
            "SELECT request,response FROM attempts WHERE task_id=?", (a["task_id"],)
        )
        assert (
            json.loads(attempt["request"])["prompt_version"]
            and json.loads(attempt["response"])["raw_response"]
        )


@pytest.mark.parametrize("scenario", ["ready", "retrieve_more", "unable_to_prepare"])
def test_readiness_branches_no_progress_and_seed_independence(flow, scenario):
    store, run, service, _, _ = flow
    first, second, *_ = seeds(flow)
    prepared = packet(flow, first)
    request = {
        "seed_id": first["id"],
        "packet_ref": prepared["request_id"],
        "requested_specificity": "exploratory relationship",
        "fixture_scenario": scenario,
    }
    record = perform(service, run, "P07", request)
    assert record["result"]["artifact"]["decision"] == scenario
    sends = len(store.rows("SELECT * FROM attempts"))
    again = perform(service, run, "P07", request)
    assert (
        again["result"]["background_status"] == "no_progress"
        and len(store.rows("SELECT * FROM attempts")) == sends
    )
    assert "decision" not in again["result"]
    other_packet = packet(flow, second)
    ready = perform(
        service,
        run,
        "P07",
        {
            "seed_id": second["id"],
            "packet_ref": other_packet["request_id"],
            "requested_specificity": "exploratory relationship",
        },
    )
    assert ready["result"]["artifact"]["decision"] == "ready"
    assert record["result"]["artifact"]["decision"] == scenario
    if scenario == "retrieve_more":
        assert record["result"]["artifact"]["focused_followups"][0]["why_it_matters"]


def test_open_input_isolation_and_seed_query_context(flow):
    _store, run, service, _view, lit = flow
    directed, _, opened = seeds(flow)
    open_action = service.successful(run, "P06_OPEN")[0]
    assert set(open_action["input"]) == {
        "goal_context",
        "neutral_overview",
        "source_discovery_capabilities",
        "generic_search_constraints",
    }
    assert directed["id"] not in json.dumps(open_action["input"])
    assert "directed_seed_briefs" not in json.dumps(open_action["input"])
    planned = perform(service, run, "P03", {"seed_id": directed["id"]})
    assert planned["result"]["artifact"]["executed"] is False
    before = len(lit.history(run))
    service.execute_query(run, planned["request_id"], 0, "directed-search", lit)
    assert len(lit.history(run)) == before + 1
    search = lit.history(run)[-1]
    assert search["request"]["query_origin"] == "model_planned_user_executed"
    assert search["request"]["background_context"]["seed_id"] == directed["id"]
    open_plan = perform(service, run, "P03", {"seed_id": opened["id"]})
    assert not any(
        s["seed_id"] == directed["id"] for s in open_plan["input"]["executed_search_history"]
    )
    # Explicit parent keeps seed provenance through fetch and cursor continuation.
    lit.submit(
        run,
        "seed-fetch",
        {
            "kind": "fetch",
            "source_ref": "epmc:MED:999001",
            "search_request_id": "directed-search",
            "desired_access": "abstract",
        },
    )
    h = lit.execute("seed-fetch")
    with pytest.raises(ValueError, match="Another seed"):
        service.create_view(run, h[-1]["task_id"], seed_id=opened["id"])
    own_view = service.create_view(run, h[-1]["task_id"], seed_id=directed["id"])
    with pytest.raises(ValueError, match="another Run/seed"):
        perform(service, run, "P04", {"view_id": own_view["id"], "seed_id": opened["id"]})
    lit.submit(
        run,
        "seed-next-page",
        {
            "kind": "search",
            "query": search["request"]["query"],
            "cursor": "page-2",
            "parent_search_id": "directed-search",
        },
    )
    lit.execute("seed-next-page")
    assert lit.history(run)[-1]["request"]["background_context"]["seed_id"] == directed["id"]


def test_foreign_run_seed_view_and_packet_rejected(flow):
    store, run, service, _view, _ = flow
    own = seeds(flow)[0]
    other_run, other, other_view, _ = setup_flow_foreign(store)
    with pytest.raises(ValueError):
        service.submit(run, "foreign-view", "P04", {"view_id": other_view["id"]})
    with pytest.raises(ValueError):
        other.submit(other_run, "foreign-seed", "P03", {"seed_id": own["id"]})
    prepared = packet(flow, own)
    other_seed = service.seeds(run)[1]
    with pytest.raises(ValueError, match="another seed"):
        service.submit(
            run,
            "wrong-packet",
            "P07",
            {
                "seed_id": other_seed["id"],
                "packet_ref": prepared["request_id"],
                "requested_specificity": "relationship",
            },
        )


def setup_flow_foreign(store):
    revision = store.revise_brief(store.create_project("Foreign"), {"question": "Foreign Goal"})
    goal = GoalSlice(store, DevelopmentAdapter(), development_test=True)
    run = goal.create_run(revision, DEVELOPMENT_POLICY)
    goal.execute(run)
    lit = LiteratureService(store, enabled=True, transport=FixtureTransport())
    lit.submit(run, "foreign-search", {"kind": "search", "query": "other concept"})
    lit.execute("foreign-search")
    lit.submit(
        run,
        "foreign-fetch",
        {"kind": "fetch", "source_ref": "epmc:MED:999001", "desired_access": "abstract"},
    )
    h = lit.execute("foreign-fetch")
    service = BackgroundService(store, DevelopmentReadingAdapter())
    return run, service, service.create_view(run, h[-1]["task_id"]), lit


@pytest.mark.parametrize(
    "scenario,expected", [("invalid_output", "invalid_output"), ("technical_failure", None)]
)
def test_technical_parse_failures_not_scientific_denial(flow, scenario, expected):
    store, run, service, view, _ = flow
    record = perform(service, run, "P04", {"view_id": view["id"], "fixture_scenario": scenario})
    if expected:
        assert record["result"]["background_status"] == expected
        assert store.rows("SELECT * FROM execution_facts WHERE kind='background_parse_error'")
    else:
        assert record["task_status"] == "failed" and record["result"] is None
    assert not service.seeds(run)
    # A known failure does not fabricate unable_to_prepare or block all future seeds.
    recovered = perform(service, run, "P04", {"view_id": view["id"]})
    assert recovered["result"]["background_status"] == "saved"


def test_cropping_capacity_and_no_silent_negative_omission(flow):
    store, run, service, view, _ = flow
    with pytest.raises(ValueError):
        service.create_view(run, view["acquisition_task_id"], start=1, end=20)
    cropped = service.create_view(
        run,
        view["acquisition_task_id"],
        start=1,
        end=20,
        reason="Explicit fixture excerpt, not whole abstract",
    )
    assert cropped["cropped"] and cropped["not_read_ranges"] and cropped["images_seen"] is False
    first = perform(service, run, "P04", {"view_id": view["id"]})
    second = perform(service, run, "P04", {"view_id": cropped["id"]})
    with pytest.raises(ValueError, match="negative"):
        service.submit(
            run,
            "omit-negative",
            "P05",
            {
                "reading_refs": [first["request_id"]],
                "omitted_readings": {second["request_id"]: "Cannot fit"},
            },
        )
    service.adapter.config["max_request_bytes"] = 10
    before = len(store.rows("SELECT * FROM attempts"))
    failure = perform(service, run, "P05")
    assert (
        failure["result"]["background_status"] == "capacity_exceeded"
        and len(store.rows("SELECT * FROM attempts")) == before
    )


def test_missing_config_no_fallback_and_review_fields_rejected(flow):
    store, run, service, view, _ = flow
    unavailable = BackgroundService(store)
    failure = perform(unavailable, run, "P04", {"view_id": view["id"]})
    assert (
        failure["result"]["background_status"] == "model_not_configured" and not failure["attempts"]
    )
    with pytest.raises(ValueError, match="Unexpected"):
        service.submit(
            run, "review-input", "P04", {"view_id": view["id"], "expected": "must not enter"}
        )
    with pytest.raises(ValueError):
        service.submit(run, "forbidden-generation", "P08", {})


def test_duplicate_application_and_submission_are_idempotent(flow):
    store, run, service, view, _ = flow
    record = perform(service, run, "P04", {"view_id": view["id"]})
    count = len(store.tasks(run))
    attempts = len(store.rows("SELECT * FROM attempts"))
    service.submit(run, record["request_id"], "P04", {"view_id": view["id"]})
    service.execute(record["request_id"])
    assert len(store.tasks(run)) == count and len(store.rows("SELECT * FROM attempts")) == attempts
    assert store.submit_result(record["task_id"], record["result"]) is False
    with pytest.raises(ValueError, match="different"):
        service.submit(run, record["request_id"], "P04", {"view_id": "changed"})


def test_cross_process_saved_model_response_replay(tmp_path):
    db = tmp_path / "crash.sqlite"
    with Store(db) as store:
        run, service, view, _ = setup_flow(store)
        service.submit(run, "crash-reading", "P04", {"view_id": view["id"]})
    code = r"""
import os,sys,json
from co_scientist_next.store import Store
from co_scientist_next.background import BackgroundService
from co_scientist_next.background_ops import DevelopmentReadingAdapter
from co_scientist_next.scheduler import Scheduler
with Store(sys.argv[1]) as store:
 service=BackgroundService(store,DevelopmentReadingAdapter())
 original=store.submit_result
 def crash(*args,**kwargs):
  print(json.dumps({'pid':os.getpid()}),flush=True);os._exit(29)
 store.submit_result=crash
 service.execute('crash-reading')
"""
    child = subprocess.run(
        [sys.executable, "-c", code, str(db)],
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
        check=False,
    )
    assert child.returncode == 29, child.stderr
    old = json.loads(child.stdout)

    class NoSend(DevelopmentReadingAdapter):
        def __call__(self, _):
            pytest.fail("Saved model success must replay, not send")

    with Store(db) as store:
        service = BackgroundService(store, NoSend())
        snapshot = service.execute("crash-reading", recover=True)
        record = snapshot["actions"][-1]
        assert record["result"]["background_status"] == "saved" and len(record["attempts"]) == 1
        assert old["pid"] != os.getpid()
        print(
            json.dumps(
                {
                    "scenario": "P04_saved_response_replay",
                    "crashed_pid": old["pid"],
                    "resumed_pid": os.getpid(),
                    "fixture_sends": 1,
                }
            )
        )


def test_review_metadata_cannot_enter_selected_views_or_model_payload(flow):
    store, run, service, view, _ = flow
    row = store.one("SELECT output FROM results WHERE task_id=?", (view["acquisition_task_id"],))
    acquisition = json.loads(row["output"])
    acquisition["details"]["metadata"]["review_only"] = {
        "expected": "REVIEW-ONLY-SENTINEL",
        "critical_failures": ["Never send"],
    }
    with store.db:
        store.db.execute(
            "UPDATE results SET output=? WHERE task_id=?",
            (json.dumps(acquisition), view["acquisition_task_id"]),
        )
    clean = service.create_view(run, view["acquisition_task_id"])
    clean["text"] = "Caller mutation must not alter the saved view"
    saved = next(v for v in service.views(run) if v["id"] == clean["id"])
    assert saved["text"] == view["text"] and "review_only" not in saved
    record = perform(service, run, "P04", {"view_id": clean["id"]})
    attempt = store.one("SELECT request FROM attempts WHERE task_id=?", (record["task_id"],))
    assert "REVIEW-ONLY-SENTINEL" not in attempt["request"]
    assert "critical_failures" not in attempt["request"]


def test_reading_uncertain_send_requires_explicit_authorization_and_lineage(tmp_path):
    class LostResponse(DevelopmentReadingAdapter):
        def __init__(self):
            super().__init__()
            self.sends = 0
            self.lost = True

        def __call__(self, request):
            self.sends += 1
            if self.lost:
                raise TimeoutError("DEVELOPMENT fixture: response missing after send")
            return super().__call__(request)

    with Store(tmp_path / "uncertain-reading.sqlite") as store:
        adapter = LostResponse()
        run, service, view, _ = setup_flow(store, adapter)
        service.submit(run, "uncertain-reading", "P04", {"view_id": view["id"]})
        record = service.execute("uncertain-reading")["actions"][-1]
        assert record["task_status"] == "blocked" and record["result"] is None
        service.execute("uncertain-reading", recover=True)
        assert adapter.sends == 1
        attempt = store.one("SELECT * FROM attempts WHERE task_id=?", (record["task_id"],))
        assert attempt["status"] == "uncertain"
        store.authorize_uncertain_retry(
            attempt["id"], "Explicit fixture confirmation; repeat send authorized"
        )
        store.retry_task(record["task_id"], "Explicit fixture retry")
        adapter.lost = False
        done = service.execute("uncertain-reading")["actions"][-1]
        attempts = store.rows(
            "SELECT * FROM attempts WHERE task_id=? ORDER BY ordinal", (record["task_id"],)
        )
        assert done["result"]["background_status"] == "saved" and adapter.sends == 2
        assert [a["status"] for a in attempts] == ["uncertain", "succeeded"] and attempts[1][
            "previous_id"
        ] == attempts[0]["id"]


def test_response_persistence_failure_does_not_allow_bypassing_uncertain_send(flow):
    store, run, service, view, _ = flow
    store.db.executescript("""CREATE TRIGGER fixture_failed_response_save BEFORE UPDATE OF status ON attempts
        WHEN NEW.status='succeeded' AND OLD.target='development-fixture/p03-p07-v1'
        BEGIN SELECT RAISE(ABORT,'Fixture response persistence failure'); END;""")
    service.submit(run, "response-save-failure", "P04", {"view_id": view["id"]})
    failed = service.execute("response-save-failure")["actions"][-1]
    assert failed["task_status"] == "failed" and failed["attempts"][0]["status"] == "in_flight"
    with pytest.raises(ValueError, match="Unresolved external"):
        service.submit(run, "must-not-bypass", "P04", {"view_id": view["id"]})
    assert len(service.actions(run)) == 1


def test_saved_browser_evidence_preserves_actual_inputs_and_no_real_calls():
    import gzip

    evidence = ROOT / "docs/verification/w1-l2/development-execution.json.gz"
    data = json.loads(gzip.decompress(evidence.read_bytes()))
    snapshot = data["snapshot"]
    assert (
        snapshot["real_adapter_attempts_recorded"] == 0 and snapshot["science_validated"] is False
    )
    actions = {a["task_id"]: a for a in snapshot["actions"]}
    for attempt in data["model_attempts"]:
        request = json.loads(attempt["request"])
        action = actions[attempt["task_id"]]
        assert json.loads(request["messages"][-1]["content"]) == action["input"]
        assert request["model_config"]["execution_mode"] == "development_fixture"
        assert request["binding"]["run_id"] == snapshot["run_id"]
    opened = next(a for a in snapshot["actions"] if a["operation"] == "P06_OPEN")
    assert set(opened["input"]) == {
        "goal_context",
        "neutral_overview",
        "source_discovery_capabilities",
        "generic_search_constraints",
    }


class RefinedReadingFixture(DevelopmentReadingAdapter):
    """Changed fixture interpretations of unchanged text, not real model reading."""

    def __init__(self):
        super().__init__()
        self.reading_revision = 0
        self.packet_revision = 0

    def __call__(self, request):
        from co_scientist_next.contracts import CallResponse
        from co_scientist_next.store import encode

        response = super().__call__(request)
        value = json.loads(response.output["raw_response"])
        if request["operation"] == "P04" and self.reading_revision:
            value["finding_cards"][0]["endpoint"] = (
                "OFFLINE fixture newly extracted measured endpoint"
            )
            value["finding_cards"][0]["not_established"] = [
                "OFFLINE fixture newly identified inference limit"
            ]
        if request["operation"] == "P05" and self.packet_revision:
            value["competing_explanations"] = ["OFFLINE fixture newly preserved competing context"]
        return CallResponse({"raw_response": encode(value), "fixture": True})


def readiness(service, run, seed, prepared, scenario="retrieve_more"):
    return perform(
        service,
        run,
        "P07",
        {
            "seed_id": seed["id"],
            "packet_ref": prepared["request_id"],
            "requested_specificity": "exploratory relationship",
            "fixture_scenario": scenario,
        },
    )


def legacy_progress_hash(store, action):
    """Existing PR7 results have the old source-only digest; retain their facts."""
    result = {**action["result"], "progress_fingerprint": "legacy-source-only-v1-digest"}
    with store.db:
        store.db.execute(
            "UPDATE results SET output=? WHERE task_id=?", (json.dumps(result), action["task_id"])
        )


def test_rereading_same_source_with_new_findings_allows_p07_reassessment(flow):
    store, run, service, view, _ = flow
    service.adapter = RefinedReadingFixture()
    seed = seeds(flow)[0]
    before = packet(flow, seed)
    previous = readiness(service, run, seed, before)
    assert previous["result"]["artifact"]["decision"] == "retrieve_more"
    service.adapter.reading_revision = 1
    after = packet(flow, seed)
    assert (
        before["result"]["artifact"]["source_views"] == after["result"]["artifact"]["source_views"]
    )
    assert any(
        c["endpoint"].endswith("newly extracted measured endpoint")
        for r in after["result"]["artifact"]["retained_contexts"]
        for c in r["finding_cards"]
    )
    attempts = len(store.rows("SELECT * FROM attempts"))
    reassessed = readiness(service, run, seed, after, "ready")
    assert reassessed["result"]["background_status"] == "saved"
    assert reassessed["result"]["artifact"]["decision"] == "ready"
    assert len(store.rows("SELECT * FROM attempts")) == attempts + 1
    assert next(v for v in service.views(run) if v["id"] == view["id"])["text"] == view["text"]


def test_changed_synthesis_without_new_source_also_allows_p07(flow):
    store, run, service, _, _ = flow
    service.adapter = RefinedReadingFixture()
    seed = seeds(flow)[0]
    before = packet(flow, seed)
    readiness(service, run, seed, before)
    service.adapter.packet_revision = 1
    after = perform(service, run, "P05", {"seed_id": seed["id"]})
    attempts = len(store.rows("SELECT * FROM attempts"))
    reassessed = readiness(service, run, seed, after)
    assert reassessed["result"]["background_status"] == "saved"
    assert len(store.rows("SELECT * FROM attempts")) == attempts + 1


@pytest.mark.parametrize("repeat_reading", [False, True])
def test_identical_packet_or_duplicate_reading_new_ids_is_still_no_progress(flow, repeat_reading):
    store, run, service, view, _ = flow
    seed = seeds(flow)[0]
    before = packet(flow, seed)
    previous = readiness(service, run, seed, before)
    legacy_progress_hash(store, previous)
    if repeat_reading:
        copy = service.create_view(run, view["acquisition_task_id"])
        assert copy["id"] != view["id"] and copy["text"] == view["text"]
        perform(service, run, "P04", {"view_id": copy["id"], "seed_id": seed["id"]})
    after = perform(service, run, "P05", {"seed_id": seed["id"]})
    assert before["request_id"] != after["request_id"]
    attempts = len(store.rows("SELECT * FROM attempts"))
    unchanged = readiness(service, run, seed, after)
    assert unchanged["result"]["background_status"] == "no_progress"
    assert len(store.rows("SELECT * FROM attempts")) == attempts


def test_only_identity_and_clock_changes_do_not_change_preparation_content(flow):
    import copy

    _, run, service, _, _ = flow
    seed = seeds(flow)[0]
    prepared = packet(flow, seed)
    original = service.build_input(
        run,
        "P07",
        {
            "seed_id": seed["id"],
            "packet_ref": prepared["request_id"],
            "requested_specificity": "conceptual relationship",
        },
    )
    card = original["packet"]["retained_contexts"][0]["finding_cards"][0]
    reading_ref = original["packet"]["retained_contexts"][0]["record_ref"]
    query_ref = original["executed_search_records"][0]["record_ref"]
    original["packet"]["knowledge_edges"] = [
        {
            "kind": "observation",
            "description": f"Fixture [{card['id']}] from [{reading_ref}] and [{query_ref}]",
            "finding_refs": [card["id"]],
        }
    ]
    renamed = copy.deepcopy(original)
    ids = {prepared["request_id"], seed["id"]}
    ids.update(v["id"] for v in original["packet"]["source_views"])
    ids.update(r["record_ref"] for r in original["packet"]["retained_contexts"])
    ids.update(c["id"] for r in original["packet"]["retained_contexts"] for c in r["finding_cards"])
    ids.update(s["record_ref"] for s in original["executed_search_records"])
    mapping = {ref: "new-transient-" + str(i) for i, ref in enumerate(sorted(ids))}

    def rename(value):
        if isinstance(value, str):
            for old, new in mapping.items():
                value = value.replace(old, new)
            return value
        if isinstance(value, list):
            return [rename(v) for v in value]
        if isinstance(value, dict):
            return {mapping.get(k, k): rename(v) for k, v in value.items()}
        return value

    renamed = rename(renamed)
    renamed["packet"]["created_at"] = "2099-01-01"
    for v in renamed["packet"]["source_views"]:
        v["created_at"] = "2099-01-01"
    for r in renamed["packet"]["retained_contexts"]:
        r["created_at"] = "2099-01-01"
        r["finding_cards"].reverse()
    for s in renamed["executed_search_records"]:
        s["result"]["executed_at"] = "2099-01-01"
    assert service.progress(original) == service.progress(renamed)


def test_new_reading_on_directed_seed_does_not_advance_open_sibling(flow):
    store, run, service, _, _ = flow
    service.adapter = RefinedReadingFixture()
    first, _, opened = seeds(flow)
    first_packet = packet(flow, first)
    sibling_packet = packet(flow, opened)
    readiness(service, run, first, first_packet)
    sibling_previous = readiness(service, run, opened, sibling_packet)
    assert sibling_previous["result"]["background_status"] == "saved"
    service.adapter.reading_revision = 1
    changed_packet = packet(flow, first)
    assert readiness(service, run, first, changed_packet)["result"]["background_status"] == "saved"
    rebuilt_sibling = perform(service, run, "P05", {"seed_id": opened["id"]})
    assert "newly extracted measured endpoint" not in json.dumps(rebuilt_sibling["input"])
    attempts = len(store.rows("SELECT * FROM attempts"))
    assert (
        readiness(service, run, opened, rebuilt_sibling)["result"]["background_status"]
        == "no_progress"
    )
    assert len(store.rows("SELECT * FROM attempts")) == attempts


def test_progress_preserves_background_relationship_to_finding_content(flow):
    import copy

    _, run, service, _, _ = flow
    service.adapter = RefinedReadingFixture()
    seed = seeds(flow)[0]
    packet(flow, seed)
    service.adapter.reading_revision = 1
    prepared = packet(flow, seed)
    payload = service.build_input(
        run,
        "P07",
        {
            "seed_id": seed["id"],
            "packet_ref": prepared["request_id"],
            "requested_specificity": "conceptual relationship",
        },
    )
    cards = [c for r in payload["packet"]["retained_contexts"] for c in r["finding_cards"]]
    before = next(c for c in cards if c["endpoint"] == "Unknown in fixture")
    after = next(c for c in cards if c["endpoint"].endswith("newly extracted measured endpoint"))
    payload["packet"]["knowledge_edges"] = [
        {
            "kind": "observation",
            "description": "Same relationship text",
            "finding_refs": [before["id"]],
        }
    ]
    rewired = copy.deepcopy(payload)
    rewired["packet"]["knowledge_edges"][0]["finding_refs"] = [after["id"]]
    assert service.progress(payload) != service.progress(rewired)
