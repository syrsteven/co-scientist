"""Thin operator boundary around the unchanged scientific CoreRunner."""

import asyncio
import fcntl
import hashlib
import json
import os
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import httpx

from co_scientist.application.config import resolve_run_config
from co_scientist.domain.execution_config import ROLE_SCHEMAS
from co_scientist.domain.research_protocol import protocol_hash
from co_scientist.domain.single_root import FullIdeationConfig
from co_scientist.runtime.core_runner import CoreRunner
from co_scientist.runtime.ideation_trace import export_trace
from co_scientist.runtime.worker import WorkerStep

from .resources import package_file, resource_path


def load(path):
    return json.loads(Path(path).read_bytes())


def save_new(path, value):
    with Path(path).open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)


def code_identity():
    root = Path(__file__).parents[1]
    names = {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file()
        and "__pycache__" not in p.parts
        and p.suffix in {".py", ".json", ".yaml", ".md", ".txt"}
    }
    return protocol_hash(names)


def budget(manifest):
    config = FullIdeationConfig.model_validate(manifest["effective_execution_config"])
    import yaml

    reference = FullIdeationConfig.model_validate(
        yaml.safe_load(package_file("g3.yaml").read_text())["execution_runtime"]
    )
    if config != reference:
        raise ValueError("effective runtime differs from frozen release configuration")
    tasks = [config.task(s) for s in ROLE_SCHEMAS]
    initial = sum(
        Decimal(t["reserved_usd"]) * config.roles[t["role"]].max_dispatches for t in tasks
    )
    extra = sorted(
        [
            Decimal(t["reserved_usd"])
            for t in tasks
            for _ in range(2 * config.roles[t["role"]].max_dispatches)
        ],
        reverse=True,
    )[:24]
    return {
        "conservative_usd": str(initial + sum(extra)),
        "risk_ceiling_usd": str(config.envelope.max_reserved_usd),
        "model_dispatches": 143,
        "initial_dispatches": 119,
        "retry_dispatches": 24,
        "sol_dispatches": 24,
        "flash_dispatches": 135,
        "pubmed_http": 48,
        "external_http": 191,
        "watchdog_seconds": 7200,
    }


class RunService:
    """No scientific scheduler, score, result repair or API defaults live here."""

    def __init__(self, environment=None):
        self.environment = dict(os.environ if environment is None else environment)

    def validate(self, goal, profile=None):
        import yaml

        reference = yaml.safe_load(package_file("g3.yaml").read_text())
        if profile is not None and yaml.safe_load(Path(profile).read_text()) != reference:
            raise ValueError("custom profile differs from frozen release configuration")
        for name in ("deepseek-v41.json", "o200k_base.tiktoken"):
            resource_path("resource:" + name)
        resolved = resolve_run_config(
            goal_file=Path(goal),
            profile_file=Path(profile) if profile else package_file("g3.yaml"),
            provider="deepseek",
            environment={
                "DEEPSEEK_API_KEY": "offline-config-only",
                "CO_SCIENTIST_DEEPSEEK_MODEL": "deepseek-flash",
            },
        )
        m = resolved.model_dump(mode="json")["manifest"]
        config = FullIdeationConfig.model_validate(m["effective_execution_config"])
        if (
            config.version != "ideation-performance-dev-g3-v1"
            or config.continuous_policy is None
            or m["profile"].get("evolution_output_revision") != "evolution-per-parent-output-v1"
        ):
            raise ValueError("Release only supports explicit Continuous R2 G3 DEV profile")
        import yaml

        reference = yaml.safe_load(package_file("g3.yaml").read_text())
        scientific = reference["execution_runtime"]["performance"]["baseline"]["scientific"]
        if m["effective_execution_config"]["performance"]["baseline"]["scientific"] != scientific:
            raise ValueError("scientific parameters differ from the validated R2 release")
        planned = budget(m)
        if (
            Decimal(planned["conservative_usd"]) > Decimal(planned["risk_ceiling_usd"])
            or Decimal(planned["risk_ceiling_usd"]) > 60
        ):
            raise ValueError(
                "Run risk envelope does not cover frozen planning or exceeds release cap"
            )
        return m

    def create(self, goal, data_dir, *, profile=None, mock=False, long=False, failure=None):
        manifest = self.validate(goal, profile)
        run_id = "ideation-g3-" + datetime.now(UTC).strftime("%Y%m%d") + "-" + uuid4().hex
        root = Path(data_dir).expanduser().resolve() / run_id
        root.mkdir(parents=True, exist_ok=False)
        plan = {
            "version": "release-run-plan-v1",
            "run_id": run_id,
            "mode": "MOCK_ONLY" if mock else "LIVE_SINGLE_DISPATCH",
            "manifest_hash": protocol_hash(manifest),
            "config_hash": manifest["effective_execution_config_hash"],
            "code_identity": code_identity(),
            "limits": budget(manifest),
            "pubmed_email": self.environment.get("CO_SCIENTIST_PUBMED_EMAIL"),
            "mock_options": {"long": long, "failure": failure} if mock else None,
        }
        save_new(root / "manifest.json", manifest)
        save_new(root / "goal.json", manifest["goal"])
        save_new(root / "plan.json", plan)
        return {
            "run_id": run_id,
            "run_root": str(root),
            "plan_hash": protocol_hash(plan),
            "limits": plan["limits"],
            "authorized": False,
            "mode": plan["mode"],
        }

    def _verify(self, root):
        root = Path(root).resolve()
        plan, manifest = load(root / "plan.json"), load(root / "manifest.json")
        if (
            plan["version"] != "release-run-plan-v1"
            or plan["manifest_hash"] != protocol_hash(manifest)
            or plan["config_hash"] != manifest["effective_execution_config_hash"]
            or plan["code_identity"] != code_identity()
            or plan["limits"] != budget(manifest)
        ):
            raise ValueError("frozen Run/code/budget identity mismatch")
        return root, plan, manifest

    def authorize(
        self, root, *, confirm, accept_usd, accept_unknown_risk=False, confirm_pricing=False
    ):
        root, plan, _ = self._verify(root)
        if not confirm:
            raise ValueError("explicit --confirm required")
        if Decimal(str(accept_usd)) != Decimal(plan["limits"]["risk_ceiling_usd"]):
            raise ValueError("accept the exact frozen risk ceiling; this does not spend it upfront")
        if plan["mode"] == "LIVE_SINGLE_DISPATCH" and not accept_unknown_risk:
            raise ValueError("explicit possible duplicate-billing risk acceptance required")
        if plan["mode"] == "LIVE_SINGLE_DISPATCH" and not confirm_pricing:
            raise ValueError(
                "operator must confirm current prices/capabilities cover frozen estimates"
            )
        if (root / "authorization.json").exists():
            raise ValueError("already authorized; authorization cannot be overwritten")
        value = {
            "version": "release-authorization-v1",
            "run_id": plan["run_id"],
            "plan_hash": protocol_hash(plan),
            "mode": plan["mode"],
            "accepted_risk_usd": str(accept_usd),
            "limits": plan["limits"],
            "accepted_unknown_delivery_risk": accept_unknown_risk,
            "authorized_at": datetime.now(UTC).isoformat(),
        }
        value["operator_confirmed_pricing_capability"] = confirm_pricing
        save_new(root / "authorization.json", value)
        return value

    def status(self, root):
        root = Path(root).resolve()
        plan = load(root / "plan.json")
        path = root / "runtime/co-scientist.db"
        if not path.exists():
            return {
                "run_id": plan["run_id"],
                "state": "prepared",
                "authorized": (root / "authorization.json").exists(),
                "limits": plan["limits"],
                "stop_requested": (root / "stop-request.json").exists(),
            }
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
            state = db.execute(
                "SELECT state FROM runs WHERE run_id=?", (plan["run_id"],)
            ).fetchone()
            if state is None:
                return {
                    "run_id": plan["run_id"],
                    "state": "prepared",
                    "authorized": (root / "authorization.json").exists(),
                    "limits": plan["limits"],
                    "stop_requested": (root / "stop-request.json").exists(),
                }
            counts = dict(db.execute("SELECT state,COUNT(*) FROM tasks GROUP BY state"))
            event_count = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            costs = db.execute("SELECT cost_usd FROM cost_entries").fetchall()
            final = db.execute(
                "SELECT payload_json FROM events WHERE event_type='IdeationFinalSelectionV1' ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
        from co_scientist.runtime.trace_snapshot import readonly_uow

        with readonly_uow(path) as reader:
            accounting = reader.load_budget_snapshot(plan["run_id"]).model_dump(mode="json")
        return {
            "run_id": plan["run_id"],
            "state": state[0] if state else "prepared",
            "events": event_count,
            "task_states": counts,
            "cost_estimate_not_bill_usd": str(sum((Decimal(c[0]) for c in costs), Decimal(0))),
            "accounting": accounting,
            "final": json.loads(final[0]) if final else None,
            "stop_requested": (root / "stop-request.json").exists(),
        }

    def events(self, root, after=0):
        root = Path(root).resolve()
        if self.status(root)["state"] == "prepared":
            return []
        with sqlite3.connect(
            (root / "runtime/co-scientist.db").as_uri() + "?mode=ro", uri=True
        ) as db:
            return [
                {"sequence": s, "event_type": t, "payload": json.loads(p), "timestamp": d}
                for s, t, p, d in db.execute(
                    "SELECT sequence,event_type,payload_json,occurred_at FROM events WHERE sequence>? ORDER BY sequence",
                    (after,),
                )
            ]

    def export_path(self, root):
        root = Path(root).resolve()
        state = self.status(root)
        if state["state"] in {"completed", "completed_partial", "failed", "cancelled"}:
            return root / "exports"
        return root / "snapshots" / ("events-" + str(state.get("events", 0)))

    def stop(self, root):
        root = Path(root).resolve()
        if not (root / "stop-request.json").exists():
            save_new(
                root / "stop-request.json",
                {
                    "version": "release-stop-request-v1",
                    "requested_at": datetime.now(UTC).isoformat(),
                },
            )
        return {
            "stop_requested": True,
            "behavior": "finish active bounded call, then native PARTIAL; no new scientific dispatch",
        }

    async def execute(self, root, *, steps=None):
        root, plan, manifest = self._verify(root)
        auth = load(root / "authorization.json")
        if (
            auth["version"] != "release-authorization-v1"
            or auth["plan_hash"] != protocol_hash(plan)
            or auth["run_id"] != plan["run_id"]
            or auth["mode"] != plan["mode"]
            or auth["limits"] != plan["limits"]
            or Decimal(auth["accepted_risk_usd"]) != Decimal(plan["limits"]["risk_ceiling_usd"])
        ):
            raise ValueError("authorization identity mismatch")
        terminal = {"completed", "completed_partial", "failed", "cancelled"}
        if self.status(root)["state"] in terminal:
            return self.status(root)  # Replay/finished resume is zero dispatch.
        if plan["mode"] == "LIVE_SINGLE_DISPATCH":
            if not auth["operator_confirmed_pricing_capability"]:
                raise ValueError("pricing/capability confirmation missing")
            if not auth["accepted_unknown_delivery_risk"]:
                raise ValueError("unknown-delivery risk not accepted")
            if not all(self.environment.get(k) for k in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY")):
                raise ValueError("both API credentials required; no dispatch")
            if not plan["pubmed_email"] or "@" not in plan["pubmed_email"]:
                raise ValueError(
                    "PubMed contact email required; create a fresh correctly configured Run"
                )
        lock = (root / "driver.lock").open("a")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close()
            raise ValueError("another driver owns this Run") from None
        runner = None
        mock = None
        if plan["mode"] == "MOCK_ONLY":
            from .mock_http import MockHTTP

            mock = MockHTTP(**plan["mock_options"])
        elif plan["mode"] != "LIVE_SINGLE_DISPATCH":
            lock.close()
            raise ValueError("unsupported execution mode")

        def issue(expected):
            if (root / "stop-request.json").exists():
                raise ValueError("operator stop: external dispatch forbidden")
            if (
                expected["run_id"] != plan["run_id"]
                or expected["mode"] != plan["mode"]
                or expected["config_hash"] != plan["config_hash"]
                or expected["execution_root"] != str(root / "runtime")
                or not 1 <= expected["attempt"] <= 3
            ):
                raise ValueError("permit scope mismatch")
            transport = runner.worker.providers.resolve("deepseek").client._transport
            with transport._db() as db:
                rows = db.execute("SELECT * FROM attempts").fetchall()
            models = [r for r in rows if r["kind"] == "model"]
            retries = [
                r for r in models if int(r["id"].split(":attempt:", 1)[1].split(":", 1)[0]) > 1
            ]
            sol = sum(r["id"].startswith("role:generation:") for r in models)
            literature = [r for r in rows if r["kind"] == "literature"]
            suffix = (
                ":attempt:"
                + str(expected["attempt"])
                + ":"
                + hashlib.sha256(expected["call_id"].encode()).hexdigest()
            )
            key = hashlib.sha256(b"GET\0" + expected["url"].encode() + b"\0").hexdigest() + suffix
            fresh = (
                not any(r["id"] == key for r in rows)
                if expected["method"] == "GET"
                else not any(r["kind"] == "model" and r["id"].endswith(suffix) for r in rows)
            )
            if fresh and (
                len(rows) >= 191
                or (
                    expected["method"] == "POST"
                    and (
                        len(models) >= 143
                        or (
                            len(retries) >= 24
                            if expected["attempt"] > 1
                            else len(models) - len(retries) >= 119
                        )
                        or (
                            sol >= 24
                            if expected["provider"] == "openai"
                            else len(models) - sol >= 135
                        )
                    )
                )
            ):
                raise ValueError("whole-Run dispatch envelope exhausted")
            if fresh and expected["method"] == "GET" and len(literature) >= 48:
                raise ValueError("retrieval envelope exhausted")
            if fresh and sum((Decimal(r["reserved_usd"]) for r in rows), Decimal(0)) + Decimal(
                expected["reserved_usd"]
            ) > Decimal(auth["accepted_risk_usd"]):
                raise ValueError("cost-risk envelope exhausted")
            permits = root / "permits"
            permits.mkdir(exist_ok=True)
            p = permits / (protocol_hash(expected).removeprefix("sha256:") + ".json")
            if p.exists():
                if load(p) != expected:
                    raise ValueError("existing permit mismatch")
            else:
                save_new(p, expected)
            return expected

        environment = {
            k: self.environment[k]
            for k in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY")
            if k in self.environment
        }
        environment["CO_SCIENTIST_PUBMED_EMAIL"] = plan["pubmed_email"]
        try:
            runner = CoreRunner(
                data_dir=root / "runtime",
                environment=environment,
                single_root_authorization={
                    "run_id": plan["run_id"],
                    "execution_mode": manifest["effective_execution_config"]["version"],
                    "mode": plan["mode"],
                    "transport": httpx.MockTransport(mock) if mock else None,
                    "permit_issuer": issue,
                },
            )
            try:
                runner.uow.run_state(plan["run_id"])
            except KeyError:
                runner.supervisor.bootstrap_run(run_id=plan["run_id"], manifest=manifest)
            runner._compose(runner.uow.run_manifest(plan["run_id"]), run_id=plan["run_id"])
            if mock:
                mock.runner = runner
            original = runner.worker.run_once

            async def observed(run_id):
                if (root / "stop-request.json").exists() and runner.uow.run_state(
                    run_id
                ) == "running":
                    await runner._finish_continuous_partial(run_id, "USER_STOP")
                    return WorkerStep(status="terminal", run_id=run_id)
                step = await original(run_id)
                with (root / "progress.jsonl").open("a", encoding="utf-8") as handle:
                    handle.write(
                        json.dumps(
                            {
                                "timestamp": datetime.now(UTC).isoformat(),
                                "step": step.model_dump(mode="json"),
                                "state": runner.uow.run_state(run_id),
                            }
                        )
                        + "\n"
                    )
                return step

            runner.worker.run_once = observed
            if steps is None:
                await runner.drive(run_id=plan["run_id"])
            else:
                for _ in range(steps):
                    step = await runner.worker.run_once(plan["run_id"])
                    if step.status == "idle":
                        history = runner.uow.load(plan["run_id"])
                        runner.supervisor.advance(
                            run_id=plan["run_id"], expected_sequence=history[-1].sequence
                        )
                    if runner.uow.run_state(plan["run_id"]) in terminal:
                        break
            transport = runner.worker.providers.resolve("deepseek").client._transport
            export_trace(
                runner.uow,
                runner.artifacts,
                plan["run_id"],
                self.export_path(root),
                transport_artifacts=transport.artifacts,
            )
        except asyncio.CancelledError:
            # CTRL-C is a requested terminal stop, not a scientific completion.
            if runner is not None:
                await runner._finish_continuous_partial(plan["run_id"], "USER_INTERRUPT")
            raise
        finally:
            if runner is not None:
                await runner.aclose()
            fcntl.flock(lock, fcntl.LOCK_UN)
            lock.close()
        return self.status(root)

    async def export(self, root, output=None):
        root, plan, _ = self._verify(root)
        if self.status(root)["state"] == "prepared":
            raise ValueError("Run not started; nothing to export")
        from co_scientist.adapters.artifacts.filesystem import FilesystemArtifactStore
        from co_scientist.runtime.trace_snapshot import readonly_uow

        with readonly_uow(root / "runtime/co-scientist.db") as reader:
            artifacts = FilesystemArtifactStore(
                root / "runtime/dispatch" / plan["run_id"] / "artifacts"
            )
            target = Path(output) if output else self.export_path(root)
            export_trace(
                reader,
                FilesystemArtifactStore(root / "runtime/artifacts"),
                plan["run_id"],
                target,
                transport_artifacts=artifacts,
            )
            return {"output": str(target.resolve())}
