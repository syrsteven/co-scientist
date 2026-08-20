"""Deterministic PubMed response provider for offline scenarios."""

from pathlib import Path
from typing import Any, Literal

from co_scientist.ports.external_provider import RawExternalResponse


class ReplayLiteratureProvider:
    """Return committed PubMed fixtures without accessing the network."""

    def __init__(self, search_path: Path, summary_path: Path) -> None:
        self.search_payload = search_path.read_bytes()
        self.summary_payload = summary_path.read_bytes()

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
