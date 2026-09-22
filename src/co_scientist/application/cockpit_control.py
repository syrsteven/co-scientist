"""Explicit local lifecycle commands; never start workers, providers or migrations."""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, ValidationError
from sqlalchemy.exc import SQLAlchemyError

from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork
from co_scientist.application.cockpit import ReadOnlyUnitOfWork
from co_scientist.domain.review import ReviewPolicy
from co_scientist.domain.transitions import InvalidTransition
from co_scientist.export.run_export import SqliteRunReadModel
from co_scientist.ports.event_store import ConcurrencyConflict
from co_scientist.supervisor.orchestrator import Supervisor


class ControlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action: Literal["pause", "resume", "stop"]
    expected_sequence: StrictInt = Field(ge=0)
    confirmed: StrictBool


def control_run(database: Path, run_id: str, payload: object) -> dict[str, Any]:
    """Server resolves database and run_id from its catalog, never request-body paths."""
    try:
        request = ControlRequest.model_validate(payload)
        if not request.confirmed:
            return {"ok": False, "status": 422, "error": "请明确确认运行控制操作。"}
        # Read/validate before opening the write boundary. A missing file is not created.
        database = database.resolve(strict=True)
        reader = ReadOnlyUnitOfWork(database)
        try:
            with SqliteRunReadModel(reader).snapshot(run_id) as read:
                manifest = read.run_manifest(run_id)
        finally:
            reader.engine.dispose()
        if manifest.get("execution_contract_version") != 3:
            return {"ok": False, "status": 409, "error": "仅支持当前 v3 运行；请使用 CLI 检查旧运行。"}
        if manifest["current_sequence"] != request.expected_sequence:
            return {"ok": False, "status": 409, "error": "运行已更新，请刷新并重新确认；未自动重试。"}
        allowed = {"pause": {"running"}, "resume": {"paused"}, "stop": {"running", "paused"}}
        if manifest["final_state"] not in allowed[request.action]:
            return {"ok": False, "status": 409, "error": "当前运行状态不允许此操作。"}
        policy = ReviewPolicy.model_validate(manifest["profile"]["review_policy"])
        writer = SqliteUnitOfWork(f"sqlite:///{database.as_uri()}?mode=rw&uri=true")
        try:
            supervisor = Supervisor(uow=writer, review_policy=policy)
            action = {"pause": supervisor.pause_run, "resume": supervisor.resume_run,
                      "stop": supervisor.request_soft_stop}[request.action]
            result = action(run_id, expected_sequence=request.expected_sequence)
            return {
                "ok": True, "status": 200, "run_id": run_id, "action": request.action,
                "current_sequence": result.last_sequence, "worker_started": False,
                "worker_command": shlex.join([
                    "co-scientist", "worker", "run", run_id, "--data-dir", str(database.parent),
                ]),
                "message": "已记录控制事件。不会启动 Worker；在途请求可能继续完成并产生费用。",
            }
        finally:
            writer.engine.dispose()
    except ValidationError:
        return {"ok": False, "status": 422, "error": "无效控制请求：需要操作、整数序号和明确确认。"}
    except (FileNotFoundError, KeyError):
        return {"ok": False, "status": 404, "error": "运行或其冻结配置不存在。"}
    except (ConcurrencyConflict, InvalidTransition, ValueError):
        return {"ok": False, "status": 409, "error": "状态或序号冲突，请刷新核对；部分控制事件可能已落盘。"}
    except (OSError, SQLAlchemyError):
        return {"ok": False, "status": 503, "error": "存储操作未确认完成，请刷新核对后再操作。"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        payload = None
    print(json.dumps(control_run(args.database, args.run_id, payload), ensure_ascii=False))


if __name__ == "__main__":
    main()
