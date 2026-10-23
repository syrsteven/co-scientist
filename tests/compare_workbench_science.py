"""Explicit synthetic before/after experiment, run once under each source tree.

Shared immutable manifest and deterministic call IDs are fixture inputs only.
No historical Run, code-identity check or production configuration is changed.
Usage: python tests/compare_workbench_science.py SHARED_DIR baseline|patched
"""

import asyncio
import json
import socket
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from co_scientist.release import service as release
from co_scientist.runtime.core_runner import CoreRunner


def deny(*args, **kwargs):
    raise AssertionError("comparison fixture denies all real sockets")


async def main():
    folder, name = Path(sys.argv[1]), sys.argv[2]
    folder.mkdir(parents=True, exist_ok=True)
    socket.socket.connect = socket.socket.connect_ex = deny
    native = release.RunService(environment={})
    shared = folder / "frozen-manifest.json"
    goal = folder / "goal.json"
    if not shared.exists():
        goal.write_text(json.dumps({"title": "Controlled synthetic comparison",
            "goal": "Distinguish reversible synthetic stress from persistent functional impairment.",
            "required_causal_chain": ["stress", "recovery"],
            "required_outputs": ["prediction", "falsifier"]}))
        shared.write_text(json.dumps(native.validate(goal)))
    manifest = json.loads(shared.read_bytes())
    native.validate = lambda *args, **kwargs: manifest
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 23, tzinfo=UTC)
    release.datetime = Clock
    release.uuid4 = lambda: SimpleNamespace(hex="1234567890abcdef1234567890abcdef")
    compose = CoreRunner._compose
    def deterministic(self, *args, **kwargs):
        compose(self, *args, **kwargs)
        self.worker.call_id_factory = lambda task: f"call:{task.task_id}:{task.attempt}:controlled"
    CoreRunner._compose = deterministic
    root = Path(native.create(goal, folder / name, mock=True)["run_root"])
    native.authorize(root, confirm=True, accept_usd="60")
    result = await native.execute(root)
    assert result["state"] == "completed", result
    documents = {f.name: json.loads(f.read_bytes()) for f in (root / "exports").glob("*.json")}
    events = documents["run-timeline.json"]["events"]
    keep = {"HypothesisContentCreated": ["hypothesis_id", "title", "claim", "mechanism_chain",
            "assumptions", "predictions", "falsifiers", "scientific_parent_ids", "generation_index", "content_hash"],
        "MatchEvaluated": ["match_id", "left_id", "right_id", "decision", "winner_id"],
        "BayesianRatingProjected": ["hypothesis_id", "match_id", "mu", "sigma"],
        "BaselineReproductionPlannedV1": ["generation", "slot_id", "decision"],
        "IdeationFinalSelectionV1": ["execution_result", "selection_result", "winner_id",
            "winner_content_hash", "eligible_pool_ids", "terminal_barrier_complete"]}
    summary = {"events": [{"sequence": e["sequence"], "type": e["event_type"],
                "payload": {k: e["payload"].get(k) for k in keep[e["event_type"]]}}
                for e in events if e["event_type"] in keep],
        "costs": sorted(c["cost_usd"] for c in documents["run-timeline.json"]["cost_entries"]),
        "event_types": [e["event_type"] for e in events]}
    (folder / f"{name}-science.json").write_text(json.dumps(summary, indent=2))
    print(name, result["state"], result["final"]["winner_id"], len(events))


if __name__ == "__main__":
    asyncio.run(main())
