"""Verify the delivered source/package inventory without any network access."""

import argparse
import hashlib
import json
from pathlib import Path


def verify(root, *, strict=False, manifest_name="SHA256SUMS.json"):
    root = Path(root).resolve()
    manifest = json.loads((root / manifest_name).read_bytes())
    for relative, expected in manifest["files"].items():
        path = root / relative
        if (
            path.is_symlink()
            or not path.resolve().is_relative_to(root)
            or not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != expected
        ):
            raise ValueError("MISMATCH: " + relative)
    if strict:
        actual = {
            str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() or p.is_symlink()
        }
        extra = actual - set(manifest["files"]) - {manifest_name}
        if extra:
            raise ValueError("UNLISTED: " + ", ".join(sorted(extra)))
    return len(manifest["files"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict", action="store_true", help="reject ALL unlisted files, including .git/cache"
    )
    parser.add_argument("--manifest", required=True, help="Explicit external build inventory")
    args = parser.parse_args()
    try:
        count = verify(
            Path(__file__).resolve().parents[1], strict=args.strict, manifest_name=args.manifest
        )
    except ValueError as error:
        raise SystemExit(str(error)) from None
    print(
        f"PASS: {count} indexed files; {'complete-directory' if args.strict else 'hash-only'}; no network used"
    )


if __name__ == "__main__":
    main()
