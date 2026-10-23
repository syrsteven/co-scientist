"""Browser-only deterministic event boundaries; no HTTP or provider dispatch."""

import os
from pathlib import Path

import pytest

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(
    not os.environ.get("CO_SCIENTIST_BROWSER_TESTS"), reason="explicit offline Chromium test")]


@pytest.mark.parametrize("decision", ["tie", "abstain", "inconclusive"])
async def test_historical_replay_does_not_leak_future_or_count_ties(decision):
    from playwright.async_api import async_playwright
    assets = Path("src/co_scientist_web/frontend")
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        async def serve(route):
            name = route.request.url.split("/")[-1] or "index.html"
            if name == "backend.js":
                await route.fulfill(body="", content_type="application/javascript")
            else:
                await route.fulfill(path=str(assets / name))
        await page.route("**/*", serve)
        await page.goto("http://127.0.0.1/")
        result = await page.evaluate("""(decision) => {
          const ev=(sequence,event_type,payload)=>({sequence,event_type,payload});
          const content=id=>({hypothesis_id:id,title:id,claim:'claim',content_hash:id,
            scientific_parent_ids:[],generation_index:0});
          const events=[ev(1,'HypothesisContentCreated',content('a')),
            ev(2,'HypothesisContentCreated',content('b')),
            ev(3,'InitialRatingAssigned',{hypothesis_id:'a',mu:25,sigma:8}),
            ev(4,'TaskCompleted',{task_id:'synthetic'}),
            ev(5,'MatchPairReserved',{match_id:'m',left_id:'a',right_id:'b'}),
            ev(6,'MatchEvaluated',{match_id:'m',left_id:'a',right_id:'b',decision}),
            ev(7,'CandidateEthicsRecordedV1',{binding:{hypothesis_id:'a',content_hash:'a'}}),
            ev(8,'BaselineReflectionRecordedV1',{binding:{hypothesis_id:'a',content_hash:'a'},secret:'future'})];
          const docs={'candidates.json':[content('a'),content('b')].map(c=>({...c,
            created_sequence:c.hypothesis_id==='a'?1:2,rating:{mu:99,sigma:1,decisive_matches:8},
            reflection:[events[7]],ethics:[events[6]]})),
            'ranking-history.json':[{match_id:'future',left_id:'a',right_id:'b',reserved_sequence:90}],
            'evolution-tree.json':{},'run-timeline.json':{run_id:'r',events,
              final_selection:{execution_result:'COMPLETE',terminal_barrier_complete:true,selection_result:'FINAL_WINNER',winner_id:'a'}}};
          const m=window.CoScientistMonitor;m.loadBackend(docs,{});
          const latest=m.snapshot();
          document.querySelector('#frame-slider').value=3;
          document.querySelector('#frame-slider').dispatchEvent(new Event('input',{bubbles:true}));
          const history=m.snapshot();
          const missing=structuredClone(docs);
          missing['run-timeline.json'].events=structuredClone(events.slice(0,6));
          Object.assign(missing['run-timeline.json'].events[5].payload,{decision:'decisive',winner_id:'a'});
          m.loadBackend(missing,{});
          return {latest,history,missingProjection:m.snapshot()};
        }""", decision)
        assert result["latest"]["candidates"][0]["matches"] == 0
        assert result["latest"]["candidates"][0]["score"]["mu"] == 25
        assert result["latest"]["candidates"][1]["score"] is None
        assert not result["history"]["candidates"][0]["reflection"]
        assert not result["history"]["candidates"][0]["ethics"]
        assert result["latest"]["final"] is None
        assert result["missingProjection"]["candidates"][0]["score"] is None
        assert all(m["match_id"] != "future" for m in result["history"]["ranking"])
        await browser.close()
