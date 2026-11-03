# Co-Scientist W1 — M01/M02 Scientific Method Protocol v0.4

**Status:** PROPOSED / for owner and supervisor review; not an approved scientific method or implementation authorization.  
**Date:** 2026-11-03.  
**Baseline:** accepted M00-ARCH-v1.0; v0.3 Pro study; W0-T3 PR #4 proposal.  
**Scope:** `prepare_goal -> screen_goal -> M01 background research -> generate_hypotheses -> candidate_ethics -> R0`. No production code, PR merge, paid-model tests, R1–R3, Ranking, Evolution, or new orchestration platform.

## A. What changed from v0.3

| Issue exposed in the v0.3 assessment | v0.4 method decision | Status |
|---|---|---|
| BackgroundPack lacked a complete model-visible example | Define `SeedBackgroundPacket`, with source-view snapshots, actual access representations, context contrasts, search coverage, and renderable model payload | PROPOSED |
| Queries quickly concentrated on named proteins | Separate **goal-first broad orientation** from **seed-specific focused retrieval**; require query audit | PROPOSED |
| Readiness expected an initial discriminating prediction | Check **credible factual starting points and possible measurability**; generation constructs the discriminating prediction | PROPOSED |
| Open seed could inherit coordinator-preferred mechanisms | Explicit allowed/denied input manifest; open branch independently discovers mechanisms | PROPOSED |
| R0 risked adjudicating science using shallow source comparison | Restrict source-based block to directly demonstrable, indispensable source misrepresentation; otherwise route to R1 | PROPOSED |
| Candidate Ethics was made binary without user authorization | `screen_goal` alone fixed to pass/reject; leave Candidate Ethics decision policy for M02 owner review | PROPOSED |
| v0.3 method comparison used a same-assistant rewrite | Specify true, separately executed ablations and blinded expert review before declaring efficacy | PROPOSED |

Terminology: [DISCLOSED] explicitly in Nature/arXiv; [INFERRED] plausible reading; [PROPOSED] our procedure. This document does **not** alter accepted M00 rules. No W1 scientific results have been independently validated.

## B. Actual operations, inputs, and handoffs

| Operation (owner) | Input read | Output saved | Condition/edge |
|---|---|---|---|
| `prepare_goal` (M01) | Frozen BriefRevision, user question and explicit constraints, user materials manifest | `GoalContext` with original exact text, source-located constraints, preferences and unspecified conditions | An indispensable ambiguity causes clarification **before** Ethics; other unspecified conditions remain unknown |
| `screen_goal` (M02) | GoalContext, intended use, approved safety policy | `GoalEthics{pass/reject,policy_refs,reason}` | Only pass continues; missing policy/invalid input is an execution or validation problem, not a third Ethics verdict |
| `plan_orientation` (M01) | Passed Goal, source capabilities | `OrientationSearchPlan` and query coverage matrix | Must not presuppose a protein/kinase not supplied or retrieved |
| `search/read` (M01 shared LiteraturePort, M15 call record) | Actual planned search and selected source IDs | `SearchHistory`, `SourceCatalog`, source-view snapshots, `LiteratureFindingCards` | Search failed != searched empty; abstract != full text |
| `synthesize_orientation` (M01) | Actual finding cards and coverage | `OrientationPacket`, `KnowledgeMap`, `ResearchGapMap` | Include negative observations, contextual contrasts, source limitations |
| `plan_directed_seeds` (M01) | Neutral orientation, available gaps; no prior candidate answers | `SeedResearchBrief`s with scientific question and missing link, not prewritten answers | Distinctness by causal bottleneck; no artificial fixed taxonomy |
| `start_open_seed` (M01) | **Only** Goal, neutral orientation, source capabilities, general search constraints | Open Seed search question(s) and independently discovered gap | Exclude ranked gap map, coordinator's preferred mechanisms, sibling briefs and candidate texts |
| `seed_retrieve/read/synthesize` (M01) | One seed brief, relevant source records + new searches | Complete `SeedBackgroundPacket` and actual model-visible `source_views` | Share downloads; do not share hidden sibling candidate content |
| `check_readiness` (M01) | SeedPacket, actual retrieval/access facts, requested hypothesis specificity | `ReadinessDecision{ready/retrieve_more/unable_to_prepare,criteria,evidence,reason}` | Ready -> Generation; retrieve_more -> targeted query; unable -> preserve unprepared seed, do not claim disproven |
| `generate_hypotheses` (M01) | Frozen Goal, one ready packet, generation mode | One **immutable Hypothesis** + refs, new bridges, assumptions, predictions/falsification, model call | Never claim scientific verification or rank |
| `candidate_ethics` (M02) | Saved candidate + Goal and actual intended use, applicable policy | Candidate safety decision, clauses and reasons | Keep its unfinished/uncertain policy semantics separate from Goal Ethics binary change |
| `review_r0` (M02) | Fixed candidate, passed Candidate Ethics, Goal, visible source views | `R0Review{proceed_to_R1/blocked,blocking_defects,scientific_unknowns,R1_focus}` | Narrow preliminary gate; no search, revision, scientific scoring or M03 inventory |

M12 only routes the above operations according to their owning modules' results. M15 persists actual sends, response/error, access levels, unknown usage, and idempotent replay. A technical exception is never converted to a scientific or ethics decision.

## C. Retrieval protocol: broad first, then targeted

### C1. Goal-to-query planning

Extract disease/phenomenon; **user-required** process; entity class; target outcomes; expressly constrained context; unfilled choices. Generate **scientific questions first**, then database-specific queries.

**Orientation search intents** (families, not a fixed number of queries):
1. Disease/phenomenon observations and major mechanisms.
2. Required process and its measured biological functions, including studies outside the disease context.
3. Competing explanations, counterexamples, and cases of opposite direction.
4. Available experimental models, assays and actual endpoints.
5. Closest broad prior work and foundational/recent developments.

**ALS illustration (proposed requests; not claims that these exact database queries were run):**

| Intent | PubMed-oriented query example | Avoided bias |
|---|---|---|
| Disease | `(ALS[tiab] OR "amyotrophic lateral sclerosis"[tiab]) AND (nucleoporin*[tiab] OR "nuclear pore"[tiab])` | Does not force NUP50 or a kinase |
| Modification | `(nucleoporin*[tiab] OR "nuclear pore"[tiab]) AND (phosphorylat*[tiab] OR kinase*[tiab])` | Finds cross-system mechanistic anchors |
| Alternatives | `(ALS[tiab] OR C9orf72[tiab]) AND ("nucleocytoplasmic transport"[tiab] OR "nuclear pore"[tiab])` | Can find phosphorylation-independent injury |
| Context | `(neurons[tiab] OR "motor neuron"[tiab]) AND (nucleoporin*[tiab] OR "nuclear pore"[tiab])` | Allows opposing cell-state findings |
| Measurement | `(nucleoporin*[tiab] OR NUP50[tiab]) AND ("nuclear import"[tiab] OR "nuclear export"[tiab])` | Later extension after the entity appears in sources |

Query syntax is an example, not a verified successful execution record. Before execution, check each provider's actual syntax and source restrictions. `SearchRequest` stores engine, canonical query, filters/scope, timestamp, pagination, status and results. Do not fabricate a search total from a ranked web search.

### C2. Search, screening, and selection

1. Execute through the shared LiteraturePort; record each actual request, pagination, provider and status via M15.
2. Resolve DOI/PMID, title, version, and **study_family_id**. A preprint and later journal article are not independent confirmations. Companion reports with uncertain participant/data overlap are not assumed independent.
3. Triage by title and abstract, prioritizing: direct study of the goal phenomenon; relevant mechanistic experiment; negative/competing explanation; necessary experimental method; closest prior art. Retain reason for inclusion **and exclusion** where consequential.
4. Include both foundational and recent research. Do not use a default recent-years-only filter or systematic exclusion of negative findings.
5. Follow citations **when a scientifically important mechanism or contradiction remains uncovered**, not by arbitrary citation depth.
6. If a particular gap remains under-supported, make a targeted follow-up request specifying what its outcome can change. Avoid repeating equivalent queries just to accumulate papers.

### C3. Reading-depth policy

| Material role | Minimum inspect | Escalation trigger |
|---|---|---|
| Broad topical screening | Title/abstract | Candidate anchor or major opposing explanation |
| Simple observation explicitly in abstract | Abstract, precise claim bound | More specificity, study conditions missing |
| Critical mechanism starting point | Results and matching figure/legend; essential Methods | Mechanism hinges on particular mutant, target engagement, control, readout |
| Important negative or contradictory evidence | Actual comparison and endpoint sections | Results from distinct contexts appear inconsistent |
| Indispensable experimental detail | Figure/Methods and supplementary material as needed | Phosphosite, assay direction, species/isoform, effect magnitude |

Full text is **selective**, not mandatory for every article. If missing, mark what cannot be asserted and either (a) narrow the anchor to what the abstract supports, (b) seek accessible corroboration, or (c) request additional retrieval. Never claim an unread figure or method was verified.

### C4. What reader extracts (one card per material finding)

`finding_id; source_id; study_family_id; source_version; locator; access_level; representation; species; biological_system; cell_state; intervention_or_comparison; measured_endpoint; reported_result; relevant_negative_results; author_interpretation; excluded_inference; transfer_assumptions; source_view_ref; retrieval_limitations`.

The model must never silently convert depletion into phosphorylation, transport receptor migration into cargo flux, cell viability into clinical benefit, or a postmitotic extrapolation into a proven fact.

### C5. Output of orientation synthesis

`OrientationPacket` holds a neutral goal restatement; compact phenomenon map; contextual findings; alternative explanations; **unranked** research gaps; areas not yet searched; and source catalogue. It is an input to seed planning, not a Hypothesis and not an M05 EvidenceDossier. It should not use `known novel` or `proved absent` for prior-art status.

## D. Seed protocol and independence

1. Plan two directed seed questions from different **causal bottlenecks** for the first *method trial*, plus one open branch. Count is experimental, not a production rule.
2. Directed questions identify observed starting points and unresolved links, but **do not supply the model with completed candidate mechanisms or outcomes**.
3. The open branch receives the original goal, a neutral orientation stripped of prioritized gaps, source catalogue, and tools. It conducts its own searches and may discover protective/compensatory or noncanonical directions. Its specific direction **emerges after searching**.
4. Seed retrieval may share immutable source bytes and DOI cache. The open branch cannot view sibling queries with inferred answers, sibling gap rankings, generation outputs or post-generation critique.
5. Log each seed's final **actual visible input manifest**. After first-pass generation, compare mechanism identity using: causal bottleneck; necessary new link; context; alternative; and experimental discriminator. Do not silently delete duplicates; preserve audit records and classify duplicates for later policies.
6. Never claim statistical/model independence merely because of separate prompts. The intended guarantee is **input separation**; independent execution and its effectiveness are empirical questions.

**ALS seed illustration:** D1: NUP50 abundance–phosphorylation interaction in transport recovery; D2: NUP98 structure/permeability in nondividing neurons; O1 initially has **no preselected molecule or metabolic mechanism**. If independent open searching later finds an AMPK–NUP50 metabolic topic, treat that as a newly discovered seed direction, not the content of its starting brief.

## E. Background Readiness: an executable decision record

Readiness applies **per seed and per requested hypothesis specificity**. It is NOT an estimate of scientific truth, novelty, or eventual Admission.

| Criterion | Required observation | Example failure and next action |
|---|---|---|
| `goal_interpretable` | A scientific question and user constraints are clear | Resolve essential ambiguity in prepare_goal |
| `anchor_traceable` | At least one genuinely relevant factual starting observation is supported within actual visible source scope | Obtain a source or narrow unsupported assertion |
| `context_preserved` | Critical source conditions, intervention, endpoints, negative findings and transfer assumptions are represented | Read Results/Methods or add ContextContrast |
| `alternatives_considered` | Main known competing explanations have been searched/retained at scope appropriate to seed | Targeted opposing query/reading |
| `critical_reading_adequate` | Source detail needed for the intended specificity is actually visible | Retrieve the necessary figure/method or reduce specificity **explicitly** |
| `closest_prior_work_attempted` | At least an initial targeted search for this specific scientific connection is logged | Run a targeted search; do not require exhaustive novelty review |

**Not a hard readiness requirement:** a fully specified discriminating prediction or proof of the new causal link. These are Generation and R1/R2 responsibilities. However, the seed must refer to observable biological quantities and a plausible experimental context; otherwise its aim may be too vague to generate an evaluable candidate.

**Decision rule:**
- `ready`: all essential assertions and required context for the **allowed specificity** are represented, major opposing directions were sought, and traceable sources support the starting premises. Unknown *new* bridges are expected.
- `retrieve_more`: a specifically named missing fact or source detail could change what scientific claim can honestly be generated. Record exact next reading/search and why.
- `unable_to_prepare`: adequate basis cannot be obtained or the direction remains uninterpretable after documented attempts. Preserve as an incomplete seed, **not a disproven hypothesis**.

No fixed paper count or mandatory full-text quota. Re-evaluate only after a real new result, explicit scope change, or resolved access problem. Source acquisition failure remains a technical execution fact, not a finding of zero evidence.

## F. Generation strategies and output

**[DISCLOSED] Nature** describes literature exploration, iterative assumptions, simulated scientific debate and research expansion. **[DISCLOSED] arXiv** describes randomized initial hypotheses with independent/parallel literature research, strong simplicity instructions, and 1.6 generation temperature in a described configuration. Exact production query/reader algorithms are not disclosed.

**[PROPOSED] First comparison:**
- `DIRECT`: goal + seed-specific actual evidence views -> one full candidate.
- `ITERATIVE_ASSUMPTIONS`: same input -> concise **public assumption ledger** of necessary new bridges and how to test them -> one full candidate. The ledger is an output artifact, not hidden chain of thought.
- Debate not in minimal first build; test later only if meaningful benefit remains.

`Hypothesis` minimum: `scoped_claim`, `mechanism_steps` with known vs conjectured status, `conditions`, `evidence_anchors`, `new_causal_links`, `critical_assumptions`, `one_or_more_predictions`, `competing_explanations`, `falsification_conditions`, `validation_concept`, `source_refs`, `known_limitations`, `seed_ref`, `method`, and actual call provenance. Candidate saved immutably before M02; changes require a new candidate identity.

## G. Candidate Ethics and R0

Goal Ethics successful results are **exactly pass/reject**. Missing policy/input blocks execution without a fabricated ethical decision. **Candidate Ethics decision space remains owned by M02 and pending a specific decision; v0.4 does not silently remove its prior incomplete/unknown semantics.** Both stages use actual approved safety policy, not an AI-invented policy.

R0 returns only `proceed_to_R1` or `blocked` after a completed review; technical/input failures stay outside these scientific dispositions.

**Block only when evaluation is not meaningful as written:**
1. Explicit hard-goal contradiction that a contextual refinement cannot explain.
2. No identifiable causal scientific proposition (pure slogan or topical suggestion).
3. Necessary propositions are mutually inconsistent in the **same experimental context**.
4. Proposed claim is effectively immune to any imaginable relevant observation.
5. An **indispensable factual premise explicitly attributed to a supplied source** is directly contradicted by the actual visible passage; record exact source and candidate spans. A disputed scientific interpretation is **not** this case.

If a mechanism is unproven, prior art unresolved, a prediction weak but potentially made testable without changing the central claim, or transfer between contexts contested: **proceed with explicit `required_R1_checks`**, not an R0 scientific verdict. R0 does not write a revised candidate, perform a new search, choose a parent or calculate scientific scores.

## H. ALS/AML development use and data honesty

The companion `W1_Complete_Worked_Input_v0.4_PROPOSED.json` demonstrates one complete, **model-visible** transport packet based on v0.3 source-reading records and source identities checked in this study. Its selected views are **paraphrases**, not full-passage reproduction. This is a documentation rendering and readiness illustration, **not** proof a production retrieval and Generation call occurred. No target published ALS hypothesis is supplied as a free-generation answer.

For AML/KIRA6, use a second context-transfer test: AML viability differs across cell lines, while KIT binding, broad binding profiles and HSP60 evidence originate from other experiments. The required behavior is to separate viability **phenotype** from a uniquely causal drug target. No new AML external experimental validation is claimed.

## I. Scientific evaluation protocol (not yet executed)

### Offline protocol checks (no paid models)
- Input isolation: public labels/expected failures/reviewer hints never enter tested model payload.
- Reading scope: abstract-only cards cannot claim unread Results; negative findings stay in ContextContrast.
- Actual packet rendering: every source in model input has an actual source-view snapshot and locator; unknown input length reductions are reported, not hidden.
- Readiness cases: `ready`, `retrieve_more`, `unable_to_prepare`, including a false-premise and an inaccessible-key-method example.
- Seed isolation: open input manifest provably excludes coordinator-selected mechanism, sibling gaps, hypotheses, critiques.
- R0 case fixtures: strong and borderline flaws; unverified ≠ contradicted.
- All prior W0 engineering outcomes remain engineering checks, not scientific validity.

### Later authorized controlled model experiment
First isolate **packet presentation**: same Goal, seed, source excerpts, model, sampling configuration and output fields; compare compact factual summary versus full ContextContrast presentation. Use multiple independently executed calls; mark calls and cost. Blind expert reviewers to condition where feasible. Assess factual citation fidelity, lost negative results, invalid context transfer, testability and unnecessary bridges.

Second isolate **generation method** on the same frozen packet: DIRECT vs ITERATIVE_ASSUMPTIONS; keep all other factors fixed. Evaluate the actual intermediate assumption ledger and whether it reduces extra speculative links without suppressing legitimate novelty.

Third test **exploration policy** at equal total candidate-generation opportunities: directed-only versus directed+open, with independently rendered open context. Primary measure is **distinct credible causal mechanisms**, not count of varied titles. Record prior-art overlap and seed-specific retrieval coverage.

Readiness must be expert-labeled independently, including **false-ready** (missing/false necessary anchor) and **overly conservative** holds. R0 must include borderline candidates and track false blocks. No threshold, model winner, prompt superiority or parameter optimum is frozen without these evaluations.

## J. Page delivery and handoff

W0-T4 is still a separate, not-yet-implemented coding slice; no coding begins from this proposal. After explicit owner approval, it should handle Goal + Goal Ethics with **binary** completed Goal decisions and minimal conditional progression; Generation unimplemented must appear honestly unavailable.

W1 subsequent slices must display actual source retrieval/access and readiness state; saved candidate cards; candidate Ethics/R0 outcomes. Preserve the V5 principle of hypothesis-centered reading while showing real task/source provenance. Frontend refresh is read-only; no fake progress, candidate or Winner. A module's backend implementation is not synonymous with frontend integration or scientific validation.

## K. Decisions for owner

1. Accept Goal Ethics binary `pass/reject` (user already specified); do not automatically simplify Candidate Ethics.
2. Approve the three operations of broad search, focused seed search and context-preserving synthesis as M01's internal method.
3. Adopt **per-seed, specificity-dependent readiness** and protected open branch as proposed experiment designs, not proven performance improvements.
4. Require independent science assessments and controlled comparison before adopting default generation settings.
5. Safety policy for live Goal/Candidate screening remains an explicitly approved external input; this document supplies none.

## Source references

- M00 accepted: `docs/design/m00-accepted-v1.0/01_ARCHITECTURE_BASELINE.md`, `04_MODULE_DEPENDENCY_MAP.md`; PR #4 `docs/M01_M02_PROPOSAL.md`.
- v0.3 deliverables provided in conversation, 2026-11-03; exploratory cases are non-blind development material.
- Nature 2026 Co-Scientist: https://doi.org/10.1038/s41586-026-10644-y ; Supplementary Note 9.1.
- arXiv:2608.26701v1: https://arxiv.org/abs/2608.26701v1 .
- Kosako et al. 2009: PMID 19767751, https://pubmed.ncbi.nlm.nih.gov/19767751/ .
- Megat et al. 2023: PMCID PMC9860017, https://pmc.ncbi.nlm.nih.gov/articles/PMC9860017/ .
