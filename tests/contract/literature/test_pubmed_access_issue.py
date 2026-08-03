import httpx
import pytest

from co_scientist.adapters.literature.pubmed import (
    LiteratureAccessIssue,
    PubMedProvider,
)


@pytest.mark.asyncio
async def test_429_is_classified_as_transient_access_issue(respx_mock) -> None:
    respx_mock.get(PubMedProvider.SEARCH_URL).respond(429)
    async with httpx.AsyncClient() as client:
        provider = PubMedProvider(client, tool="co-scientist-core", email=None)
        with pytest.raises(LiteratureAccessIssue) as error:
            await provider.search("lens regeneration")

    assert error.value.retryable


@pytest.mark.asyncio
async def test_400_is_classified_as_non_retryable_access_issue(respx_mock) -> None:
    respx_mock.get(PubMedProvider.SUMMARY_URL).respond(400)
    async with httpx.AsyncClient() as client:
        provider = PubMedProvider(client, tool="co-scientist-core", email=None)
        with pytest.raises(LiteratureAccessIssue) as error:
            await provider.fetch_summaries(("123",))

    assert error.value.status_code == 400
    assert not error.value.retryable
