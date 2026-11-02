"""Run via PYTHONPATH=src python -m co_scientist_next; no API keys required."""

import argparse
import json
import os

from .demo import create_demo, registry
from .scheduler import Scheduler
from .store import Store


def main():
    parser = argparse.ArgumentParser(description="W0 deterministic engineering demo (no science)")
    parser.add_argument("--db", required=True)
    parser.add_argument("--run-id", help="Resume an existing demo Run")
    parser.add_argument("--steps", type=int, help="Stop after this many Tasks; default: finish")
    args = parser.parse_args()
    if args.steps is not None and args.steps < 0:
        parser.error("--steps must be nonnegative")
    with Store(args.db) as store:
        store.recover()
        run_id = args.run_id or create_demo(store)
        scheduler = Scheduler(store, registry())
        count = 0
        while args.steps is None or count < args.steps:
            if not scheduler.step(run_id):
                break
            count += 1
        tasks = store.tasks(run_id)
        print(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "run_id": run_id,
                    "status": store.run(run_id)["status"],
                    "tasks": [
                        {
                            "id": t["id"],
                            "step": t["step"],
                            "module": t["module"],
                            "status": t["status"],
                        }
                        for t in tasks
                    ],
                    "results": store.rows(
                        """SELECT r.* FROM results r JOIN tasks t ON t.id=r.task_id
                                    WHERE t.run_id=? ORDER BY t.step""",
                        (run_id,),
                    ),
                    "usage": store.usage(run_id=run_id),
                    "engineering_fixture": True,
                },
                sort_keys=True,
            )
        )
        return 0 if store.run(run_id)["status"] in ("ready", "completed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
