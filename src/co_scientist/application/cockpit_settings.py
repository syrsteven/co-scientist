"""Local new-run configuration editor. Never creates a Run or calls a provider."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from co_scientist.adapters.llm.multi_provider import KEY_NAMES
from co_scientist.application.config import CoreProfile, ResearchGoal

PROFILE_FILES = {
    "deepseek": "core_preview_deepseek.yaml", "openai": "core_preview_online.yaml",
    "qwen": "core_preview_qwen.yaml", "gemini": "core_preview_gemini.yaml",
    "claude": "core_preview_claude.yaml", "replay": "core_preview.yaml",
}


class SettingsDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    goal: ResearchGoal
    profile: CoreProfile
    model: str = Field(default="", max_length=160)

    @field_validator("name", "model")
    @classmethod
    def clean_text(cls, value: str) -> str:
        if any(ord(c) < 32 for c in value):
            raise ValueError("control characters are not allowed")
        return value.strip()


def settings_catalog(root: Path, environment: Mapping[str, str]) -> dict[str, Any]:
    from co_scientist.application.model_catalog import model_catalog

    goal = ResearchGoal.model_validate(
        yaml.safe_load((root / "examples/lens_regeneration_goal.yaml").read_text())
    ).model_dump(mode="json")
    templates = []
    for provider, filename in PROFILE_FILES.items():
        profile = CoreProfile.model_validate(
            yaml.safe_load((root / "configs/profiles" / filename).read_text())
        ).model_dump(mode="json")
        templates.append({"id": provider, "goal": goal, "profile": profile})
    return {
        "templates": templates,
        "providers": [
            {"id": provider, "key_env": key, "key_configured": bool(environment.get(key)),
             "model_env": f"CO_SCIENTIST_{provider.upper()}_MODEL",
             "model": environment.get(f"CO_SCIENTIST_{provider.upper()}_MODEL", "")}
            for provider, key in KEY_NAMES.items()
        ],
        "saved": list_saved(root),
        "model_catalog": model_catalog(),
    }


def list_saved(root: Path) -> list[dict[str, Any]]:
    directory = root / ".co-scientist-configs"
    if not directory.exists() or directory.is_symlink():
        return []
    saved = []
    for path in sorted(directory.glob("*/settings.json"), reverse=True)[:100]:
        if path.is_symlink() or path.parent.is_symlink():
            continue
        try:
            record = json.loads(path.read_text())
            draft = SettingsDraft.model_validate(record["draft"]).model_dump(mode="json")
            saved.append({"id": path.parent.name, "saved_at": record["saved_at"], "draft": draft})
        except (OSError, ValueError, KeyError):
            continue
    return saved


def validate_settings(payload: Any) -> dict[str, Any]:
    try:
        draft = SettingsDraft.model_validate(payload)
    except ValidationError as error:
        schema_errors = []
        for item in error.errors(include_input=False, include_url=False, include_context=False):
            field = ".".join(map(str, item["loc"]))
            if "ranking_output_protocol requires" in item["msg"]:
                field = "profile.ranking_output_protocol"
            elif "meta_review requires" in item["msg"]:
                field = "profile.meta_review.max_rounds"
            schema_errors.append({"field": field, "message": item["msg"]})
        return {"ok": False, "errors": schema_errors, "warnings": []}
    errors: list[dict[str, str]] = []
    warnings: list[str] = []

    def fail(field: str, message: str) -> None:
        errors.append({"field": field, "message": message})

    p = draft.profile
    if not draft.name:
        fail("name", "配置名称不能为空。")
    for key in ("title", "goal"):
        if not getattr(draft.goal, key).strip():
            fail(f"goal.{key}", "研究标题和目标不能为空白。")
    for key in ("required_causal_chain", "required_outputs"):
        values = getattr(draft.goal, key)
        if not values or any(not x.strip() for x in values):
            fail(f"goal.{key}", "至少填写一项非空内容。")
    if p.providers.llm != "replay" and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}", draft.model):
        fail("model", "填写实际可用的模型 ID，不是 API key；仅允许字母、数字及 . _ : / -。")
    if p.providers.llm != "deepseek" and p.providers.deepseek_generation is not None:
        fail("profile.providers.deepseek_generation", "这些生成参数仅由 DeepSeek adapter 支持。")
    if p.providers.llm == "replay":
        if p.providers.literature != "replay_pubmed" or p.literature_content != "metadata":
            fail("profile.providers.literature", "离线模板需要 replay_pubmed 和 metadata。")
        if p.evolution.max_rounds:
            fail("profile.evolution.max_rounds", "内置 replay trace 没有演化响应，请关闭演化。")
        if p.meta_review.max_rounds:
            fail("profile.meta_review.max_rounds", "内置 replay trace 没有科学反馈响应，请关闭闭环。")
        warnings.append("Replay 是固定响应回放；修改目标或策略不代表生成了新的科学结果。")
    elif p.providers.literature != "pubmed":
        fail("profile.providers.literature", "在线模型配置使用 PubMed；离线回放请选 replay 模板。")
    stages = set(map(str, p.review_policy.required_before_admission))
    if "initial_review" not in stages or not stages <= {"initial_review", "full_review"}:
        fail("profile.review_policy.required_before_admission", "初审不可关闭；开发版设置仅支持初审和完整评审准入策略。")
    if p.literature_novelty_required and "full_review" not in stages:
        fail("profile.literature_novelty_required", "当前新颖性产物由完整评审生成；启用新颖性准入时需保留完整评审。")
    if not p.literature_novelty_required:
        warnings.append("已关闭文献新颖性准入门槛；这会降低研究证据要求。")
    if p.tournament.anchor_count != 2:
        fail("profile.tournament.anchor_count", "当前内置 anchor 集固定为两个成员。")
    if p.tournament.rating_policy_version != "elo-32-v1":
        fail("profile.tournament.rating_policy_version", "当前仅实现 elo-32-v1，不能通过改名创建新算法。")
    if p.tournament.match_mode != "research":
        fail("profile.tournament.match_mode", "当前运行器未完整实现 binary benchmark 行为，设置页仅开放 research 模式。")
    for key in ("require_anchor_plateau", "require_top_k_stability", "require_cluster_diversity_plateau"):
        if not getattr(p.stop, key):
            fail(f"profile.stop.{key}", "当前停止内核始终联合检查此信号，设置页不能关闭它。")
    for maximum, minimum in (("max_matches", "minimum_matches"), ("max_hypotheses", "minimum_hypotheses"), ("max_model_calls", "minimum_model_calls")):
        limit = getattr(p.budget, maximum)
        if limit is not None and limit < getattr(p.stop, minimum):
            warnings.append(f"{maximum} 小于 {minimum}：预计先达到预算上限，不能满足质量收敛门槛。")
    if p.budget.max_hypotheses is not None and p.stop.top_k > p.budget.max_hypotheses:
        warnings.append("top-k 大于候选数量上限；排名可能不足 k 个。")
    if p.budget.max_model_calls is None or p.budget.max_matches is None:
        warnings.append("当前有界锦标赛继续策略需要同时设置调用与比赛上限；留空不会得到无限自主探索。")
    if p.budget.max_usd is not None:
        warnings.append("当前真实模型账目未完整定价；美元上限不能作为可靠的账单硬保护，请同时限制调用和 tokens。")
    if not p.scientific_context and p.providers.llm != "replay":
        warnings.append("关闭科学上下文后，部分评审/比较输入仅包含引用信息；真实研究建议开启。")
    if p.providers.llm != "replay" and not p.research_protocol_version:
        warnings.append("此配置使用 Legacy 科研输入；建议在评审与演化中显式选择 Research v1，用新配置启动。")
    if p.research_protocol_version and (not draft.goal.required_causal_chain or not draft.goal.required_outputs):
        fail("goal.required_outputs", "Research v1 需要非空因果链与产出要求。")
    if p.providers.llm == "replay" and p.research_protocol_version:
        fail("profile.research_protocol_version", "内置 Replay trace 只支持 Legacy；Research v1 需专用回放数据。")
    warnings.append("当前内置 anchors 面向晶状体再生；换研究领域时须另行实现匹配的 anchor 集。")
    # Nested legacy models ignore extras: fail closed at this editor boundary.
    for key, allowed in (("budget", set(type(p.budget).model_fields)),
                         ("stop", set(type(p.stop).model_fields)),
                         ("review_policy", set(type(p.review_policy).model_fields))):
        raw = payload.get("profile", {}).get(key, {})
        if isinstance(raw, dict) and set(raw) - allowed:
            fail(f"profile.{key}", "包含未支持的字段，不会静默丢弃。")
    if errors:
        return {"ok": False, "errors": errors, "warnings": warnings}
    return {"ok": True, "errors": [], "warnings": warnings, "draft": draft.model_dump(mode="json")}


def save_settings(root: Path, payload: Any) -> dict[str, Any]:
    result = validate_settings(payload)
    if not result["ok"]:
        return result
    draft = result["draft"]
    provider = draft["profile"]["providers"]["llm"]
    saved_id = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-") + uuid4().hex[:8]
    parent = root / ".co-scientist-configs"
    if parent.is_symlink():
        raise ValueError("configuration directory must not be a symlink")
    parent.mkdir(mode=0o700, exist_ok=True)
    directory = parent / saved_id
    directory.mkdir(mode=0o700)
    profile = dict(draft["profile"])
    profile["profile_id"] = f"web-{saved_id}"
    # Export paths remain relative to profile.yaml even outside configs/profiles.
    if provider == "replay":
        profile["replay_resources"] = {
            "llm_responses": "../../examples/lens_regeneration_replay/core_trace.json",
            "pubmed_search": "../../examples/lens_regeneration_replay/pubmed_search.json",
            "pubmed_summary": "../../examples/lens_regeneration_replay/pubmed_summary.json",
        }
    else:
        profile["replay_resources"] = None
    draft["profile"] = profile
    files = {
        "goal.yaml": yaml.safe_dump(draft["goal"], allow_unicode=True, sort_keys=False),
        "profile.yaml": yaml.safe_dump(profile, allow_unicode=True, sort_keys=False),
    }
    relative = directory.relative_to(root).as_posix()
    args = ["co-scientist", "run", "execute", "--run-id", f"web-{saved_id}",
            "--goal", f"{relative}/goal.yaml", "--profile", f"{relative}/profile.yaml",
            "--provider", provider, "--data-dir", f".co-scientist-{provider}"]
    command = shlex.join(args)
    if provider != "replay":
        command = f"CO_SCIENTIST_{provider.upper()}_MODEL={shlex.quote(draft['model'])} " + command
    for name, content in files.items():
        with (directory / name).open("x", encoding="utf-8") as handle:
            handle.write(content)
    record = {"id": saved_id, "saved_at": datetime.now(UTC).isoformat(), "draft": draft}
    # Commit marker is written last; incomplete saves are not listed.
    with (directory / "settings.json").open("x", encoding="utf-8") as handle:
        json.dump(record, handle, ensure_ascii=False, indent=2)
    return {**result, **record, "files": files, "directory": relative,
            "command": command, "run_started": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("command", choices=["catalog", "validate", "save"])
    args = parser.parse_args()
    if args.command == "catalog":
        result = settings_catalog(args.root, os.environ)
    else:
        payload = json.loads(sys.stdin.read(1024 * 1024))
        result = validate_settings(payload) if args.command == "validate" else save_settings(args.root, payload)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
