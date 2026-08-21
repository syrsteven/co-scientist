"""Deterministic PubMed response provider for offline scenarios."""

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from co_scientist.ports.external_provider import RawExternalResponse


class ReplayPubMedSearchResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    idlist: tuple[str, ...]

    @model_validator(mode="after")
    def validate_ids(self) -> "ReplayPubMedSearchResult":
        if any(not identifier for identifier in self.idlist):
            raise ValueError("PubMed search identifiers must be non-empty")
        return self


class ReplayPubMedSearchEnvelope(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    esearchresult: ReplayPubMedSearchResult


class ReplayPubMedSummaryEnvelope(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    result: dict[str, Any]

    @model_validator(mode="after")
    def validate_records(self) -> "ReplayPubMedSummaryEnvelope":
        identifiers = self.result.get("uids")
        if not isinstance(identifiers, list) or any(
            not isinstance(identifier, str) or not identifier for identifier in identifiers
        ):
            raise ValueError("PubMed summary identifiers are malformed")
        for identifier in identifiers:
            record = self.result.get(identifier)
            if not isinstance(record, dict) or record.get("uid") != identifier:
                raise ValueError("PubMed summary record identity is malformed")
            if not isinstance(record.get("title"), str) or not record["title"]:
                raise ValueError("PubMed summary title is malformed")
            authors = record.get("authors", [])
            if not isinstance(authors, list) or any(
                not isinstance(author, dict)
                or not isinstance(author.get("name"), str)
                or not author["name"]
                for author in authors
            ):
                raise ValueError("PubMed summary authors are malformed")
        return self


class ReplayLiteratureProvider:
    """Return committed PubMed fixtures without accessing the network."""

    def __init__(self, search_path: Path, summary_path: Path) -> None:
        self.search_payload = search_path.read_bytes()
        self.summary_payload = summary_path.read_bytes()
        try:
            ReplayPubMedSearchEnvelope.model_validate(
                json.loads(self.search_payload)
            )
            ReplayPubMedSummaryEnvelope.model_validate(
                json.loads(self.summary_payload)
            )
        except (json.JSONDecodeError, TypeError, ValidationError) as error:
            raise ValueError("typed PubMed replay resource is malformed") from error

    async def search(self, query: str, limit: int = 10) -> RawExternalResponse:
        return RawExternalResponse(
            body=self.search_payload,
            mime_type="application/json",
            provider_response_id="replay-pubmed-search-lens",
        )

    async def fetch_summaries(self, pmids: tuple[str, ...]) -> RawExternalResponse:
        return RawExternalResponse(
            body=self.summary_payload,
            mime_type="application/json",
            provider_response_id="replay-pubmed-summary-lens",
        )


class ReplayPubMedBridge:
    """Adapt one configured PubMed operation to the raw external-call port."""

    def __init__(
        self,
        provider: ReplayLiteratureProvider,
        operation: Literal["search", "summary"],
    ) -> None:
        self.provider = provider
        self.operation = operation

    async def invoke(self, request: dict[str, Any]) -> RawExternalResponse:
        if self.operation == "search":
            return await self.provider.search(
                str(request["query"]), int(request.get("limit", 10))
            )
        return await self.provider.fetch_summaries(tuple(map(str, request["pmids"])))
