"""Deterministic, content-bound passages for claim provenance."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def _sha(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


class SourceUnit(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_unit_id: str
    hypothesis_id: str
    hypothesis_content_hash: str
    ordinal: int = Field(ge=0)
    exact_text: str
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=1)
    exact_text_hash: str


class SourceUnitV2(BaseModel):
    """Versioned source identity; semantic relation is not encoded here."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: Literal["source-unit-v2"] = "source-unit-v2"
    source_unit_id: str
    hypothesis_id: str
    hypothesis_content_hash: str
    ordinal: int = Field(ge=0)
    exact_text: str
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=1)
    exact_text_hash: str


def _source_unit_v2_id(
    hypothesis_id: str,
    hypothesis_content_hash: str,
    ordinal: int,
    exact_text: str,
) -> str:
    identity = f"source-unit-v2\0{hypothesis_id}\0{hypothesis_content_hash}\0{ordinal}\0{exact_text}"
    return "source-unit-v2:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()


def source_units_v2_for_content(inputs: Mapping[str, Any]) -> tuple[SourceUnitV2, ...]:
    """Derive v2 source units without changing the legacy v1 identities."""
    legacy_units = source_units_for_content(inputs)
    return tuple(SourceUnitV2(
        source_unit_id=_source_unit_v2_id(
            unit.hypothesis_id, unit.hypothesis_content_hash, unit.ordinal, unit.exact_text,
        ),
        hypothesis_id=unit.hypothesis_id,
        hypothesis_content_hash=unit.hypothesis_content_hash,
        ordinal=unit.ordinal,
        exact_text=unit.exact_text,
        char_start=unit.char_start,
        char_end=unit.char_end,
        exact_text_hash=_sha(unit.exact_text),
    ) for unit in legacy_units)


def resolve_source_units_v2(
    source_unit_ids: list[str] | tuple[str, ...],
    *,
    expected_hypothesis_id: str,
    expected_content_hash: str,
    allowed_units: tuple[SourceUnitV2, ...],
) -> tuple[SourceUnitV2, ...]:
    """Resolve only exact, unique units from the frozen hypothesis scope."""
    if not source_unit_ids:
        raise ValueError("source unit provenance cannot be empty")
    if len(set(source_unit_ids)) != len(source_unit_ids):
        raise ValueError("duplicate source unit id")
    by_id = {unit.source_unit_id: unit for unit in allowed_units}
    if len(by_id) != len(allowed_units):
        raise ValueError("duplicate source unit in allowed scope")
    resolved: list[SourceUnitV2] = []
    for source_unit_id in source_unit_ids:
        unit = by_id.get(source_unit_id)
        if unit is None or not source_unit_id.startswith("source-unit-v2:"):
            raise ValueError("unknown source unit id")
        if unit.hypothesis_id != expected_hypothesis_id:
            raise ValueError("source unit hypothesis mismatch")
        if unit.hypothesis_content_hash != expected_content_hash:
            raise ValueError("source unit content hash mismatch")
        if unit.exact_text_hash != _sha(unit.exact_text):
            raise ValueError("source unit exact text hash mismatch")
        if unit.source_unit_id != _source_unit_v2_id(
            unit.hypothesis_id, unit.hypothesis_content_hash, unit.ordinal, unit.exact_text,
        ):
            raise ValueError("source unit identity mismatch")
        if unit.char_end - unit.char_start != len(unit.exact_text):
            raise ValueError("source unit offset mismatch")
        resolved.append(unit)
    return tuple(resolved)


def source_units_for_content(inputs: Mapping[str, Any]) -> tuple[SourceUnit, ...]:
    """One unit per immutable scientific passage; offsets index their newline join."""
    from co_scientist.domain.hypothesis import HypothesisContent

    hypothesis_id = inputs.get("hypothesis_id")
    content_hash = inputs.get("content_hash")
    body = inputs.get("hypothesis_content")
    if not isinstance(hypothesis_id, str) or not hypothesis_id or not isinstance(body, Mapping):
        raise ValueError("source units require immutable hypothesis content and identity")
    content = HypothesisContent.model_validate(body)
    if not isinstance(content_hash, str) or content.content_hash != content_hash:
        raise ValueError("source unit content hash mismatch")
    if body.get("content_hash") not in (None, content_hash):
        raise ValueError("source unit content hash mismatch")
    passages = (content.title, content.claim, *content.mechanism_chain,
                *content.assumptions, *content.predictions, *content.falsifiers)
    units: list[SourceUnit] = []
    cursor = 0
    for ordinal, exact_text in enumerate(passages):
        if not exact_text.strip():
            raise ValueError("source unit text cannot be empty")
        source_unit_id = _sha(f"{hypothesis_id}\0{content_hash}\0{ordinal}\0{exact_text}")
        units.append(SourceUnit(source_unit_id=source_unit_id, hypothesis_id=hypothesis_id,
            hypothesis_content_hash=content_hash, ordinal=ordinal, exact_text=exact_text,
            char_start=cursor, char_end=cursor + len(exact_text),
            exact_text_hash=_sha(exact_text)))
        cursor += len(exact_text) + 1
    return tuple(units)
