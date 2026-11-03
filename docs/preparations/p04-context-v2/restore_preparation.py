"""Restore only to a new local file; no network, credentials or execution."""

import argparse
import gzip
import hashlib
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    expected = next(
        line.split("  ", 1)[0]
        for line in (here / "SHA256SUMS").read_text().splitlines()
        if line.endswith("  prepared.sqlite.gz")
    )
    packed = (here / "prepared.sqlite.gz").read_bytes()
    if hashlib.sha256(packed).hexdigest() != expected:
        parser.error("Snapshot SHA256 mismatch")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with args.output.open("xb") as destination:
            destination.write(gzip.decompress(packed))
    except FileExistsError:
        parser.error("Output exists; never overwrite an existing Brief/Run/database")
    print("Restored new independent preparation DB; no tasks executed")


if __name__ == "__main__":
    main()
