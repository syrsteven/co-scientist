"""Deterministic PubMed response provider for offline scenarios."""

from pathlib import Path

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
