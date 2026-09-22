"""Catalog-bound cockpit retry/raw bridge; never constructs a runner or provider."""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, ValidationError
from sqlalchemy.exc import SQLAlchemyError

from co_scientist.adapters.artifacts.filesystem import FilesystemArtifactStore
from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork
from co_scientist.application.cockpit import ReadOnlyUnitOfWork
from co_scientist.application.commands import RetryInvalidOutput, SubmitScientistFeedback
from co_scientist.application.output_diagnostics import json_syntax_diagnostic
from co_scientist.application.output_retry import submit_output_retry
from co_scientist.domain.review import ReviewPolicy
from co_scientist.ports.artifact_store import ArtifactRef
from co_scientist.ports.event_store import ConcurrencyConflict
from co_scientist.supervisor.orchestrator import Supervisor
from co_scientist.supervisor.scientist_feedback import submit_scientist_feedback

MAX_RAW_BYTES = 4 * 1024 * 1024
PREVIEW_CHARACTERS = 65536


class RawTooLarge(ValueError):
    pass


class CockpitArtifacts(FilesystemArtifactStore):
    """Bounded reads of contained files, with whole-artifact integrity checks."""

    def __init__(self, database: Path) -> None:
        root = database.parent / "artifacts"
        if root.is_symlink():
            raise ValueError("artifact root cannot be a symbolic link")
        super().__init__(root)

    def read(self, ref: ArtifactRef) -> bytes:
        if ref.byte_length > MAX_RAW_BYTES:
            raise RawTooLarge("Raw exceeds cockpit limit; inspect with CLI")
        with self._contained_path(self.root / ref.path).open("rb") as handle:
            body = handle.read(MAX_RAW_BYTES + 1)
        if len(body) > MAX_RAW_BYTES:
            raise RawTooLarge("Raw exceeds cockpit limit; inspect with CLI")
        if len(body) != ref.byte_length or "sha256:" + hashlib.sha256(body).hexdigest() != ref.sha256:
            raise ValueError("raw artifact integrity check failed")
        return body


class RetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    external_call_id: str = Field(min_length=1, max_length=2048)
    expected_sequence: StrictInt = Field(ge=0)
    confirmed: StrictBool


def retry_output(database: Path, run_id: str, payload: object) -> dict[str, Any]:
    try:
        request = RetryRequest.model_validate(payload)
        if not request.confirmed:
            return {"ok": False, "status": 422, "error": "请明确确认新调用可能产生费用。"}
        command = RetryInvalidOutput(run_id=run_id, external_call_id=request.external_call_id,
            expected_run_sequence=request.expected_sequence, confirmed=True)
        database = database.resolve(strict=True)
        reader = ReadOnlyUnitOfWork(database)
        try:
            manifest = reader.run_manifest(run_id)
            if reader.load(run_id)[-1].sequence != request.expected_sequence:
                raise ConcurrencyConflict("stale sequence")
        finally:
            reader.engine.dispose()
        if manifest.get("execution_contract_version") != 3:
            return {"ok": False, "status": 409, "error": "旧运行仅支持 CLI 检查，不自动升级。"}
        writer = SqliteUnitOfWork(f"sqlite:///{database.as_uri()}?mode=rw&uri=true")
        try:
            supervisor = Supervisor(uow=writer, review_policy=ReviewPolicy.model_validate(manifest["profile"]["review_policy"]))
            result = submit_output_retry(supervisor, CockpitArtifacts(database), command)
            return {**result, "ok": True, "status": 200,
                "worker_command": shlex.join(["co-scientist", "worker", "run", run_id, "--data-dir", str(database.parent)]),
                "message": "已授权并重新排队，未启动 Worker。存活的 Worker 可能领取任务并产生费用。"}
        finally:
            writer.engine.dispose()
    except ValidationError:
        return {"ok": False, "status": 422, "error": "请求需要调用 ID、整数序号和明确确认，不接受额外字段。"}
    except (FileNotFoundError, KeyError):
        return {"ok": False, "status": 404, "error": "运行、调用或原始响应不存在。"}
    except ConcurrencyConflict:
        return {"ok": False, "status": 409, "error": "运行已更新，请刷新核对并重新确认；未自动重试。"}
    except RawTooLarge:
        return {"ok": False, "status": 413, "error": "原始响应超过网页 4 MiB 限制，请用 CLI 检查。"}
    except ValueError:
        return {"ok": False, "status": 409, "error": "重试被拒绝：请检查状态、预算、次数与原始证据完整性。"}
    except (OSError, SQLAlchemyError):
        return {"ok": False, "status": 503, "error": "存储操作未确认完成，请刷新检查事件后再操作。"}


def scientist_feedback(database: Path, run_id: str, payload: object) -> dict[str, Any]:
    try:
        if not isinstance(payload, dict):
            return {"ok": False, "status": 422, "error": "JSON object required"}
        if "run_id" in payload:
            return {"ok": False, "status": 422, "error": "run_id is selected by the route"}
        command = SubmitScientistFeedback.model_validate({**payload, "run_id": run_id})
        database = database.resolve(strict=True)
        writer = SqliteUnitOfWork(f"sqlite:///{database.as_uri()}?mode=rw&uri=true")
        try:
            manifest = writer.run_manifest(run_id)
            supervisor = Supervisor(uow=writer,
                review_policy=ReviewPolicy.model_validate(manifest["profile"]["review_policy"]))
            result = submit_scientist_feedback(supervisor, run_id=run_id,
                feedback_id=command.feedback_id, expected_sequence=command.expected_run_sequence,
                actor=command.actor, note=command.note, confirmed=command.confirmed)
            return {**result, "ok": True, "status": 200,
                "message": "意见已记录并排队独立复评。未启动Worker；存活Worker可能领取任务并产生费用。"}
        finally:
            writer.engine.dispose()
    except ValidationError:
        return {"ok": False, "status": 422, "error": "请填写研究者、意见、反馈ID、整数序号及费用确认。"}
    except ConcurrencyConflict:
        return {"ok": False, "status": 409, "error": "运行已变化，请刷新核对事件，不要重复提交。"}
    except (FileNotFoundError, KeyError):
        return {"ok": False, "status": 404, "error": "运行或反馈不存在。"}
    except ValueError as error:
        return {"ok": False, "status": 409, "error": str(error)}
    except (OSError, SQLAlchemyError):
        return {"ok": False, "status": 503, "error": "结果未确认，请刷新查看事件后再操作。"}


def read_raw(database: Path, run_id: str, call_id: str) -> dict[str, Any]:
    try:
        database = database.resolve(strict=True)
        reader = ReadOnlyUnitOfWork(database)
        try:
            call = reader.get_external_call(call_id)
        finally:
            reader.engine.dispose()
        if call.run_id != run_id or call.raw_artifact_ref is None:
            return {"ok": False, "status": 404, "error": "该运行不存在此原始响应。"}
        body = CockpitArtifacts(database).read(call.raw_artifact_ref)
        text = body.decode("utf-8", errors="replace")
        return {"ok": True, "status": 200, "external_call_id": call_id,
            "artifact_ref": call.raw_artifact_ref.model_dump(mode="json"), "integrity_verified": True,
            "json_diagnostic": json_syntax_diagnostic(body, call.provider),
            "text": text[:PREVIEW_CHARACTERS], "truncated": len(text) > PREVIEW_CHARACTERS}
    except (FileNotFoundError, KeyError):
        return {"ok": False, "status": 404, "error": "原始响应不存在。"}
    except RawTooLarge:
        return {"ok": False, "status": 413, "error": "原始响应超过网页 4 MiB 限制，请用 CLI 检查。"}
    except ValueError:
        return {"ok": False, "status": 409, "error": "原始响应完整性或路径校验失败；未显示正文。"}
    except (OSError, SQLAlchemyError):
        return {"ok": False, "status": 503, "error": "暂时无法读取原始响应。"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--call-id")
    parser.add_argument("command", choices=["retry", "raw", "scientist-feedback"])
    args = parser.parse_args()
    if args.command == "raw":
        result = read_raw(args.database, args.run_id, args.call_id or "")
    else:
        try:
            payload = json.load(sys.stdin)
        except ValueError:
            payload = None
        result = (scientist_feedback(args.database, args.run_id, payload)
                  if args.command == "scientist-feedback" else retry_output(args.database, args.run_id, payload))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
