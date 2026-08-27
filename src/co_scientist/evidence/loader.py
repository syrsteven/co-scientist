from pathlib import Path
from typing import Literal

import yaml  # type: ignore[import-untyped]  # types-PyYAML is a dev dependency
from pydantic import BaseModel, ConfigDict, TypeAdapter

SourceLevel = Literal[
    "paper_explicit",
    "supplement_explicit",
    "replica_default",
    "developer_extension",
]


class BehaviorEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)
    behavior_id: str
    source_level: SourceLevel
    source_refs: tuple[str, ...]
    statement: str


def load_behavior_map(path: Path) -> tuple[BehaviorEvidence, ...]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return tuple(TypeAdapter(list[BehaviorEvidence]).validate_python(raw["behaviors"]))
