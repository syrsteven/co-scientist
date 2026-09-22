"""Raw-response PubMed E-utilities adapter."""

import hashlib
import json
import xml.etree.ElementTree as ET
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
    FETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

    def __init__(self, client: httpx.AsyncClient, *, tool: str, email: str | None) -> None:
        self.client = client
        self.tool = tool
        self.email = email

    async def search(self, query: str, limit: int = 10, *, sort: str | None = None) -> RawExternalResponse:
        if sort not in {None, "relevance", "pub_date"}:
            raise ValueError("unsupported PubMed sort order")
        response = await self.client.get(
            self.SEARCH_URL,
            params={
                "db": "pubmed",
                "term": query,
                "retmode": "json",
                "retmax": min(limit, 50),
                "tool": self.tool,
                **({"sort": sort} if sort else {}),
                **({"email": self.email} if self.email else {}),
            },
            timeout=20.0,
        )
        return self._raw_response(response)

    async def fetch_abstracts(self, pmids: tuple[str, ...]) -> RawExternalResponse:
        if not pmids or len(pmids) > 50 or any(not pmid.isdigit() for pmid in pmids):
            raise ValueError("EFetch requires 1-50 numeric PMIDs")
        response = await self.client.get(
            self.FETCH_URL,
            params={"db": "pubmed", "id": ",".join(pmids), "retmode": "xml",
                    "tool": self.tool, **({"email": self.email} if self.email else {})},
            timeout=30.0,
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
                str(request["query"]), int(request.get("limit", 10)), sort=request.get("sort")
            )
        if request.get("content_mode") == "abstracts":
            return await self.provider.fetch_abstracts(tuple(map(str, request["pmids"])))
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


def parse_pubmed_abstracts(
    raw: bytes, *, query: str, raw_artifact_ref: str,
) -> tuple[SourceDocument, ...]:
    """Parse saved EFetch XML, preserving inline text and structured abstract labels.

    Do not fetch DTDs or resolve external entities. UTF-8 is the PubMed wire format;
    rejecting entity declarations also prevents internal entity expansion.
    """
    xml = raw.decode("utf-8")
    if "<!ENTITY" in xml.upper():
        raise ValueError("XML entity declarations are not allowed")
    root = ET.fromstring(xml)
    if root.tag != "PubmedArticleSet" or root.find(".//ERROR") is not None:
        raise ValueError("invalid PubMed EFetch envelope")

    def text_of(element: ET.Element | None) -> str:
        return "" if element is None else " ".join("".join(element.itertext()).split())

    documents: list[SourceDocument] = []
    seen: set[str] = set()
    for record in root.findall("PubmedArticle"):
        citation = record.find("MedlineCitation")
        if citation is None:
            raise ValueError("PubMed record has no citation")
        pmid = text_of(citation.find("PMID"))
        title = text_of(citation.find("Article/ArticleTitle"))
        if not pmid.isdigit() or pmid in seen or not title:
            raise ValueError("PubMed record identity/title missing or duplicated")
        seen.add(pmid)
        sections = []
        for section in citation.findall("Article/Abstract/AbstractText"):
            body = text_of(section)
            if body:
                label = section.get("Label")
                sections.append(f"{label}: {body}" if label else body)
        abstract = "\n".join(sections) or None
        authors = tuple(
            text_of(author.find("CollectiveName")) or " ".join(filter(None, (
                text_of(author.find("ForeName")), text_of(author.find("LastName")),
            )))
            for author in citation.findall("Article/AuthorList/Author")
        )
        date = citation.find("Article/Journal/JournalIssue/PubDate")
        publication_date = None if date is None else " ".join(filter(None, (
            text_of(date.find("Year")), text_of(date.find("Month")),
            text_of(date.find("Day")), text_of(date.find("MedlineDate")),
        ))) or None
        documents.append(SourceDocument(
            source_id=f"pubmed:{pmid}", provider="pubmed", canonical_id=f"PMID:{pmid}",
            title=title, authors=authors, publication_date=publication_date,
            retrieval_query=query, raw_artifact_ref=raw_artifact_ref,
            abstract=abstract, content_level="abstract" if abstract else "metadata",
        ))
    if not documents:
        raise ValueError("PubMed EFetch returned no article records")
    return tuple(documents)
