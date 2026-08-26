from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from co_scientist.application.commands import ExecuteRun, ExportRun, RunCommand, RunWorker
from co_scientist.application.queries import GetRunStatus, ReplayRun

INVALID_RUN_IDS = [
    "",
    "/absolute",
    "segment/child",
    r"segment\child",
    ".",
    "..",
    "run..backup",
    " leading",
    "trailing ",
    "line\nbreak",
    "x" * 129,
]


def _requests(run_id: str) -> list[object]:
    return [
        ExecuteRun(
            goal_file=Path("goal.yaml"),
            profile_file=Path("profile.yaml"),
            provider="replay",
            run_id=run_id,
        ),
        RunWorker(run_id=run_id),
        RunCommand(run_id=run_id, expected_run_sequence=1, command="pause"),
        ExportRun(run_id=run_id, output=Path("export")),
        GetRunStatus(run_id=run_id),
        ReplayRun(run_id=run_id),
    ]


@pytest.mark.parametrize("run_id", INVALID_RUN_IDS)
# Mutation caught: accepting traversal, separators, whitespace/control, or unbounded IDs
# at any typed application boundary that addresses durable Run state.
def test_all_run_requests_reject_unsafe_identifiers(run_id: str) -> None:
    with pytest.raises(ValidationError, match="safe identifier"):
        _requests(run_id)


def test_all_run_requests_accept_one_stable_operator_identifier() -> None:
    requests = _requests("run.stable_2026-08-21")

    assert {request.run_id for request in requests} == {
        "run.stable_2026-08-21"
    }
