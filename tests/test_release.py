"""Portable release tests: real adapters, denied sockets, synthetic HTTP only."""

import json
import socket
from pathlib import Path

import pytest

from co_scientist.release.resources import ASSETS, package_file, resource_path
from co_scientist.release.service import RunService, load

GOAL = {
    "title": "Synthetic stress mechanism",
    "goal": "Distinguish reversible responses from sustained functional impairment.",
    "required_causal_chain": ["stress", "signaling", "functional recovery"],
    "required_outputs": ["mechanism", "predictions", "falsifiers"],
}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("real socket forbidden in release acceptance")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)


def create(tmp_path, **kwargs):
    goal = tmp_path / "goal.json"
    goal.write_text(json.dumps(GOAL))
    service = RunService(environment={})
    value = service.create(goal, tmp_path / "runs", **kwargs)
    root = Path(value["run_root"])
    return service, root


def test_portable_profile_all_skill_schema_and_tokenizers():
    import hashlib

    from co_scientist.agents.payloads import resolve_output_schema
    from co_scientist.runtime.context_planning import deepseek_encoding, openai_encoding
    from co_scientist.skills.loader import (
        BASELINE_SEARCH_SKILL_CONTRACTS,
        BASELINE_SKILL_CONTRACTS,
        core_skill_directory,
        load_skill,
    )

    for (sid, version, phase), expected in {
        **BASELINE_SKILL_CONTRACTS,
        **BASELINE_SEARCH_SKILL_CONTRACTS,
    }.items():
        actual = load_skill(core_skill_directory(sid), skill_version=version, phase=phase)
        assert actual == expected
        assert resolve_output_schema(actual.output_schema, 1)
    for phase in ("QUERY_PLAN_V1", "SOURCE_REVIEW_V1"):
        assert load_skill(
            core_skill_directory("root_literature_review"), skill_version="0.4.0", phase=phase
        )
    assert load_skill(core_skill_directory("generation"), skill_version="0.4.0")
    for name, sha in ASSETS.items():
        assert hashlib.sha256(resource_path("resource:" + name).read_bytes()).hexdigest() == sha
    assert deepseek_encoding("resource:deepseek-v41.json", ASSETS["deepseek-v41.json"])
    assert openai_encoding("resource:o200k_base.tiktoken", ASSETS["o200k_base.tiktoken"]).encode(
        "非ASCII scientific input"
    )
    assert "/Users/" not in package_file("g3.yaml").read_text()


def test_packaged_core_and_all_51_skill_resources_match_successful_source():
    import hashlib

    import co_scientist

    root = Path(co_scientist.__file__).parent
    expected = load(package_file("source-files.json"))
    # The original successful-source index remains immutable. Exactly these
    # observational modules have explicit, independently versioned patch hashes.
    overlay = load(package_file("reliability-overlay-v0.1.1.json"))
    assert overlay["baseline_commit"] == "baa13351ec3cbea8a1e6e81cd4c1432377e315cf"
    assert set(overlay["modified"]) == {"application/cockpit.py", "runtime/ideation_trace.py"}
    assert set(overlay["added"]) == {"runtime/trace_snapshot.py"}
    # This branch explicitly patches stop finalization and crash-safe operator
    # files. Keep both historical manifests immutable; add an auditable overlay.
    workbench = load(package_file("workbench-reliability-v1.json"))
    assert workbench["baseline_commit"] == "a9a6934ce2c579d7302efe40a25c041c77a86d68"
    assert set(workbench["modified"]) == {"supervisor/orchestrator.py", "runtime/core_runner.py", "release/service.py"}
    for name, sha in expected.items():
        if name in overlay["modified"]:
            patch = overlay["modified"][name]
            assert patch["baseline_sha256"] == sha
            sha = patch["patched_sha256"]
        if name in workbench["modified"]:
            patch = workbench["modified"][name]
            assert patch["baseline_sha256"] == sha
            sha = patch["patched_sha256"]
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == sha, name
    for name, sha in overlay["added"].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == sha
    for name, patch in workbench["modified"].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == patch["patched_sha256"]
    skills = {
        str(p.relative_to(root)) for p in (root / "skills/resources").rglob("*") if p.is_file()
    }
    assert len(skills) == 51
    assert skills == {name for name in expected if name.startswith("skills/resources/")}


def test_missing_authorization_and_credentials_zero_dispatch(tmp_path):
    import asyncio

    service, root = create(tmp_path)
    with pytest.raises(FileNotFoundError):
        asyncio.run(service.execute(root))
    with pytest.raises(ValueError):
        service.authorize(root, confirm=True, accept_usd="60")
    service.authorize(
        root, confirm=True, accept_usd="60", accept_unknown_risk=True, confirm_pricing=True
    )
    with pytest.raises(ValueError, match="credentials"):
        asyncio.run(service.execute(root))
    assert not (root / "runtime").exists()


def test_credentials_not_frozen_and_authorization_not_transferable(tmp_path):
    import asyncio

    goal = tmp_path / "goal.json"
    goal.write_text(json.dumps(GOAL))
    service = RunService(
        environment={
            "OPENAI_API_KEY": "SECRET_SENTINEL_OPENAI",
            "DEEPSEEK_API_KEY": "SECRET_SENTINEL_DEEPSEEK",
            "CO_SCIENTIST_PUBMED_EMAIL": "researcher@example.org",
        }
    )
    one = Path(service.create(goal, tmp_path / "runs", mock=True)["run_root"])
    two = Path(service.create(goal, tmp_path / "runs", mock=True)["run_root"])
    auth = service.authorize(one, confirm=True, accept_usd="60")
    for path in one.glob("*.json"):
        assert "SECRET_SENTINEL" not in path.read_text()
    (two / "authorization.json").write_text(json.dumps(auth))
    with pytest.raises(ValueError, match="authorization identity"):
        asyncio.run(service.execute(two))
    assert not (two / "runtime").exists()


@pytest.mark.asyncio
async def test_long_g3_complete_trace_restart_replay(tmp_path):
    service, root = create(tmp_path, mock=True, long=True)
    service.authorize(root, confirm=True, accept_usd="60")
    await service.execute(root, steps=8)
    assert service.status(root)["state"] == "running"
    # New service/clients use frozen durable state, not mutable YAML defaults.
    service = RunService(environment={})
    result = await service.execute(root)
    assert result["state"] == "completed"
    final = result["final"]
    assert final["generation"] == 3 and final["execution_result"] == "COMPLETE"
    assert final["terminal_barrier_complete"] and final["selection_result"] == "FINAL_WINNER"
    files = {p.name for p in (root / "exports").iterdir()}
    assert files == {
        "run-timeline.json",
        "candidates.json",
        "ranking-history.json",
        "evolution-tree.json",
        "ideation-report.md",
    }
    cs = load(root / "exports/candidates.json")
    assert (
        len(cs) == 10
        and sorted(c["generation_index"] for c in cs) == [0] * 4 + [1] * 2 + [2] * 2 + [3] * 2
    )
    assert all(c["rating"]["decisive_matches"] >= 2 for c in cs)
    ranked = sorted(cs, key=lambda c: (-c["rating"]["mu"], c["hypothesis_id"]))
    assert ranked[0]["hypothesis_id"] == final["winner_id"]
    tree = load(root / "exports/evolution-tree.json")
    assert len(tree["reproduction"]) == 6
    assert all(
        p["ordered_critiques"]
        for e in tree["reproduction"]
        for p in e["exact_model_input"]["parents"]
    )
    timeline = load(root / "exports/run-timeline.json")
    assert (
        max(
            r["wire_ref"]["byte_length"]
            for r in timeline["requests"]
            if "match-" in r["permit"]["task_id"]
        )
        > 296588
    )
    assert max(e["generation"] for e in tree["reproduction"]) == 3
    count = len(timeline["dispatch_ledger"]["attempts"])
    assert count == len({a["id"] for a in timeline["dispatch_ledger"]["attempts"]})
    await service.execute(root)
    await service.export(root)
    again = load(root / "exports/run-timeline.json")
    assert len(again["dispatch_ledger"]["attempts"]) == count
    assert again["events"] == timeline["events"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["json", "length", "429", "unknown"])
async def test_retry_fault_restart_no_duplicate_application(tmp_path, failure):
    service, root = create(tmp_path, mock=True, failure=failure)
    service.authorize(root, confirm=True, accept_usd="60")
    await service.execute(root, steps=1)
    service = RunService(environment={})
    await service.execute(root, steps=1)
    events = service.events(root)
    assert sum(e["event_type"] == "DirectiveEthicsRecordedV1" for e in events) == 1
    assert sum(e["event_type"] == "ContinuousAttemptPreparedV1" for e in events) == 1
    timeline = load(service.export_path(root) / "run-timeline.json")
    calls = [c for c in timeline["calls"] if ":directive:" in c["task_id"]]
    assert len(calls) == 2 and calls[0]["external_call_id"] != calls[1]["external_call_id"]
    assert calls[0]["applied_domain_sequence"] is None
    assert calls[1]["applied_domain_sequence"] is not None
    if failure == "unknown":
        assert service.status(root)["accounting"]["actively_reserved"]["cost_usd"] != "0"


@pytest.mark.asyncio
async def test_stop_finalizes_partial_and_cannot_resume_science(tmp_path):
    service, root = create(tmp_path, mock=True)
    service.authorize(root, confirm=True, accept_usd="60")
    await service.execute(root, steps=2)
    before = load(service.export_path(root) / "run-timeline.json")["dispatch_ledger"]["attempts"]
    service.stop(root)
    result = await service.execute(root)
    assert result["state"] == "completed_partial" and result["final"]["winner_id"] is None
    after = load(root / "exports/run-timeline.json")["dispatch_ledger"]["attempts"]
    assert before == after
    await service.execute(root)
    assert service.status(root)["state"] == "completed_partial"


def test_manifest_or_mode_tamper_blocked(tmp_path):
    import asyncio

    service, root = create(tmp_path, mock=True)
    service.authorize(root, confirm=True, accept_usd="60")
    manifest = load(root / "manifest.json")
    manifest["goal"]["goal"] = "tampered"
    (root / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="identity"):
        asyncio.run(service.execute(root))
