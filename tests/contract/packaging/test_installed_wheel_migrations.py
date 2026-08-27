from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[3]


# Mutation caught: CoreRunner resolves Alembic from the source checkout, so a
# non-editable wheel cannot initialize an empty database outside the repository.
def test_installed_wheel_cli_upgrades_a_fresh_database_to_head(tmp_path: Path) -> None:
    wheel_dir = tmp_path / "wheel"
    target = tmp_path / "installed"
    operator_cwd = tmp_path / "operator"
    data_dir = operator_cwd / "data"
    wheel_dir.mkdir()
    target.mkdir()
    operator_cwd.mkdir()

    build = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            ".",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(wheel_dir),
        ],
        cwd=PROJECT_ROOT,
        env={**os.environ, "PIP_NO_INDEX": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert build.returncode == 0, build.stderr
    wheels = tuple(wheel_dir.glob("co_scientist_replica-*.whl"))
    assert len(wheels) == 1

    installed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--no-index",
            "--target",
            str(target),
            str(wheels[0]),
        ],
        cwd=operator_cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    assert installed.returncode == 0, installed.stderr

    inherited_pythonpath = os.environ.get("PYTHONPATH")
    pythonpath = str(target)
    if inherited_pythonpath:
        pythonpath = os.pathsep.join((pythonpath, inherited_pythonpath))
    invoked = subprocess.run(
        [
            sys.executable,
            "-c",
            "from co_scientist.cli.app import main; main()",
            "config",
            "check",
            "--data-dir",
            str(data_dir),
        ],
        cwd=operator_cwd,
        env={**os.environ, "PYTHONPATH": pythonpath},
        capture_output=True,
        text=True,
        check=False,
    )
    assert invoked.returncode == 0, invoked.stderr
    assert "schema=ready" in invoked.stdout
    assert str(target) in subprocess.check_output(
        [
            sys.executable,
            "-c",
            "import co_scientist; print(co_scientist.__file__)",
        ],
        cwd=operator_cwd,
        env={**os.environ, "PYTHONPATH": pythonpath},
        text=True,
    )

    with sqlite3.connect(data_dir / "co-scientist.db") as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    assert revision == ("0003_worker_leases_budget_reservations",)
