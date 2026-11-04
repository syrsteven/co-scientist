"""M12 mechanical sequence only; modules own interpretation of their results."""

import json

from .calls import TaskCalls
from .contracts import Module, ModuleResult, TaskInput, UncertainCall
from .store import encode


class Registry:
    def __init__(self):
        self._modules: dict[str, Module] = {}

    def register(self, name: str, module: Module):
        if name in self._modules:
            raise ValueError(f"Module already registered: {name}")
        self._modules[name] = module

    def get(self, name: str) -> Module:
        return self._modules[name]


class Scheduler:
    def __init__(self, store, registry):
        self.store, self.registry = store, registry

    def step(self, run_id: str) -> bool:
        """Execute at most one Task. Returns False for a terminal/blocked Run."""
        store = self.store
        if store.run(run_id)["status"] not in ("ready", "running"):
            return False
        task = store.one(
            "SELECT * FROM tasks WHERE run_id=? AND status='ready' ORDER BY step LIMIT 1", (run_id,)
        )
        with store.db:
            store.db.execute("UPDATE tasks SET status='running' WHERE id=?", (task["id"],))
            store.db.execute("UPDATE runs SET status='running' WHERE id=?", (run_id,))
            store.fact(task["id"], "task_started", {"module": task["module"]})
        try:
            result = self.registry.get(task["module"])(
                TaskInput(**json.loads(task["input"])),
                TaskCalls(store, task["id"]),
            )
            if not isinstance(result, ModuleResult):
                raise TypeError("Module must return ModuleResult")
            if task["module"] in ("goal.prepare.v1", "goal.screen.v1"):
                from .goal import goal_route

                stop, context = goal_route(task["module"], result.output)
                store.submit_result(
                    task["id"], result.output, stop_status=stop, goal_context=context
                )
            elif task["module"] in ("literature.search.v1", "literature.fetch.v1"):
                from .literature_runtime import literature_route

                store.submit_result(
                    task["id"], result.output, stop_status=literature_route(result.output)
                )
            elif task["module"] == "generation.P08":
                from .generation import generation_route

                store.submit_result(
                    task["id"], result.output, stop_status=generation_route(result.output)
                )
            elif task["module"].startswith("background."):
                from .background import background_route

                store.submit_result(
                    task["id"], result.output, stop_status=background_route(result.output)
                )
            else:
                store.submit_result(task["id"], result.output)
        except Exception as exc:  # noqa: BLE001 -- module boundary persists failure facts
            status = "blocked" if isinstance(exc, UncertainCall) else "failed"
            error = {"type": type(exc).__name__, "message": str(exc), "module": task["module"]}
            with store.db:
                store.db.execute(
                    "UPDATE tasks SET status=?,error=? WHERE id=?",
                    (status, encode(error), task["id"]),
                )
                store.db.execute("UPDATE runs SET status=? WHERE id=?", (status, run_id))
                store.fact(task["id"], "task_error", error)
            return False
        return True

    def run(self, run_id):
        while self.step(run_id):
            pass
        return self.store.run(run_id)["status"]
