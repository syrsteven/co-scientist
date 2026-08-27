import json
import os

import httpx
import pytest

from co_scientist.adapters.literature.pubmed import PubMedProvider


@pytest.mark.online
@pytest.mark.asyncio
async def test_live_pubmed_returns_at_least_one_pmid() -> None:
    if not (
        os.getenv("OPENAI_API_KEY")
        and os.getenv("CO_SCIENTIST_OPENAI_MODEL")
        and os.getenv("CO_SCIENTIST_NETWORK_ONLINE") == "1"
    ):
        pytest.skip(
            "requires OPENAI_API_KEY, CO_SCIENTIST_OPENAI_MODEL, and "
            "CO_SCIENTIST_NETWORK_ONLINE=1"
        )

    async with httpx.AsyncClient() as client:
        provider = PubMedProvider(client, tool="co-scientist-core", email=None)
        raw = await provider.search("lens epithelial cell regeneration fibrosis", limit=5)

    assert json.loads(raw.body)["esearchresult"]["idlist"]
    assert raw.provider_response_id
