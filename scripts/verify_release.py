"""Verify the delivered source/package inventory without any network access."""

import hashlib
import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "SHA256SUMS.json").read_bytes())
    for relative, expected in manifest["files"].items():
        path = root / relative
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise SystemExit("MISMATCH: " + relative)
    print("PASS: " + str(len(manifest["files"])) + " files; no network used")


if __name__ == "__main__":
    main()
