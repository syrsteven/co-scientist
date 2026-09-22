from pathlib import Path

import httpx
import pytest

from co_scientist.adapters.literature.pubmed import (
    PubMedBridge,
    PubMedProvider,
    parse_pubmed_abstracts,
)

FIXTURE = Path("tests/scenario/fixtures/pubmed_abstracts_lens.xml")


def test_abstract_parser_preserves_sections_inline_text_and_missingness() -> None:
    documents = parse_pubmed_abstracts(FIXTURE.read_bytes(), query="lens", raw_artifact_ref="external-call:test")
    first, second = documents
    assert first.title == "Lens epithelial regeneration"
    assert first.abstract == "BACKGROUND: Synthetic fixture, not scientific evidence.\nRESULTS: Preserved cells retain regenerative potential."
    assert first.content_level == "abstract"
    assert first.authors == ("Alice Example",)
    assert first.publication_date == "2016 Mar"
    assert second.abstract is None and second.content_level == "metadata"
    assert second.authors == ("Example Group",)
    assert second.publication_date == "2020 Winter"
    assert all(document.raw_artifact_ref == "external-call:test" for document in documents)


@pytest.mark.parametrize("xml", [
    b"<PubmedArticleSet/>", b"<ERROR>service unavailable</ERROR>",
    b"<!DOCTYPE x [<!ENTITY secret SYSTEM 'file:///etc/passwd'>]><PubmedArticleSet/>",
    FIXTURE.read_bytes().replace(b"<PMID>1002</PMID>", b"<PMID>1001</PMID>"),
    FIXTURE.read_bytes().replace(b"<PMID>1001</PMID>", b"<PMID>bad-id</PMID>"),
])
def test_invalid_xml_sources_are_rejected(xml: bytes) -> None:
    with pytest.raises(ValueError):
        parse_pubmed_abstracts(xml, query="lens", raw_artifact_ref="external-call:test")


@pytest.mark.asyncio
async def test_bridge_requests_relevance_and_raw_efetch_xml() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=FIXTURE.read_bytes(), headers={"content-type": "text/xml"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        provider = PubMedProvider(client, tool="test", email=None)
        await PubMedBridge(provider, "search").invoke({"query": "lens", "sort": "relevance"})
        raw = await PubMedBridge(provider, "summary").invoke({"pmids": ["1001", "1002"], "content_mode": "abstracts"})
        assert requests[0].url.params["sort"] == "relevance"
        assert requests[1].url.path.endswith("efetch.fcgi")
        assert requests[1].url.params["id"] == "1001,1002"
        assert requests[1].url.params["retmode"] == "xml"
        assert raw.body == FIXTURE.read_bytes() and raw.mime_type == "text/xml"
        for pmids in ((), ("invalid",), tuple(str(i) for i in range(51))):
            with pytest.raises(ValueError):
                await provider.fetch_abstracts(pmids)
        assert len(requests) == 2
