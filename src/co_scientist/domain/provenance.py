from typing import Literal

from pydantic import BaseModel, ConfigDict


class SourceDocument(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_id: str
    provider: str
    canonical_id: str
    title: str
    authors: tuple[str, ...] = ()
    publication_date: str | None = None
    retrieval_query: str
    raw_artifact_ref: str


class EvidenceItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    evidence_id: str
    source_id: str
    locator: str
    statement: str
    relation: Literal["supports", "refutes", "context_only", "conflicts"]
