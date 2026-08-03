"""Port for literature providers that preserve their raw responses."""

from typing import Protocol

from co_scientist.ports.external_provider import RawExternalResponse


class LiteratureProvider(Protocol):
    """Search literature and retrieve summaries without interpreting them."""

    async def search(self, query: str, limit: int = 10) -> RawExternalResponse: ...

    async def fetch_summaries(self, pmids: tuple[str, ...]) -> RawExternalResponse: ...
