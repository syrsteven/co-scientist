"""Explicit offline product acceptance server. Never loads credentials or real transports."""

import json
import runpy
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from co_scientist_next.background_ops import DevelopmentReadingAdapter
from co_scientist_next.candidate_review_ops import DevelopmentReviewAdapter
from co_scientist_next.contracts import CallResponse, KnownCallFailure, Usage
from co_scientist_next.generation_ops import DevelopmentGenerationAdapter
from co_scientist_next.store import Store
from co_scientist_next.workspace import make_server

helpers = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "tests/next/test_literature_acquisition.py")
)
FixtureTransport, envelope, FIXTURE = (
    helpers[k] for k in ("FixtureTransport", "envelope", "FIXTURE")
)


class ProductLiterature(FixtureTransport):
    def __call__(self, request):
        params = parse_qs(urlsplit(request["url"]).query)
        if request["url"].endswith("/fullTextXML"):
            return super().__call__(request)
        if params.get("resultType") == ["core"]:
            query = params.get("query", [""])[0] + urlsplit(request["url"]).path
            if "999003" in query:
                response = envelope(request, "OFFLINE access failure")
                response["status_code"] = 503
                raise KnownCallFailure("OFFLINE fixture material access failure", response=response)
            number = next((i for i in range(1, 5) if f"99900{i}" in query), 1)
            article = self.article(number)
            return CallResponse(
                envelope(request, json.dumps({"hitCount": 1, "result": article})),
                Usage(tool_units=1),
            )
        return CallResponse(
            envelope(
                request,
                json.dumps(
                    {
                        "hitCount": 4,
                        "nextCursorMark": "unvisited-page-2",
                        "resultList": {"result": [self.article(i) for i in range(1, 5)]},
                    }
                ),
            ),
            Usage(tool_units=1),
        )

    @staticmethod
    def article(number):
        article = dict(FIXTURE["article"])
        article.update(id=f"99900{number}", title=f"OFFLINE invented product material {number}")
        if number != 1:
            article.pop("pmcid", None)
            article["isOpenAccess"] = "N"
        return article


class DelayedReading(DevelopmentReadingAdapter):
    def __call__(self, request):
        if request["operation"] == "P04":
            time.sleep(12)  # Actual wait boundary for simultaneous note-save/browser checks.
        return super().__call__(request)


def main():
    path = "/private/tmp/co-scientist-product-fixture/runs/fixture.sqlite"
    with Store(path, http_threads=True) as store:
        server = make_server(
            store,
            port=8779,
            responsive=True,
            automatic_research=True,
            development_test=True,
            offline_start_response_loss=True,
            public_literature=True,
            literature_transport=ProductLiterature(),
            reading_adapter=DelayedReading(),
            generation_adapter=DevelopmentGenerationAdapter(),
            review_adapter=DevelopmentReviewAdapter(),
            development_review=True,
            literature_mode="development_fixture",
        )
        print("OFFLINE fixture only: http://127.0.0.1:8779/", flush=True)
        try:
            server.serve_forever()
        finally:
            server.research_controller.stop_event.set()
            server.server_close()


if __name__ == "__main__":
    main()
