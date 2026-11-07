"""Read-only export of a proposed replacement Goal request; never sends or resumes."""

import argparse
import json
import sqlite3
from pathlib import Path

from co_scientist_next.goal_diagnostics import preparation_proposal


class ReadOnlyStore:
    def __init__(self, path):
        self.db = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
        self.db.row_factory = sqlite3.Row

    def one(self, sql, args):
        return dict(self.db.execute(sql, args).fetchone())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = preparation_proposal(ReadOnlyStore(args.db), args.run)
    with open(args.output, "x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, ensure_ascii=False, indent=2))
    Path(args.output).chmod(0o600)
    print("Unsent proposal exported. No database mutation or supplier request.")
