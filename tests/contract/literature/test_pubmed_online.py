import json
import os

import httpx
import pytest

from co_scientist.adapters.literature.pubmed import PubMedProvider


@pytest.mark.online
@pytest.mark.asyncio
async def test_live_pubmed_returns_at_least_one_pmid() -> None:
    if os.getenv("CO_SCIENTIST_PUBMED_ONLINE") != "1":
        pytest.skip("set CO_SCIENTIST_PUBMED_ONLINE=1 to run the live PubMed contract")

    async with httpx.AsyncClient() as client:
        provider = PubMedProvider(client, tool="co-scientist-core", email=None)
        raw = await provider.search("lens epithelial cell regeneration fibrosis", limit=5)

    assert json.loads(raw.body)["esearchresult"]["idlist"]
