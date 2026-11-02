# Co-Scientist W1 v0.4 — Supervisor / Codex Method Handoff

**Status:** PROPOSED. This handoff requests design review only and does not authorize coding, PR merges, or paid model calls.  
**As verified 2026-11-03:** GitHub `main=e98404cda9ec35a82a1c363c14e315f54e240d96`; PR #4 is OPEN/unmerged, head `c6f7e0949f9353bfcd9ea1d8be28daef273f8292`. According to the user handoff W0-T4 was not executed; no W0-T4 implementation is claimed.

## 1. Design recommendation to approve/reject

**Adopt in principle:**
- M00's fixed sequence and module boundaries, with **Goal Ethics completed decisions only `pass/reject`**.
- M01's **two-level literature discovery**: neutral, goal-first broad search followed by seed-specific focused retrieval.
- Context-preserving reading records that keep the actual biological model, intervention, endpoint, source interpretation, important negative observations and unverified transfer assumptions.
- Seed-specific `BackgroundPacket` and **per-seed/readability-dependent Readiness**. No global paper-count or mandatory full-text quota.
- Directed/open input isolation: open branch is not initialized with ranked candidate mechanisms or other seed outputs.
- Direct and explicit iterative-assumption Generation as two **separate test arms**, rather than claiming one is already superior.
- Narrow R0 blocking only fundamental non-evaluability or demonstrably indispensable source misrepresentation; scientific unknown goes to R1.

**Do not silently approve:**
- Candidate Ethics binary simplification. The user's binary instruction applied only to `screen_goal`.
- Any specific background-readiness score, fixed candidate count, model, temperature, search call count or global novelty conclusion.
- Pro v0.3 as an independent multi-agent run or scientific validation.

## 2. Exact W1 operation/ownership map

| Owner | Operation and saved output | External interactions | Scientific handoff |
|---|---|---|---|
| M01 | `prepare_goal` -> GoalContext | supplied user materials only | M02 Goal Ethics |
| M02 | `screen_goal` -> pass/reject + policy refs | approved policy, optional model through M15 | Only pass to M01 broad search |
| M01 | `plan_orientation`, `retrieve/read/synthesize` -> SearchHistory, source views, cards, OrientationPacket | M01 retrieval strategy, shared LiteraturePort implemented through M15 | M01 seed planner |
| M01 | directed/open seed launch, focused retrieval, readiness -> SeedBackgroundPacket + ReadinessDecision | Actual provider searches/fetches and model reads | Ready seed to M01 Generation |
| M01 | `generate_hypotheses` -> new immutable Hypothesis | Model call, actual full final visible input persisted via M15 | M02 Candidate Ethics |
| M02 | `candidate_ethics` -> candidate safety result | approved candidate safety policy | pass to R0, other outcomes do not continue |
| M02 | `review_r0` -> R0Review + R1 questions | no new external literature searches | M03 (later, separate) |
| M12 | legal next step | no scientific judgments | sequence and blocked/failed effects only |

The accepted M00 design already owns the downstream M03–M09 scientific chain. Do not implement M05 full evidence appraisal inside background reading or R0. No new general graph runner or durable scientific truth service is requested by v0.4.

## 3. Concrete input/output semantics

The four included documents are normative **proposals**, not frozen production schema:

- `W1_Method_Protocol_v0.4_PROPOSED.md` — methods, search/readiness rules, branch gates, evaluation.
- `W1_English_Prompt_Pack_v0.4_PROPOSED.md` — full P01–P10 project-authored English prompts and variable ownership.
- `W1_Complete_Worked_Input_v0.4_PROPOSED.json` — self-contained transport seed packet with material representations, ContextContrast, source access, an actual *proposed* generation USER payload and itemized readiness/R0 samples. `NOT_SENT_TO_ANY_MODEL` explicitly.
- `W1_ALS_Worked_Walkthrough_v0.4_PROPOSED.md` — scientist-facing stepwise walkthrough and AML check.

**Required model-facing payload:** correct Goal/Seed/Prompt version; actual selected material passages or openly labeled assistant paraphrases; source identity/locator and actual access; negative findings; conflicting source context; assumed transfers; source selection/trimming notes; full renderer input and returned output. Saving only DOI, a `finding_id` or a source summary without the actual visible evidence is insufficient.

**Key behavior:** `ready` allows a *conjecture at stated specificity*, not proven correctness; `retrieve_more` specifies a fact to obtain; `unable_to_prepare` marks that seed unprepared, not scientifically false. Readiness is M01 internal, not an extra M00 global Ethics category.

## 4. Proposed implementation slices, subject to owner authorization

### W0-T4 (existing next slice): Goal + Ethics + minimal page

- Freeze BriefRevision with its original, explicit user conditions; save GoalContext stable reference.
- Goal Ethics successful decisions are binary; reject prevents background/Generation downstream.
- Missing policy, malformed input, technical timeout are explicit execution/validation errors; cannot be turned into Ethics decisions.
- Preserve current M15 attempt, replay, unknown-usage and uncertain-call behavior.
- M12 makes only the **minimal conditional successor**. Generation remains unimplemented/unavailable and must never be simulated as a scientific result.
- **Frontend:** new research/Brief save, frozen Goal, constraints, screening result, real task state; refresh reads persisted backend without automatically resuming or resending.
- **Acceptance:** pass, reject, missing-policy, technical failure, process recovery; UI create/run/read/refresh; no fake candidate.

### W1-L (subsequent slice): source acquisition and background methods

- M01 search plan with broad vs focused intent; real LiteraturePort adapters; source identity/version and recorded access.
- FindingCards + ContextContrast, KnowledgeMap, seed-specific pack with actual material views.
- Targeted retrieval on `retrieve_more`, `unable_to_prepare` honest when necessary material unavailable.
- **Frontend:** search history, source count (actual only), read level, findings/contradictions, per-seed readiness and missing-material request.
- **Acceptance:** empty search != tool failure, abstract != full text, version family dedup, negative-finding preservation, actual final model input, no invented coverage, source quotation/locator consistency.

### W1-G (next): real Generation + Candidate Ethics/R0

- Directed and open seed input manifests; fixed candidate IDs; one candidate output per call; immutable saved scientific content; actual rendered request.
- Separate DIRECT/ITERATIVE_ASSUMPTIONS configurations for later empirical evaluation; no automatic fake multi-agent debate.
- Candidate Ethics using its **own approved taxonomy**; R0 narrow gate + actual R1 focus.
- **Frontend:** hypothesis-centered candidate cards, mechanism/assumptions/predictions/falsifier/source views, Ethics/R0 and honest incomplete states; no ranking if none exists.
- **Acceptance:** seed input isolation, candidate output identity across recovery, no unauthorized source/label leakage, no R0 rewrites, no candidate enters M03 after reject/block; all displayed results from persisted backend.

### W1-E (scientific evaluation, not only engineering tests)

- Fixed source packet; compare compact vs ContextContrast representation independently.
- With packet fixed, compare DIRECT vs ITERATIVE_ASSUMPTIONS independently.
- At equal generation opportunities, compare directed-only vs directed+open.
- Human expert labeling: factual accuracy, evidence transfer, causal specificity, differentiating prediction, false R0 blocks, honest novelty coverage. Report uncertainty, failures and actual tokens/cost.
- Include source-to-goal leakage tests. ALS/AML are public development cases, not a hidden external scientific benchmark. Expand with independent research tasks when available.

## 5. Explicit non-goals

No full M03–M09, TrueSkill, Ranking/Evolution; no broad platform refactor; no old G3 compatibility; no new user resource budget. No automatic editing or re-entry of an R0-blocked hypothesis into Mutation. No global Epoch change. No final Winner or fake completed science. Do not modify PR #4 scientific expectations by editing test data to fit results.

## 6. Page sync: what goes where in V5 concept

V5 remains a UI/interaction reference; its mock timeline and G3 replay cannot become new-system live facts. This review did not re-open the actual HTML for pixel-level design.

| Stage | Page placement | Real data source | User action / empty and failed state |
|---|---|---|---|
| Brief and Goal | New study / run header | BriefRevision, GoalContext | Edit Draft before Run, inspect fixed Goal; if no Goal, show awaiting preparation |
| Goal Ethics | Run stage/status | M02 decision + versioned policy | Inspect reason; reject blocks continuation; missing-policy is execution error |
| Background | Run detail / Sources | Searches, sources, findings, actual access | Review found papers, unavailable full text, zero-results vs failed; no mock paper count |
| Seed readiness | Research direction list | M01 per-seed state + criterion basis | See ready/retrieve_more/unable_to_prepare; one seed pending does not block other ready seeds |
| Generated hypothesis | Candidate-centered workspace | Immutable M01 candidate + inputs | Read core claim, added link, uncertainty, falsifier; no fabricated rankings |
| Candidate Ethics/R0 | Candidate detail | M02 screening and R0 | See applicable decision, exact blocking defect or R1 verification questions |
| Recovery/failure | Run task view | M12/M15 persisted facts | Refresh is read-only; real resume/stop enabled only after backend support |

Delivery status must separately track `backend_implemented`, `M12_integrated`, `frontend_integrated`, `science_validated`; do not mark full user-facing completion when frontend is disconnected.

## 7. Technical acceptance and scientific non-claims

- Engineering mocks verify payload binding, valid branching, store replay, missing-context treatment and render correctness; **not** generation science.
- For any model review, inspect the full finalized user payload with actual materials and source representations, not merely prompt names.
- The v0.3 ALS/AML results and v0.4 constructed packet are non-blind public development examples; they cannot demonstrate independent novel discovery or parameter superiority.
- Only claim evidence for methods after real independent/controlled model calls and appropriate expert review.

## 8. Owner decisions and next action

**Ask owner to approve the v0.4 scientific method principles** (two-stage literature search, ContextContrast, per-seed readiness, open input isolation, narrow R0) and accept this as a *proposal*. Separately obtain production safety policy and Candidate Ethics completion semantics. Allow the already-planned W0-T4 implementation **only with explicit development authorization**, preserving its minimal first-page interface. Start W1-L/G production work only after the actual packet and evaluation cases are reviewed. Do not treat this handoff itself as a Codex instruction to execute.
