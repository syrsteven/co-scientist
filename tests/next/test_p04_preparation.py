"""Audit actual saved public materials without any network or model execution."""

import hashlib
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "docs/preparations/p04-context-v2"


def test_preparation_export_is_clean_and_offline():
    before = hashlib.sha256((PACKAGE / "prepared.sqlite.gz").read_bytes()).hexdigest()
    checked = subprocess.run(
        [sys.executable, str(PACKAGE / "verify_preparation.py")],
        env={**os.environ, "OPENAI_API_KEY": "", "DEEPSEEK_API_KEY": ""},
        capture_output=True,
        text=True,
        check=True,
    )
    assert "model sends=0" in checked.stdout
    assert hashlib.sha256((PACKAGE / "prepared.sqlite.gz").read_bytes()).hexdigest() == before


def test_restore_cannot_overwrite_an_existing_run_database(tmp_path):
    path = tmp_path / "fresh.sqlite"
    command = [sys.executable, str(PACKAGE / "restore_preparation.py"), "--output", str(path)]
    subprocess.run(command, check=True, capture_output=True, text=True)
    before = path.read_bytes()
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    assert result.returncode != 0 and "never overwrite" in result.stderr
    assert path.read_bytes() == before
