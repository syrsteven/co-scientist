from __future__ import annotations

import asyncio
import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select, update

from co_scientist.adapters.artifacts.filesystem import FilesystemArtifactStore
from co_scientist.adapters.persistence.sqlite import (
    BudgetReservationRow,
    EventRow,
    ExternalCallRow,
    RunRow,
    SqliteUnitOfWork,
    TaskRow,
)
from co_scientist.application.config import resolve_run_config
from co_scientist.export.run_export import (
    SqliteRunReadModel,
    export_run,
    verify_core_release_invariants,
)
from co_scientist.runtime.checkpoints import ConvergenceCheckpointBuilder
from co_scientist.runtime.core_runner import CoreRunner
from tests.core_preview_support import write_core_preview_inputs
from tests.smoke.test_lens_replay_smoke import GOAL, PROFILE, _invoke_cli


@dataclass(frozen=True)
class PersistedReleaseRun:
    run_id: str
    data_dir: Path
    uow: SqliteUnitOfWork
    artifacts: FilesystemArtifactStore

    def verify(self):
        return verify_core_release_invariants(self.run_id, SqliteRunReadModel(self.uow))


@pytest.fixture(scope="module")
def release_seed(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, str]:
    root = tmp_path_factory.mktemp("core-release-seed")
    operator_cwd = root / "operator"
    operator_cwd.mkdir()
    data_dir = root / "data"
    executed = _invoke_cli(
        operator_cwd,
        "run",
        "execute",
        "--goal",
        str(GOAL),
        "--profile",
        str(PROFILE),
        "--provider",
        "replay",
        "--data-dir",
        str(data_dir),
    )
    assert executed.returncode == 0, executed.stderr
    result = json.loads(executed.stdout)
    assert result["state"] == "completed"
    return data_dir, str(result["run_id"])


@pytest.fixture
def release_run(
    tmp_path: Path,
    release_seed: tuple[Path, str],
) -> PersistedReleaseRun:
    source, run_id = release_seed
    data_dir = tmp_path / "data"
    shutil.copytree(source, data_dir)
    return PersistedReleaseRun(
        run_id=run_id,
        data_dir=data_dir,
        uow=SqliteUnitOfWork(f"sqlite:///{data_dir / 'co-scientist.db'}"),
        artifacts=FilesystemArtifactStore(data_dir / "artifacts"),
    )


def _insert_stop_signal(
    release_run: PersistedReleaseRun,
    *,
    sequence: int,
    checkpoint_id: str,
    action: str,
) -> None:
    with release_run.uow.session_factory.begin() as session:
        session.execute(
            update(EventRow)
            .where(
                EventRow.run_id == release_run.run_id,
                EventRow.sequence >= sequence,
            )
            .values(sequence=EventRow.sequence + 1000)
        )
        session.execute(
            update(EventRow)
            .where(
                EventRow.run_id == release_run.run_id,
                EventRow.sequence >= sequence + 1000,
            )
            .values(sequence=EventRow.sequence - 999)
        )
        run = session.get(RunRow, release_run.run_id)
        assert run is not None
        run.current_sequence += 1
        session.add(
            EventRow(
                run_id=release_run.run_id,
                sequence=sequence,
                event_type="StopSignalObserved",
                schema_version=1,
                payload_json=json.dumps(
                    {"action": action, "checkpoint_id": checkpoint_id},
                    sort_keys=True,
                ),
                occurred_at=datetime.now(UTC),
                causation_id=None,
                correlation_id=None,
            )
        )


# Mutation caught: defaulting release certification to success without inspecting
# persisted task, lease, reservation, stopping, projection, and scientific evidence.
def test_core_release_invariants_are_zero_for_the_cli_replay(
    release_run: PersistedReleaseRun,
) -> None:
    report = release_run.verify()

    assert report.persisted_task_count > 0
    assert report.external_call_count > 0
    assert report.match_count == 6
    assert report.violation_count == 0


def _bootstrapped_runner(tmp_path: Path, *, run_id: str) -> tuple[CoreRunner, int]:
    goal_file, profile_file, environment = write_core_preview_inputs(tmp_path)
    config = resolve_run_config(
        goal_file=goal_file,
        profile_file=profile_file,
        provider="replay",
        environment=environment,
    )
    runner = CoreRunner(data_dir=tmp_path / "data", environment=environment)
    started = runner.supervisor.bootstrap_run(
        run_id=run_id,
        manifest=config.model_dump(mode="json")["manifest"],
    )
    return runner, started.last_sequence


# Mutation caught: tightening the verifier so far that the production scientist
# soft-stop -> finalization path can no longer certify.
def test_release_report_accepts_production_soft_stop_path(tmp_path: Path) -> None:
    runner, sequence = _bootstrapped_runner(tmp_path, run_id="release-soft-stop")
    runner.supervisor.request_soft_stop(
        "release-soft-stop", expected_sequence=sequence
    )
    asyncio.run(runner.resume(run_id="release-soft-stop"))

    report = verify_core_release_invariants(
        "release-soft-stop", SqliteRunReadModel(runner.uow)
    )

    assert report.stop_without_valid_checkpoint_count == 0


# Mutation caught: treating every hard-cancel signal as contradictory even when it is
# immediately followed by the production cancellation terminal.
def test_release_report_accepts_production_hard_cancel_path(tmp_path: Path) -> None:
    runner, sequence = _bootstrapped_runner(tmp_path, run_id="release-hard-cancel")
    recorded = ConvergenceCheckpointBuilder(
        runner.uow
    )._build_and_record_scientist_stop(
        run_id="release-hard-cancel", expected_sequence=sequence
    )
    runner.supervisor.tick(
        run_id="release-hard-cancel",
        expected_sequence=recorded.commit.last_sequence,
        checkpoint_id=recorded.checkpoint_id,
        scientist_action="hard_cancel",
    )

    report = verify_core_release_invariants(
        "release-hard-cancel", SqliteRunReadModel(runner.uow)
    )

    assert report.stop_without_valid_checkpoint_count == 0


@pytest.mark.parametrize("action", ["hard_cancel", "soft_stop"])
# Mutation caught: accepting a scientist signal after the finalization decision and
# request merely because its checkpoint exists earlier in the Run.
def test_release_report_rejects_stop_signals_after_finalization_request(
    release_run: PersistedReleaseRun,
    action: str,
) -> None:
    events = SqliteRunReadModel(release_run.uow).events(release_run.run_id)
    trigger = next(event for event in events if event["event_type"] == "StopPolicyTriggered")
    requested = next(
        event for event in events if event["event_type"] == "FinalizationRequested"
    )
    _insert_stop_signal(
        release_run,
        sequence=int(requested["sequence"]) + 1,
        checkpoint_id=str(trigger["payload"]["checkpoint_id"]),
        action=action,
    )

    report = release_run.verify()

    assert report.stop_without_valid_checkpoint_count > 0
    assert report.violation_count > 0


@pytest.mark.parametrize("action", ["unsupported_stop", "hard_cancel"])
# Mutation caught: accepting an unsupported signal or a cancellation action as the
# preface to a policy-triggered finalization path.
def test_release_report_rejects_actions_that_contradict_finalization(
    release_run: PersistedReleaseRun,
    action: str,
) -> None:
    events = SqliteRunReadModel(release_run.uow).events(release_run.run_id)
    trigger = next(event for event in events if event["event_type"] == "StopPolicyTriggered")
    _insert_stop_signal(
        release_run,
        sequence=int(trigger["sequence"]),
        checkpoint_id=str(trigger["payload"]["checkpoint_id"]),
        action=action,
    )

    report = release_run.verify()

    assert report.stop_without_valid_checkpoint_count > 0
    assert report.violation_count > 0


# Mutation caught: treating a signal as source-bound merely because some valid
# checkpoint exists earlier in the Run, even though its own checkpoint ID does not.
def test_release_report_rejects_signal_bound_to_a_different_checkpoint(
    release_run: PersistedReleaseRun,
) -> None:
    events = SqliteRunReadModel(release_run.uow).events(release_run.run_id)
    trigger = next(event for event in events if event["event_type"] == "StopPolicyTriggered")
    _insert_stop_signal(
        release_run,
        sequence=int(trigger["sequence"]),
        checkpoint_id="different-checkpoint",
        action="soft_stop",
    )

    report = release_run.verify()

    assert report.stop_without_valid_checkpoint_count > 0
    assert report.violation_count > 0


@pytest.mark.parametrize(
    ("violation", "counter"),
    [
        ("stale_lease", "stale_lease_accepted_count"),
        ("forged_lease_fingerprint", "stale_lease_accepted_count"),
        ("call_without_reservation", "external_call_without_reservation_count"),
        ("oversubscribed_reservation", "invalid_budget_reservation_count"),
        ("stop_without_checkpoint", "stop_without_valid_checkpoint_count"),
        ("stop_wrong_source_sequence", "stop_without_valid_checkpoint_count"),
        ("unrecoverable_stopping", "unrecoverable_stopping_count"),
        ("terminal_mutation", "terminal_mutation_count"),
        ("projection_mismatch", "projection_mismatch_count"),
        ("bootstrap_epoch_bypass", "bootstrap_epoch_bypass_count"),
        ("non_decisive_rating", "non_decisive_rating_update_count"),
        ("cross_epoch_match", "cross_epoch_elo_comparison_count"),
        ("proximity_novelty", "proximity_derived_novelty_count"),
    ],
)
# Mutations caught: accepting any named release-integrity violation merely because
# the public API would reject creating it. Each case corrupts durable state below
# that boundary and proves the independent release report becomes nonzero.
def test_release_report_detects_real_persisted_negative_controls(
    release_run: PersistedReleaseRun,
    violation: str,
    counter: str,
) -> None:
    uow = release_run.uow
    with uow.session_factory.begin() as session:
        events = session.scalars(
            select(EventRow)
            .where(EventRow.run_id == release_run.run_id)
            .order_by(EventRow.sequence)
        ).all()
        if violation == "stale_lease":
            call = session.scalar(
                select(ExternalCallRow).where(ExternalCallRow.run_id == release_run.run_id)
            )
            assert call is not None
            call.attempt = 0
        elif violation == "forged_lease_fingerprint":
            call = session.scalar(
                select(ExternalCallRow).where(ExternalCallRow.run_id == release_run.run_id)
            )
            assert call is not None
            context = json.loads(call.execution_context_json or "{}")
            context["lease_fence_fingerprint"] = "sha256:" + "f" * 64
            call.execution_context_json = json.dumps(context, sort_keys=True)
        elif violation == "call_without_reservation":
            call = session.scalar(
                select(ExternalCallRow).where(ExternalCallRow.run_id == release_run.run_id)
            )
            assert call is not None
            context = json.loads(call.execution_context_json or "{}")
            context.pop("reservation_id", None)
            call.execution_context_json = json.dumps(context, sort_keys=True)
        elif violation == "oversubscribed_reservation":
            reservation = session.scalar(
                select(BudgetReservationRow).where(
                    BudgetReservationRow.run_id == release_run.run_id,
                    BudgetReservationRow.state == "settled",
                )
            )
            assert reservation is not None
            reservation.actual_model_calls = 41
        elif violation == "stop_without_checkpoint":
            event = next(item for item in events if item.event_type == "StopPolicyTriggered")
            payload = json.loads(event.payload_json)
            payload["checkpoint_id"] = "missing-checkpoint"
            event.payload_json = json.dumps(payload, sort_keys=True)
        elif violation == "stop_wrong_source_sequence":
            event = next(item for item in events if item.event_type == "StopPolicyTriggered")
            payload = json.loads(event.payload_json)
            payload["checkpoint_source_sequence"] = int(
                payload["checkpoint_source_sequence"]
            ) - 1
            event.payload_json = json.dumps(payload, sort_keys=True)
        elif violation == "unrecoverable_stopping":
            requested = next(item for item in events if item.event_type == "FinalizationRequested")
            task = session.get(TaskRow, json.loads(requested.payload_json)["task_id"])
            assert task is not None
            task.intent_type = "run_generation"
        elif violation == "terminal_mutation":
            terminal = next(
                item
                for item in reversed(events)
                if item.event_type in {"RunCompleted", "RunCompletedPartial"}
            )
            run = session.get(RunRow, release_run.run_id)
            assert run is not None
            session.add(
                EventRow(
                    run_id=release_run.run_id,
                    sequence=terminal.sequence + 1,
                    event_type="StopSignalObserved",
                    schema_version=1,
                    payload_json=json.dumps(
                        {"action": "soft_stop", "checkpoint_id": "after-terminal"},
                        sort_keys=True,
                    ),
                    occurred_at=datetime.now(UTC),
                    causation_id=None,
                    correlation_id=None,
                )
            )
            run.current_sequence = terminal.sequence + 1
        elif violation == "projection_mismatch":
            run = session.get(RunRow, release_run.run_id)
            assert run is not None
            run.state = "running"
        elif violation == "bootstrap_epoch_bypass":
            event = next(item for item in events if item.event_type == "TaskEnqueued")
            payload = json.loads(event.payload_json)
            payload["created_by"] = "agent"
            event.payload_json = json.dumps(payload, sort_keys=True)
        elif violation == "non_decisive_rating":
            event = next(item for item in events if item.event_type == "MatchEvaluated")
            payload = json.loads(event.payload_json)
            payload["decision"] = "inconclusive"
            payload["winner_id"] = None
            event.payload_json = json.dumps(payload, sort_keys=True)
        elif violation == "cross_epoch_match":
            event = next(item for item in events if item.event_type == "MatchEvaluated")
            payload = json.loads(event.payload_json)
            payload["epoch_id"] = "epoch-not-opened"
            event.payload_json = json.dumps(payload, sort_keys=True)
        elif violation == "proximity_novelty":
            proximity = next(
                item
                for item in events
                if item.event_type == "ProximityAssessed"
                and json.loads(item.payload_json).get("source_result_id") is not None
            )
            novelty = next(
                item for item in events if item.event_type == "NoveltyAssessmentRecorded"
            )
            payload = json.loads(novelty.payload_json)
            payload["assessment_id"] = "proximity-derived-novelty"
            payload["source_result_id"] = json.loads(proximity.payload_json)[
                "source_result_id"
            ]
            terminal = events[-1]
            run = session.get(RunRow, release_run.run_id)
            assert run is not None
            session.add(
                EventRow(
                    run_id=release_run.run_id,
                    sequence=terminal.sequence + 1,
                    event_type="NoveltyAssessmentRecorded",
                    schema_version=novelty.schema_version,
                    payload_json=json.dumps(payload, sort_keys=True),
                    occurred_at=datetime.now(UTC),
                    causation_id=None,
                    correlation_id=None,
                )
            )
            run.current_sequence = terminal.sequence + 1
        else:  # pragma: no cover - parameterization is exhaustive
            raise AssertionError(violation)

    report = release_run.verify()

    assert getattr(report, counter) > 0
    assert report.violation_count > 0


# Mutation caught: trusting a raw manifest and database call independently instead
# of requiring exact cross-binding before exporting a scientific evidence bundle.
def test_export_rejects_a_real_persisted_raw_artifact_call_mismatch(
    release_run: PersistedReleaseRun,
    tmp_path: Path,
) -> None:
    call = SqliteRunReadModel(release_run.uow).external_calls(release_run.run_id)[0]
    manifest = release_run.artifacts.discover_raw(call["external_call_id"])
    assert manifest is not None
    manifest_path = release_run.artifacts.root / (
        str(manifest.artifact_ref.path) + ".manifest.json"
    )
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    document["provider_response_id"] = "forged-provider-response"
    manifest_path.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")

    with pytest.raises(ValueError, match="raw manifest.*persisted call"):
        export_run(
            release_run.run_id,
            tmp_path / "forged-export",
            SqliteRunReadModel(release_run.uow),
            release_run.artifacts,
        )


@pytest.mark.parametrize(
    "state",
    [
        "raw_response_persisted",
        "validated",
        "agent_result_submitted",
        "domain_result_applied",
    ],
)
# Mutation caught: silently omitting mandatory raw evidence from a polished export.
def test_export_rejects_required_call_states_with_a_null_raw_reference(
    release_run: PersistedReleaseRun,
    tmp_path: Path,
    state: str,
) -> None:
    with release_run.uow.session_factory.begin() as session:
        call = session.scalar(
            select(ExternalCallRow).where(ExternalCallRow.run_id == release_run.run_id)
        )
        assert call is not None
        call.state = state
        call.raw_artifact_ref_json = None
    output = tmp_path / f"null-raw-{state}"

    with pytest.raises(ValueError, match="requires persisted raw evidence"):
        export_run(
            release_run.run_id,
            output,
            SqliteRunReadModel(release_run.uow),
            release_run.artifacts,
        )

    assert not output.exists()


# Mutation caught: treating a database ArtifactRef as sufficient when the referenced
# content-addressed body no longer exists.
def test_export_rejects_a_missing_raw_artifact_body(
    release_run: PersistedReleaseRun,
    tmp_path: Path,
) -> None:
    call = SqliteRunReadModel(release_run.uow).external_calls(release_run.run_id)[0]
    raw_ref = call["raw_artifact_ref"]
    assert isinstance(raw_ref, dict)
    body = release_run.artifacts.root / str(raw_ref["path"])
    body.rename(body.with_name(body.name + ".missing"))
    output = tmp_path / "missing-raw"

    with pytest.raises(FileNotFoundError):
        export_run(
            release_run.run_id,
            output,
            SqliteRunReadModel(release_run.uow),
            release_run.artifacts,
        )

    assert not output.exists()


# Mutation caught: accepting a valid artifact belonging to a different durable call.
def test_export_rejects_a_cross_call_raw_artifact_reference(
    release_run: PersistedReleaseRun,
    tmp_path: Path,
) -> None:
    calls = SqliteRunReadModel(release_run.uow).external_calls(release_run.run_id)
    assert len(calls) >= 2
    with release_run.uow.session_factory.begin() as session:
        call = session.get(ExternalCallRow, calls[0]["external_call_id"])
        assert call is not None
        call.raw_artifact_ref_json = json.dumps(calls[1]["raw_artifact_ref"], sort_keys=True)
    output = tmp_path / "cross-call-raw"

    with pytest.raises(ValueError, match="raw manifest.*persisted call"):
        export_run(
            release_run.run_id,
            output,
            SqliteRunReadModel(release_run.uow),
            release_run.artifacts,
        )

    assert not output.exists()


@pytest.mark.parametrize("state", ["planned", "started"])
# Mutation caught: requiring raw evidence before a provider response can exist.
def test_export_keeps_partial_pre_response_call_states_honest(
    release_run: PersistedReleaseRun,
    tmp_path: Path,
    state: str,
) -> None:
    with release_run.uow.session_factory.begin() as session:
        call = session.scalar(
            select(ExternalCallRow).where(ExternalCallRow.run_id == release_run.run_id)
        )
        assert call is not None
        call.state = state
        call.raw_artifact_ref_json = None
        call.validated_artifact_ref_json = None
        call.agent_result_id = None
        call.agent_result_json = None
        call.applied_domain_sequence = None
        call.provider_response_id = None
        call.usage_json = "{}"
    output = tmp_path / f"partial-{state}"

    export_run(
        release_run.run_id,
        output,
        SqliteRunReadModel(release_run.uow),
        release_run.artifacts,
    )

    exported = json.loads((output / "external_calls.json").read_text(encoding="utf-8"))
    partial = next(item for item in exported if item["state"] == state)
    assert partial["raw_artifact_ref"] is None
