"""Synthetic offline HTTP only. Never an alternate production provider."""

import json

import httpx

from co_scientist.runtime.transport_observability import current_external_call_observation


class MockHTTP:
    def __init__(self, *, long=False, failure=None):
        self.runner = None
        self.long = long
        self.failure = failure
        self.sent = []
        self.injected = False

    async def __call__(self, request):
        self.sent.append({"method": request.method, "url": str(request.url)})
        if request.method == "GET":
            if "esearch" in request.url.path:
                return httpx.Response(
                    200,
                    json={
                        "esearchresult": {
                            "count": "30",
                            "idlist": [str(i) for i in range(1, 21)],
                            "querytranslation": request.url.params["term"],
                        }
                    },
                )
            ids = request.url.params["id"].split(",")
            xml = "".join(
                f"<PubmedArticle><MedlineCitation><PMID>{i}</PMID><Article><ArticleTitle>SYNTHETIC source {i}</ArticleTitle><Abstract><AbstractText>Offline fixture, not scientific evidence.</AbstractText></Abstract></Article></MedlineCitation></PubmedArticle>"
                for i in ids
            )
            return httpx.Response(200, text="<PubmedArticleSet>" + xml + "</PubmedArticleSet>")
        context = current_external_call_observation()
        task = self.runner.uow.task_definition(context.task_id)
        inputs = task.payload["inputs"]
        b = inputs["ideation_task_binding"]
        m = inputs["model_input"]
        schema = b["schema_id"]
        if schema in {"DirectiveEthicsResultV1", "CandidateEthicsResultV1"}:
            body = {"verdict": "PASS", "reason": "Synthetic Mock only"}
        elif schema == "RootQueryPlanResultV1":
            body = {
                "queries": ["mitochondri*[tiab] AND stress[tiab]"],
                "rationale": "Synthetic test plan",
            }
        elif schema == "RootLiteratureReviewResultV1":
            body = {
                "reviewed_source_ids": m["retrieval_result"]["outcome"]["usable_source_ids"],
                "scoped_empty": False,
                "review": "All supplied synthetic sources inspected; not real evidence.",
            }
        elif schema in {"GroundedGenerationResultV1", "BaselineEvolutionResultV1"}:
            name = b["slot_id"] + ("-safe" if b["redesign_count"] else "")
            mechanism = ["Synthetic causal mechanism, not a scientific result."]
            if self.long:
                mechanism.append(
                    "Complete candidate mechanism, competing explanations and falsification controls. "
                    * 1100
                )
            candidate = {
                "hypothesis_id": "hyp-" + name,
                "content_id": "content-" + name,
                "title": name,
                "hypothesis": "Synthetic hypothesis " + name,
                "mechanism": mechanism,
                "assumptions": ["Synthetic test condition"],
                "predictions": ["Observed test change"],
                "falsifiers": ["No test change"],
            }
            body = {"candidate": candidate}
            if schema == "BaselineEvolutionResultV1":
                body.update(
                    operator=m["operator"],
                    rationale="Synthetic synthesis or critique-guided mutation",
                    parent_contributions=[
                        p["hypothesis_id"] + ": retained content and all critique-driven revisions"
                        for p in m["parents"]
                    ],
                )
        elif schema == "BaselineReflectionResultV1":
            critiques = ["Weak prior support", "Alternative causal explanation"]
            if self.long:
                critiques = [
                    c + " Full untrimmed controls and source limitations." * 500 for c in critiques
                ]
            body = {
                "critiques": critiques,
                "plausibility": "uncertain",
                "prior_research": "bounded",
                "testability": "testable",
                "originality": "unknown",
                "unjustified_complexity": "simplify",
            }
        elif schema == "BaselineRankingResultV1":
            body = {
                "decision": "decisive",
                "winner_slot": 1,
                "dimension_reasons": {"testability": "Fixture preference"},
                "confidence": 0.7,
            }
        else:
            raise ValueError("unexpected Mock operation")
        text = json.dumps(body)
        finish = "stop"
        if (
            not self.injected
            and b["attempt"] == 1
            and schema == "DirectiveEthicsResultV1"
            and self.failure
        ):
            self.injected = True
            if self.failure == "unknown":
                raise httpx.ReadTimeout("Injected pure LLM unknown delivery")
            if self.failure == "429":
                return httpx.Response(
                    429, json={"error": {"code": "rate_limit"}}, headers={"Retry-After": "0"}
                )
            if self.failure == "length":
                finish = "length"
            if self.failure == "json":
                text += " invalid trailing JSON"
        if schema == "GroundedGenerationResultV1":
            return httpx.Response(
                200,
                json={
                    "model": "gpt-6.1-sol",
                    "status": "completed",
                    "output": [
                        {"type": "message", "content": [{"type": "output_text", "text": text}]}
                    ],
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 20,
                        "output_tokens_details": {"reasoning_tokens": 5},
                    },
                },
            )
        return httpx.Response(
            200,
            json={
                "model": "deepseek-flash",
                "choices": [{"finish_reason": finish, "message": {"content": text}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            },
        )
