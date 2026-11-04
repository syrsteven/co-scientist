"""Export only a read-only P08 migration preview and complete unsent request."""

import argparse
import hashlib
import json
from pathlib import Path

from .generation_migration import MigrationService, ReadOnlyStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--proposal", required=True, help="Public migration identity/reference JSON"
    )
    parser.add_argument(
        "--model-config", required=True, help="Public Responses profile, never credentials"
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    database = Path(args.db).resolve()
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    with ReadOnlyStore(database) as store:
        preview = MigrationService(store, json.loads(Path(args.model_config).read_text())).preview(
            args.run_id, json.loads(Path(args.proposal).read_text())
        )
    after = hashlib.sha256(database.read_bytes()).hexdigest()
    if before != after:
        raise RuntimeError("Database changed during read-only preview; inspect concurrent writer")
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    values = {
        "preview.json": preview,
        "new.actual-request.json": preview["actual_submission"],
        "export-manifest.json": {
            "database_sha256_before": before,
            "database_sha256_after": after,
            "database_opened_readonly": True,
            "migration_applied": False,
            "model_requests": 0,
            "credentials_read": False,
            "science_validated": False,
            "preview_hash": preview["preview_hash"],
        },
    }
    for name, value in values.items():
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    (output / "SHA256SUMS").write_text(
        "".join(
            hashlib.sha256((output / name).read_bytes()).hexdigest() + "  " + name + "\n"
            for name in values
        )
    )
    print(json.dumps(values["export-manifest.json"], indent=2))


if __name__ == "__main__":
    main()
