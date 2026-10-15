"""Deterministic, snapshot-bound EvidenceUnit v1 identities."""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _sha(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _unit_id(
    snapshot_id: str,
    snapshot_hash: str,
    field_kind: str,
    char_start: int,
    char_end: int,
    exact_text_hash: str,
) -> str:
    identity = (
        f"evidence-unit-v1\0{snapshot_id}\0{snapshot_hash}\0{field_kind}\0"
        f"{char_start}\0{char_end}\0{exact_text_hash}"
    )
    return "evidence-unit-v1:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()


class EvidenceUnitV1(BaseModel):
    """A deterministic exact field span from one immutable evidence snapshot."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: Literal["evidence-unit-v1"] = "evidence-unit-v1"
    evidence_unit_id: str
    evidence_snapshot_id: str
    evidence_snapshot_hash: str
    field_kind: Literal["title", "abstract"]
    exact_text: str
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=1)
    exact_text_hash: str

    @model_validator(mode="after")
    def validate_identity(self) -> EvidenceUnitV1:
        if self.exact_text_hash != _sha(self.exact_text):
            raise ValueError("evidence unit exact text hash mismatch")
        if self.char_end - self.char_start != len(self.exact_text):
            raise ValueError("evidence unit offset mismatch")
        if self.evidence_unit_id != _unit_id(
            self.evidence_snapshot_id,
            self.evidence_snapshot_hash,
            self.field_kind,
            self.char_start,
            self.char_end,
            self.exact_text_hash,
        ):
            raise ValueError("evidence unit identity mismatch")
        return self


def evidence_units_for_snapshot(snapshot: object) -> tuple[EvidenceUnitV1, ...]:
    """Split a validated snapshot into exact title/abstract field units.

    Canonical text is title + LF + abstract if both are nonempty, the sole
    nonempty field otherwise, and empty when neither field has content.
    Empty means exactly ``""``; no trimming or Unicode normalization occurs.
    Offsets are Python Unicode code-point indices, start-inclusive/end-exclusive.
    """
    snapshot_id = getattr(snapshot, "snapshot_id", None)
    snapshot_hash = getattr(snapshot, "snapshot_hash", None)
    title = getattr(snapshot, "title", None)
    abstract = getattr(snapshot, "abstract", None)
    if not isinstance(snapshot_id, str) or not snapshot_id:
        raise ValueError("evidence snapshot identity is required")
    if not isinstance(snapshot_hash, str) or not snapshot_hash:
        raise ValueError("evidence snapshot hash is required")
    if not isinstance(title, str) or (abstract is not None and not isinstance(abstract, str)):
        raise ValueError("evidence snapshot fields must be strings")
    abstract_text = abstract or ""
    fields: list[tuple[Literal["title", "abstract"], str, int]] = []
    if title != "":
        fields.append(("title", title, 0))
    if abstract_text != "":
        abstract_start = len(title) + 1 if title and abstract_text else 0
        fields.append(("abstract", abstract_text, abstract_start))
    units: list[EvidenceUnitV1] = []
    for field_kind, exact_text, char_start in fields:
        char_end = char_start + len(exact_text)
        text_hash = _sha(exact_text)
        units.append(EvidenceUnitV1(
            evidence_unit_id=_unit_id(
                snapshot_id, snapshot_hash, field_kind, char_start, char_end, text_hash,
            ),
            evidence_snapshot_id=snapshot_id,
            evidence_snapshot_hash=snapshot_hash,
            field_kind=field_kind,
            exact_text=exact_text,
            char_start=char_start,
            char_end=char_end,
            exact_text_hash=text_hash,
        ))
    return tuple(units)


def resolve_evidence_units(
    evidence_unit_ids: list[str] | tuple[str, ...],
    *,
    expected_snapshot_id: str,
    expected_snapshot_hash: str,
    allowed_units: tuple[EvidenceUnitV1, ...],
) -> tuple[EvidenceUnitV1, ...]:
    """Resolve unique EvidenceUnit IDs only from the frozen snapshot allowlist."""
    if not evidence_unit_ids:
        raise ValueError("evidence unit provenance cannot be empty")
    if len(set(evidence_unit_ids)) != len(evidence_unit_ids):
        raise ValueError("duplicate evidence unit id")
    by_id = {unit.evidence_unit_id: unit for unit in allowed_units}
    if len(by_id) != len(allowed_units):
        raise ValueError("duplicate evidence unit in allowed scope")
    resolved: list[EvidenceUnitV1] = []
    for evidence_unit_id in evidence_unit_ids:
        unit = by_id.get(evidence_unit_id)
        if unit is None or not evidence_unit_id.startswith("evidence-unit-v1:"):
            raise ValueError("unknown evidence unit id")
        if unit.evidence_snapshot_id != expected_snapshot_id:
            raise ValueError("evidence unit snapshot mismatch")
        if unit.evidence_snapshot_hash != expected_snapshot_hash:
            raise ValueError("evidence unit snapshot hash mismatch")
        # Revalidation catches forged model_copy/update instances as well as stale IDs.
        EvidenceUnitV1.model_validate(unit.model_dump(mode="python"))
        resolved.append(unit)
    return tuple(resolved)
