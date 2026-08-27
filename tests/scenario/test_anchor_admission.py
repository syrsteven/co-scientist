from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork
from co_scientist.application.config import resolve_run_config
from co_scientist.domain.review import ReviewPolicy
from co_scientist.events.reducers import replay_hypothesis
from co_scientist.ports.external_provider import thaw_json
from co_scientist.supervisor.orchestrator import Supervisor
from tests.core_preview_support import write_core_preview_inputs


def _resolved_manifest(tmp_path: Path) -> dict[str, object]:
    goal, profile, environment = write_core_preview_inputs(tmp_path)
    resolved = resolve_run_config(
        goal_file=goal,
        profile_file=profile,
        provider="replay",
        environment=environment,
    )
    return thaw_json(resolved.manifest)


@pytest.mark.parametrize("forgery", ["empty_evidence", "content_hash"])
# Mutations caught: callers supply an anchor verdict, omit evidence, or bind a
# frozen anchor identity to content other than its canonical HypothesisContent.
def test_bootstrap_rejects_forged_or_empty_anchor_evidence(
    tmp_path: Path, forgery: str
) -> None:
    manifest = deepcopy(_resolved_manifest(tmp_path))
    member = manifest["anchor_sets"][0]["members"][0]
    if forgery == "empty_evidence":
        member["evidence"] = {}
    else:
        member["content_hash"] = "sha256:" + "f" * 64
    uow = SqliteUnitOfWork(f"sqlite:///{tmp_path / f'{forgery}.db'}")
    uow.create_schema()

    with pytest.raises(ValueError, match="anchor"):
        Supervisor(
            uow=uow, review_policy=ReviewPolicy(profile_id="core-preview-test")
        ).bootstrap_run(run_id="run-anchor-invalid", manifest=manifest)

    with pytest.raises(KeyError):
        uow.run_state("run-anchor-invalid")


def test_valid_anchor_uses_evidence_reducer_and_replays_as_real_hypothesis(
    tmp_path: Path,
) -> None:
    manifest = _resolved_manifest(tmp_path)
    members = manifest["anchor_sets"][0]["members"]
    anchor = members[0]
    uow = SqliteUnitOfWork(f"sqlite:///{tmp_path / 'valid-anchor.db'}")
    uow.create_schema()
    supervisor = Supervisor(
        uow=uow, review_policy=ReviewPolicy(profile_id="core-preview-test")
    )
    bootstrapped = supervisor.bootstrap_run(run_id="run-anchor", manifest=manifest)

    content_events = [
        event
        for event in uow.load("run-anchor")
        if event.event_type == "HypothesisContentCreated"
    ]
    assert {event.payload["hypothesis_id"] for event in content_events} == {
        member["anchor_id"] for member in members
    }
    assert all(event.schema_version == 2 for event in content_events)
    outcome = supervisor.admit_hypothesis(
        run_id="run-anchor",
        hypothesis_id=anchor["anchor_id"],
        expected_sequence=bootstrapped.last_sequence,
        idempotency_key=f"admit:epoch-1:{anchor['anchor_id']}",
    )

    assert outcome.decision.admitted is True
    assert outcome.commit is not None
    ready = next(
        event
        for event in outcome.commit.events
        if event.event_type == "HypothesisTournamentReady"
    )
    assert ready.payload["content_hash"] == anchor["content_hash"]
    assert ready.payload["source_event_sequences"]
    assert len(ready.payload["review_ids"]) >= 2
    assert ready.payload["novelty_assessment_id"]
    assert ready.payload["proximity_edge_ids"]
    assert not ready.payload["missing_requirements"]
    assert not ready.payload["conflicting_evidence"]

    projection = replay_hypothesis(anchor["anchor_id"], uow.load("run-anchor"))
    assert projection.current_content_hash == anchor["content_hash"]
    assert projection.lifecycle_state == "tournament_active"
    assert projection.review_history
    assert projection.current_novelty_assessment_ids
    assert projection.proximity_history
    assert projection.tournament_entries_by_epoch["epoch-1"].content_hash == anchor[
        "content_hash"
    ]
