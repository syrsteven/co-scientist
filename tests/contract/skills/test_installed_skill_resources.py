from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

from co_scientist.skills.loader import CORE_SKILL_CONTRACTS, core_skill_directory, load_skill

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
RESOURCE_MEMBERS = {
    f"co_scientist/skills/resources/{skill_id}/{relative_path}"
    for skill_id in CORE_SKILL_CONTRACTS
    for relative_path in ("manifest.yaml", "prompts/system.md")
}


def _resource_hashes() -> dict[str, str]:
    hashes: dict[str, str] = {}
    for skill_id in CORE_SKILL_CONTRACTS:
        directory = core_skill_directory(skill_id)
        load_skill(directory)
        for relative_path in ("manifest.yaml", "prompts/system.md"):
            hashes[f"{skill_id}/{relative_path}"] = hashlib.sha256(
                (directory / relative_path).read_bytes()
            ).hexdigest()
    return hashes


# Mutation caught: resolving skills from a source-checkout-relative top-level directory
# that is absent from a normal wheel and therefore breaks the installed CLI.
def test_non_editable_wheel_ships_and_resolves_the_canonical_skill_catalog(
    tmp_path: Path,
) -> None:
    distribution_dir = tmp_path / "dist"
    installed_dir = tmp_path / "installed"
    operator_dir = tmp_path / "outside-repository"
    distribution_dir.mkdir()
    installed_dir.mkdir()
    operator_dir.mkdir()
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONPATH", "PYTHONHOME"}
    }
    subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--no-isolation",
            "--skip-dependency-check",
            "--outdir",
            str(distribution_dir),
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(distribution_dir.glob("*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        wheel_resources = {
            member
            for member in archive.namelist()
            if member.startswith("co_scientist/skills/resources/")
        }
        assert wheel_resources == RESOURCE_MEMBERS
        assert len(wheel_resources) == 12

    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-index",
            "--no-deps",
            "--target",
            str(installed_dir),
            str(wheel),
        ],
        cwd=operator_dir,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    probe = """
import hashlib
import json
import pathlib
import sys

sys.path.insert(0, sys.argv[1])
import co_scientist.skills.loader as loader_module
from co_scientist.skills.loader import CORE_SKILL_CONTRACTS, core_skill_directory, load_skill

installed_root = pathlib.Path(sys.argv[1]).resolve()
assert pathlib.Path(loader_module.__file__).resolve().is_relative_to(installed_root)
result = {}
for skill_id in CORE_SKILL_CONTRACTS:
    directory = core_skill_directory(skill_id)
    load_skill(directory)
    for relative_path in ("manifest.yaml", "prompts/system.md"):
        result[f"{skill_id}/{relative_path}"] = hashlib.sha256(
            (directory / relative_path).read_bytes()
        ).hexdigest()
print(json.dumps(result, sort_keys=True))
"""
    completed = subprocess.run(
        [sys.executable, "-c", probe, str(installed_dir)],
        cwd=operator_dir,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout) == _resource_hashes()
