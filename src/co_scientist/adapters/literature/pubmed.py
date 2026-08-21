"""Raw-response PubMed E-utilities adapter."""

import hashlib
import json
from typing import Any, Literal

import httpx

from co_scientist.domain.provenance import SourceDocument
from co_scientist.ports.external_provider import RawExternalResponse


class LiteratureAccessIssue(RuntimeError):
    """An HTTP response preventing access to PubMed."""

    def __init__(self, status_code: int, retryable: bool) -> None:
        super().__init__(f"PubMed HTTP {status_code}")
        self.status_code = status_code
        self.retryable = retryable


class PubMedProvider:
    """Access PubMed search and summary envelopes without parsing their records."""

    SEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    SUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"

    def __init__(self, client: httpx.AsyncClient, *, tool: str, email: str | None) -> None:
        self.client = client
        self.tool = tool
        self.email = email

    async def search(self, query: str, limit: int = 10) -> RawExternalResponse:
        response = await self.client.get(
            self.SEARCH_URL,
            params={
                "db": "pubmed",
                "term": query,
                "retmode": "json",
                "retmax": min(limit, 50),
                "tool": self.tool,
                **({"email": self.email} if self.email else {}),
            },
            timeout=20.0,
        )
        return self._raw_response(response)

    async def fetch_summaries(self, pmids: tuple[str, ...]) -> RawExternalResponse:
        if not pmids:
            raise ValueError("at least one PMID is required")
        response = await self.client.get(
            self.SUMMARY_URL,
            params={
                "db": "pubmed",
                "id": ",".join(pmids[:50]),
                "retmode": "json",
                "tool": self.tool,
                **({"email": self.email} if self.email else {}),
            },
            timeout=20.0,
        )
        return self._raw_response(response)

    @staticmethod
    def _raw_response(response: httpx.Response) -> RawExternalResponse:
        if response.status_code >= 400:
            raise LiteratureAccessIssue(
                response.status_code,
                retryable=response.status_code == 429 or response.status_code >= 500,
            )
        body = response.content
        response_id = response.headers.get("ncbi-phid")
        if not response_id:
            response_id = f"sha256:{hashlib.sha256(body).hexdigest()}"
        return RawExternalResponse(
            body=body,
            mime_type=response.headers.get("content-type", "application/json"),
            provider_response_id=response_id,
        )


class PubMedBridge:
    """Adapt one configured PubMed operation to the raw external-call port."""

    def __init__(
        self,
        provider: PubMedProvider,
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


def parse_pubmed_records(
    raw: bytes, *, query: str, raw_artifact_ref: str
) -> tuple[SourceDocument, ...]:
    """Convert a PubMed summary envelope into provenance-only evidence."""

    payload = json.loads(raw)
    result = payload["result"]
    return tuple(
        SourceDocument(
            source_id=f"pubmed:{pmid}",
            provider="pubmed",
            canonical_id=f"PMID:{pmid}",
            title=result[pmid]["title"],
            authors=tuple(author["name"] for author in result[pmid].get("authors", [])),
            publication_date=result[pmid].get("pubdate"),
            retrieval_query=query,
            raw_artifact_ref=raw_artifact_ref,
        )
        for pmid in result["uids"]
    )
