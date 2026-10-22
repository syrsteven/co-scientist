"""Versioned compatibility builder: no fallback or frozen-profile relaxation."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Goal(Strict):
    title: str = Field(min_length=3, max_length=150)
    goal: str = Field(min_length=15, max_length=30000)
    required_causal_chain: list[str] = Field(min_length=1, max_length=100)
    required_outputs: list[str] = Field(min_length=1, max_length=100)


class Runtime(Strict):
    template_id: str = "continuous-g3-r2-default"
    generation_model: str = "gpt-6.1-sol"
    review_evolution_model: str = "deepseek-flash"
    root_slots: int = Field(default=4, ge=1, le=20, strict=True)
    reproduction_transitions: int = Field(default=3, ge=0, le=10, strict=True)
    reproduction_slots_per_transition: int = Field(default=2, ge=1, le=10, strict=True)
    risk_ceiling_usd: str = "60"
    wall_minutes: int = Field(default=120, ge=1, le=1440, strict=True)


class Draft(Strict):
    project_id: str | None = None
    goal: Goal
    run_config: Runtime = Field(default_factory=Runtime)
    mode: Literal["MOCK_ONLY", "LIVE_SINGLE_DISPATCH"] = "MOCK_ONLY"
    constraints_note: str = Field(default="", max_length=10000)


def diagnostics(draft):
    expected = Runtime().model_dump()
    found = draft.run_config.model_dump()
    errors = [
        {
            "field": f"run_config.{key}",
            "code": "UNVALIDATED_CONFIGURATION",
            "message": "该组合尚未完成完整 Mock 验证；仅可保存草稿，不回退默认配置。",
        }
        for key in expected
        if found[key] != expected[key]
    ]
    if draft.constraints_note.strip():
        errors.append(
            {
                "field": "constraints_note",
                "code": "UNMAPPED_SCIENTIFIC_INPUT",
                "message": "补充约束尚无原生契约映射；请将必要科学要求明确写入研究目标。",
            }
        )
    return errors
