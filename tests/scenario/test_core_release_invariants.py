from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from co_scientist.adapters.artifacts.filesystem import FilesystemArtifactStore
from co_scientist.adapters.persistence.sqlite import (
    BudgetReservationRow,
    EventRow,
    ExternalCallRow,
    RunRow,
    SqliteUnitOfWork,
    TaskRow,
)
from co_scientist.export.run_export import (
    SqliteRunReadModel,
    export_run,
    verify_core_release_invariants,
)
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


@pytest.mark.parametrize(
    ("violation", "counter"),
    [
        ("stale_lease", "stale_lease_accepted_count"),
        ("call_without_reservation", "external_call_without_reservation_count"),
        ("oversubscribed_reservation", "invalid_budget_reservation_count"),
        ("stop_without_checkpoint", "stop_without_valid_checkpoint_count"),
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
            reservation.estimated_model_calls = 41
        elif violation == "stop_without_checkpoint":
            event = next(item for item in events if item.event_type == "StopPolicyTriggered")
            payload = json.loads(event.payload_json)
            payload["checkpoint_id"] = "missing-checkpoint"
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
            proximity = next(item for item in events if item.event_type == "ProximityAssessed")
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
