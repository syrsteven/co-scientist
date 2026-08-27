import hashlib
from pathlib import Path

import httpx
import pytest

from co_scientist.adapters.literature.pubmed import PubMedProvider, parse_pubmed_records
from co_scientist.adapters.literature.replay import ReplayLiteratureProvider


@pytest.mark.asyncio
async def test_pubmed_search_returns_raw_before_record_parsing(respx_mock) -> None:
    respx_mock.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi").respond(
        200, json={"esearchresult": {"idlist": ["123"]}}
    )
    async with httpx.AsyncClient() as client:
        provider = PubMedProvider(client, tool="co-scientist-core", email=None)
        raw = await provider.search("lens epithelial fibrosis", limit=5)

    assert raw.mime_type.startswith("application/json")
    assert b'"123"' in raw.body


# Mutation caught: trusting NCBI to always return its optional request header and
# leaving online raw provenance without a stable provider response identity.
@pytest.mark.asyncio
async def test_pubmed_search_falls_back_to_a_body_bound_response_id(respx_mock) -> None:
    body = b'{"esearchresult":{"idlist":["123"]}}'
    respx_mock.get(PubMedProvider.SEARCH_URL).respond(
        200,
        content=body,
        headers={"content-type": "application/json"},
    )
    async with httpx.AsyncClient() as client:
        provider = PubMedProvider(client, tool="co-scientist-core", email=None)
        raw = await provider.search("lens epithelial fibrosis", limit=5)

    assert raw.provider_response_id == f"sha256:{hashlib.sha256(body).hexdigest()}"


@pytest.mark.asyncio
async def test_pubmed_search_caps_results_and_includes_request_identity(respx_mock) -> None:
    route = respx_mock.get(PubMedProvider.SEARCH_URL).respond(
        200, json={"esearchresult": {"idlist": ["123"]}}
    )
    async with httpx.AsyncClient() as client:
        provider = PubMedProvider(
            client, tool="co-scientist-core", email="research@example.test"
        )
        await provider.search("lens epithelial fibrosis", limit=75)

    assert route.called
    params = route.calls.last.request.url.params
    assert params["db"] == "pubmed"
    assert params["term"] == "lens epithelial fibrosis"
    assert params["retmode"] == "json"
    assert params["retmax"] == "50"
    assert params["tool"] == "co-scientist-core"
    assert params["email"] == "research@example.test"


@pytest.mark.asyncio
async def test_pubmed_search_uses_a_twenty_second_timeout(respx_mock) -> None:
    route = respx_mock.get(PubMedProvider.SEARCH_URL).respond(
        200, json={"esearchresult": {"idlist": ["123"]}}
    )
    async with httpx.AsyncClient() as client:
        provider = PubMedProvider(client, tool="co-scientist-core", email=None)
        await provider.search("lens epithelial fibrosis")

    timeout = route.calls.last.request.extensions["timeout"]
    assert timeout == {"connect": 20.0, "read": 20.0, "write": 20.0, "pool": 20.0}


@pytest.mark.asyncio
async def test_pubmed_summary_caps_comma_delimited_pmids_at_fifty(respx_mock) -> None:
    route = respx_mock.get(PubMedProvider.SUMMARY_URL).respond(
        200, json={"result": {"uids": []}}
    )
    pmids = tuple(str(pmid) for pmid in range(1, 52))
    async with httpx.AsyncClient() as client:
        provider = PubMedProvider(client, tool="co-scientist-core", email=None)
        raw = await provider.fetch_summaries(pmids)

    assert raw.mime_type.startswith("application/json")
    assert route.calls.last.request.url.params["id"] == ",".join(pmids[:50])
    assert route.calls.last.request.extensions["timeout"] == {
        "connect": 20.0,
        "read": 20.0,
        "write": 20.0,
        "pool": 20.0,
    }


@pytest.mark.asyncio
async def test_pubmed_summary_rejects_empty_pmids_without_a_request(respx_mock) -> None:
    route = respx_mock.get(PubMedProvider.SUMMARY_URL).respond(
        200, json={"result": {"uids": []}}
    )
    async with httpx.AsyncClient() as client:
        provider = PubMedProvider(client, tool="co-scientist-core", email=None)
        with pytest.raises(ValueError, match="at least one PMID"):
            await provider.fetch_summaries(())

    assert not route.called


def test_pubmed_parser_creates_source_documents_without_proximity_edges() -> None:
    raw = b'{"result":{"uids":["123"],"123":{"title":"Lens study","authors":[]}}}'

    records = parse_pubmed_records(
        raw, query="lens regeneration", raw_artifact_ref="artifact:summary"
    )

    assert len(records) == 1
    assert records[0].source_id == "pubmed:123"
    assert records[0].canonical_id == "PMID:123"
    assert records[0].retrieval_query == "lens regeneration"
    assert records[0].raw_artifact_ref == "artifact:summary"
    assert all(record.__class__.__name__ == "SourceDocument" for record in records)


@pytest.mark.asyncio
async def test_replay_provider_returns_committed_lens_fixtures() -> None:
    fixtures = Path(__file__).parents[2] / "scenario" / "fixtures"
    provider = ReplayLiteratureProvider(
        fixtures / "pubmed_search_lens.json", fixtures / "pubmed_summary_lens.json"
    )

    search = await provider.search("ignored", limit=1)
    summary = await provider.fetch_summaries(("ignored",))

    assert b'"1001"' in search.body
    assert b"Lens epithelial cell state after minimally invasive surgery" in summary.body
    assert search.provider_response_id == "replay-pubmed-search-lens"
    assert summary.provider_response_id == "replay-pubmed-summary-lens"


# Mutation caught: loading arbitrary fixture bytes into the production replay
# provider without validating the typed PubMed search/summary envelopes.
def test_replay_provider_rejects_malformed_typed_resources(tmp_path: Path) -> None:
    search = tmp_path / "search.json"
    summary = tmp_path / "summary.json"
    search.write_text('{"esearchresult":{"idlist":"1001"}}', encoding="utf-8")
    summary.write_text('{"result":{"uids":["1001"]}}', encoding="utf-8")

    with pytest.raises(ValueError, match="typed PubMed replay resource"):
        ReplayLiteratureProvider(search, summary)
