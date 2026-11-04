"""Offline P08 engine fixtures; no scientific validation or real model calls."""

import copy
import json
import runpy
from pathlib import Path

import pytest

from co_scientist_next.contracts import CallResponse, KnownCallFailure
from co_scientist_next.generation import GenerationService
from co_scientist_next.generation_ops import (
    MODES,
    PROMPT_VERSION,
    USER_FIELDS,
    DevelopmentGenerationAdapter,
)
from co_scientist_next.store import Store, encode

HELPERS = runpy.run_path(str(Path(__file__).with_name("test_background.py")))


def prepared(store, scenario="ready"):
    run, background, view, lit = HELPERS["setup_flow"](store)
    flow = (store, run, background, view, lit)
    seed = HELPERS["seeds"](flow)[0]
    packet = HELPERS["packet"](flow, seed)
    ready = HELPERS["perform"](
        background,
        run,
        "P07",
        {
            "seed_id": seed["id"],
            "packet_ref": packet["request_id"],
            "requested_specificity": "Conditional exploratory relations only; no preselected model",
            "fixture_scenario": scenario,
        },
    )
    request = {
        "seed_id": seed["id"],
        "packet_ref": packet["request_id"],
        "readiness_ref": ready["request_id"],
        "mode": "DIRECT",
        "candidate_id": "candidate-offline-1",
    }
    return run, background, request


class Capture(DevelopmentGenerationAdapter):
    def __init__(self, scenario="success"):
        self.sent = []
        self.scenario = scenario

    def __call__(self, request):
        self.sent.append(copy.deepcopy(request))
        if self.scenario == "uncertain":
            raise TimeoutError("OFFLINE fixture lost response")
        if self.scenario == "failed":
            raise KnownCallFailure("OFFLINE known failure")
        response = super().__call__(request)
        value = json.loads(response.output["raw_response"])
        if self.scenario == "invalid":
            value["candidate_id"] = "wrong-identity"
        if self.scenario == "foreign_reference":
            value["evidence_anchors"][0]["source_view_ref"] = "unknown-view"
        if self.scenario == "untyped":
            value["mechanism_steps"][0]["status"] = "proven_in_ALS"
        return CallResponse({**response.output, "raw_response": encode(value)})


@pytest.mark.parametrize("mode", MODES)
def test_modes_exact_input_saved_candidate_and_duplicate_application(tmp_path, mode):
    with Store(tmp_path / "generation.sqlite") as store:
        run, background, request = prepared(store)
        request["mode"] = mode
        adapter = Capture()
        gen = GenerationService(store, adapter)
        saved = gen.submit(run, "offline-p08-generate", request)
        payload = json.loads(saved["input"])
        assert set(payload) == USER_FIELDS
        assert payload["readiness_record"]["allowed_specificity"]
        assert "premise_gaps" in payload["readiness_record"]
        assert (
            payload["actual_frozen_seed_background_packet"]
            == background.action(run, request["packet_ref"], "P05")["result"]["artifact"]
        )
        other = background.seeds(run)[-1]["id"]
        assert other not in encode(payload)
        data = gen.execute("offline-p08-generate")
        record = data["actions"][0]
        result = record["result"]
        assert result["generation_status"] == "generated" and result["science_validated"] is False
        assert result["candidate"]["candidate_id"] == request["candidate_id"]
        assert result["candidate_status"] == "generated_pending_candidate_ethics_r0"
        assert result["binding"]["mode"] == mode and record["prompt_version"] == PROMPT_VERSION
        assert (
            len(adapter.sent) == 1
            and json.loads(adapter.sent[0]["messages"][-1]["content"]) == payload
        )
        count = len(store.tasks(run))
        assert (
            store.submit_result(saved["task_id"], result, stop_status="awaiting_candidate_ethics")
            is False
        )
        assert gen.submit(run, "offline-p08-generate", request)["task_id"] == saved["task_id"]
        assert (
            gen.execute("offline-p08-generate")["actions"] == data["actions"]
            and len(adapter.sent) == 1
        )
        assert (
            len(store.tasks(run)) == count
            and store.run(run)["status"] == "awaiting_candidate_ethics"
        )
        changed = copy.deepcopy(result)
        changed["candidate"]["scoped_claim"] = "changed"
        with pytest.raises(ValueError):
            store.submit_result(saved["task_id"], changed, stop_status="awaiting_candidate_ethics")
        with pytest.raises(ValueError, match="identity already reserved"):
            gen.submit(run, "offline-another-request", request)
        assert all(not t["module"].startswith(("candidate_ethics", "r0")) for t in store.tasks(run))


@pytest.mark.parametrize(
    "scenario", ["retrieve_more", "unable_to_prepare", "invalid_output", "technical_failure"]
)
def test_non_ready_cannot_generate_even_when_run_status_is_spoofed(tmp_path, scenario):
    with Store(tmp_path / "not-ready.sqlite") as store:
        run, _, request = prepared(store, scenario)
        # Test corruption of a status shortcut, never used by the implementation.
        with store.db:
            store.db.execute("UPDATE runs SET status='awaiting_generation' WHERE id=?", (run,))
        gen = GenerationService(store, Capture())
        with pytest.raises(ValueError):
            gen.submit(run, "not-ready-generation", request)
        assert not store.rows("SELECT * FROM generation_actions")


@pytest.mark.parametrize("field", ["seed_id", "packet_ref", "readiness_ref"])
def test_cross_seed_or_run_binding_rejected(tmp_path, field):
    with Store(tmp_path / "binding.sqlite") as store:
        run, bg, request = prepared(store)
        other_seed = bg.seeds(run)[-1]
        packet = HELPERS["packet"]((store, run, bg, bg.views(run)[0], bg.literature), other_seed)
        other_ready = HELPERS["perform"](
            bg,
            run,
            "P07",
            {
                "seed_id": other_seed["id"],
                "packet_ref": packet["request_id"],
                "requested_specificity": "exploratory",
            },
        )
        request[field] = {
            "seed_id": other_seed["id"],
            "packet_ref": packet["request_id"],
            "readiness_ref": other_ready["request_id"],
        }[field]
        with pytest.raises(ValueError):
            GenerationService(store, Capture()).submit(run, "foreign-seed-request", request)
        foreign_run, _, _, _ = HELPERS["setup_flow_foreign"](store)
        with pytest.raises(ValueError):
            GenerationService(store, Capture()).submit(foreign_run, "foreign-run-request", request)


@pytest.mark.parametrize(
    "scenario", ["failed", "uncertain", "invalid", "foreign_reference", "untyped"]
)
def test_failure_never_produces_candidate_or_downstream_and_no_implicit_retry(tmp_path, scenario):
    with Store(tmp_path / "failure.sqlite") as store:
        run, _, request = prepared(store)
        adapter = Capture(scenario)
        gen = GenerationService(store, adapter)
        gen.submit(run, "failed-generation", request)
        record = gen.execute("failed-generation")["actions"][0]
        assert not (record["result"] or {}).get("candidate")
        gen.execute("failed-generation", recover=True)
        assert len(adapter.sent) == 1
        if scenario == "uncertain":
            assert record["task_status"] == "blocked"
            attempt = store.one("SELECT * FROM attempts WHERE task_id=?", (record["task_id"],))
            assert attempt["status"] == "uncertain" and all(
                v is None for v in json.loads(attempt["usage"]).values()
            )
            other = {**request, "candidate_id": "different-identity"}
            with store.db:
                store.db.execute("UPDATE runs SET status='awaiting_generation' WHERE id=?", (run,))
            with pytest.raises(ValueError, match="Unresolved external"):
                gen.submit(run, "another-generation", other)


def test_unknown_fields_old_mode_and_unconfigured_model_do_not_fall_back(tmp_path):
    with Store(tmp_path / "config.sqlite") as store:
        run, _, request = prepared(store)
        service = GenerationService(store)
        for bad in [{**request, "expected": {}}, {**request, "mode": "ITERATIVE_ASSUMPTIONS"}]:
            with pytest.raises(ValueError):
                service.submit(run, "bad-generation", bad)
        service.submit(run, "no-generation-model", request)
        result = service.execute("no-generation-model")["actions"][0]["result"]
        assert result["generation_status"] == "model_not_configured"
        assert not store.rows(
            "SELECT * FROM attempts WHERE task_id=?", (service.actions(run)[0]["task_id"],)
        )


def test_capacity_failure_preserves_full_input_without_send(tmp_path):
    class Small(Capture):
        def public_config(self):
            return {**super().public_config(), "max_request_bytes": 1000}

    with Store(tmp_path / "capacity.sqlite") as store:
        run, _, request = prepared(store)
        adapter = Small()
        gen = GenerationService(store, adapter)
        gen.submit(run, "over-capacity-p08", request)
        result = gen.execute("over-capacity-p08")["actions"][0]["result"]
        assert result["generation_status"] == "capacity_exceeded" and not adapter.sent


def test_restart_success_call_replay_before_result_application_and_explicit_uncertain_retry(
    tmp_path, monkeypatch
):
    db = tmp_path / "restart.sqlite"
    adapter = Capture()
    with Store(db) as store:
        run, _, request = prepared(store)
        gen = GenerationService(store, adapter)
        saved = gen.submit(run, "p08-crash-after-call", request)
        original = store.submit_result
        monkeypatch.setattr(
            store,
            "submit_result",
            lambda *_a, **_kw: (_ for _ in ()).throw(
                RuntimeError("OFFLINE result persistence interruption")
            ),
        )
        gen.execute("p08-crash-after-call")
        assert len(adapter.sent) == 1
        monkeypatch.setattr(store, "submit_result", original)
    with Store(db) as store:
        gen = GenerationService(store, adapter)
        store.retry_task(saved["task_id"], "Explicit offline result recovery")
        record = gen.execute("p08-crash-after-call", recover=True)["actions"][0]
        assert record["result"]["generation_status"] == "generated" and len(adapter.sent) == 1
        second = {**request, "candidate_id": "candidate-uncertain"}
        adapter.scenario = "uncertain"
        saved2 = gen.submit(run, "p08-uncertain-recovery", second)
        gen.execute("p08-uncertain-recovery")
        old = store.one("SELECT * FROM attempts WHERE task_id=?", (saved2["task_id"],))
        store.authorize_uncertain_retry(
            old["id"], "Accept duplicate execution/cost in offline fixture"
        )
        store.retry_task(saved2["task_id"], "Explicit one-attempt offline retry")
        adapter.scenario = "success"
        gen.execute("p08-uncertain-recovery")
        rows = store.rows(
            "SELECT * FROM attempts WHERE task_id=? ORDER BY ordinal", (saved2["task_id"],)
        )
        assert [r["status"] for r in rows] == ["uncertain", "succeeded"] and rows[1][
            "previous_id"
        ] == old["id"]
        assert rows[1]["request"] == rows[0]["request"]


def test_cross_process_replay_applies_saved_success_without_new_send(tmp_path):
    import os
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[2]
    db = tmp_path / "crash.sqlite"
    info = tmp_path / "saved.json"
    script = r"""
import json,os,runpy,sys
from co_scientist_next.store import Store
from co_scientist_next.generation import GenerationService
helpers=runpy.run_path(sys.argv[3])
with Store(sys.argv[1]) as s:
 run,bg,req=helpers['prepared'](s)
 adapter=helpers['Capture']();gen=GenerationService(s,adapter)
 a=gen.submit(run,'process-crash-generation',req)
 open(sys.argv[2],'w').write(json.dumps({'run':run,'task':a['task_id'],'candidate':req['candidate_id']}))
 s.submit_result=lambda *_a,**_kw:os._exit(0)
 gen.execute('process-crash-generation')
"""
    subprocess.run(
        [sys.executable, "-c", script, str(db), str(info), str(Path(__file__))],
        env={**os.environ, "PYTHONPATH": str(root / "src")},
        check=True,
    )
    saved = json.loads(info.read_text())
    with Store(db) as store:
        adapter = Capture()
        gen = GenerationService(store, adapter)
        result = gen.execute("process-crash-generation", recover=True)["actions"][0]["result"]
        assert result["candidate"]["candidate_id"] == saved["candidate"] and not adapter.sent
        attempts = store.rows("SELECT * FROM attempts WHERE task_id=?", (saved["task"],))
        assert len(attempts) == 1 and attempts[0]["status"] == "succeeded"


@pytest.mark.parametrize(
    "scenario", ["stop", "length", "empty", "incomplete_json", "http_error", "uncertain"]
)
def test_openai_adapter_wire_usage_and_bad_completion_paths(tmp_path, monkeypatch, scenario):
    import urllib.request

    from co_scientist_next.reading_model import OpenAIChat

    captured = []
    fixture = DevelopmentGenerationAdapter()
    secret = "INVENTED-P08-SECRET"
    config = {
        "provider": "openai",
        "endpoint": "https://api.openai.com/v1/chat/completions",
        "model": "gpt-6.1-sol",
        "parameters": {
            "reasoning_effort": "high",
            "max_completion_tokens": 32768,
            "response_format": {"type": "json_object"},
        },
        "timeout_seconds": 600,
        "max_request_bytes": 262144,
    }

    class Response:
        def __init__(self, body):
            self.body = body
            self.code = 503 if scenario == "http_error" else 200
            self.headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def read(self, _):
            return self.body

    class Opener:
        def open(self, req, *, timeout):
            body = json.loads(req.data)
            captured.append(body)
            assert timeout == 600 and "temperature" not in body
            assert body["model"] == "gpt-6.1-sol" and body["max_completion_tokens"] == 32768
            if scenario == "uncertain":
                raise TimeoutError(secret)
            content = fixture({"messages": body["messages"]}).output["raw_response"]
            if scenario == "empty":
                content = ""
            if scenario == "incomplete_json":
                content = '{"title":'
            return Response(
                json.dumps(
                    {
                        "choices": [
                            {
                                "finish_reason": "length" if scenario == "length" else "stop",
                                "message": {"content": content},
                            }
                        ],
                        "usage": {
                            "prompt_tokens": 101,
                            "completion_tokens": 50,
                            "completion_tokens_details": {"reasoning_tokens": 7},
                            "total_tokens": 151,
                        },
                    }
                ).encode()
            )

    monkeypatch.setattr(urllib.request, "build_opener", lambda *_: Opener())
    with Store(tmp_path / "wire.sqlite") as store:
        run, _, request = prepared(store)
        gen = GenerationService(store, OpenAIChat(config, secret, authorized=True))
        a = gen.submit(run, "p08-openai-mocked", request)
        record = gen.execute("p08-openai-mocked")["actions"][0]
        assert (
            len(captured) == 1
            and set(json.loads(captured[0]["messages"][-1]["content"])) == USER_FIELDS
        )
        attempt = store.one("SELECT * FROM attempts WHERE task_id=?", (a["task_id"],))
        if scenario == "stop":
            assert record["result"]["generation_status"] == "generated"
        else:
            assert not (record["result"] or {}).get("candidate")
        if scenario == "uncertain":
            assert attempt["status"] == "uncertain" and attempt["response"] is None
        else:
            response = json.loads(attempt["response"])
            assert response["provider_usage"]["completion_tokens_details"]["reasoning_tokens"] == 7
        gen.execute("p08-openai-mocked", recover=True)
        assert len(captured) == 1 and secret not in "\n".join(store.db.iterdump())


def test_same_seed_different_packet_cannot_borrow_readiness(tmp_path):
    with Store(tmp_path / "different-packet.sqlite") as store:
        run, background, request = prepared(store)
        other_packet = HELPERS["perform"](background, run, "P05", {"seed_id": request["seed_id"]})
        request["packet_ref"] = other_packet["request_id"]
        with pytest.raises(ValueError, match="exact frozen packet"):
            GenerationService(store, Capture()).submit(run, "different-packet-generation", request)


def test_frozen_config_and_mode_cannot_be_changed_during_recovery(tmp_path):
    class Changed(Capture):
        def public_config(self):
            return {**super().public_config(), "fixture_version": "changed"}

    with Store(tmp_path / "frozen.sqlite") as store:
        run, _, request = prepared(store)
        service = GenerationService(store, Capture())
        service.submit(run, "frozen-p08-input", request)
        with pytest.raises(ValueError, match="different input"):
            service.submit(run, "frozen-p08-input", {**request, "mode": "ASSUMPTION_STRUCTURED"})
        with pytest.raises(ValueError, match="frozen model"):
            GenerationService(store, Changed()).execute("frozen-p08-input")
        assert not store.rows(
            "SELECT * FROM attempts WHERE task_id=?", (service.actions(run)[0]["task_id"],)
        )


def test_sibling_candidate_and_later_draft_cannot_enter_input(tmp_path):
    with Store(tmp_path / "isolation.sqlite") as store:
        run, _, request = prepared(store)
        adapter = Capture()
        gen = GenerationService(store, adapter)
        first = gen.submit(run, "first-isolated-candidate", request)
        gen.execute("first-isolated-candidate")
        original = json.loads(first["input"])
        snapshot = store.run(run)
        store.revise_brief(
            snapshot["project_id"],
            {"question": "Later unrelated draft; never use this in fixed Run"},
            snapshot["revision_id"],
        )
        second = gen.submit(
            run,
            "second-isolated-candidate",
            {**request, "mode": "ASSUMPTION_STRUCTURED", "candidate_id": "second-identity"},
        )
        payload = json.loads(second["input"])
        assert payload == {
            **original,
            "mode": "ASSUMPTION_STRUCTURED",
            "candidate_id_from_caller": "second-identity",
        }
        assert request["candidate_id"] not in encode(payload)
