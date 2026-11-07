# Co-Scientist V6 — Frontend-to-Backend Data Gap Audit

**Fixed code baseline:** PR #20, `b93c1f5f50159cd61c205720cd95b6e2b267da57` (open at review time).  
**Scope:** Product design review; no repository changes, model calls, live literature requests, or database modifications.  
**Legend:** **A** direct existing API; **B** persisted and recoverable, but a product-oriented aggregation/view model is needed; **C** backend capability missing; **D** scientific/decision strategy not implemented, not just a UI/API issue.

## 1. UI data coverage

| Researcher-facing view | Data required | Status | Current source / precise gap |
|---|---|---|---|
| New Research | Title, question, background, hard constraints, preferences, intended use, reference strings | **A** | `POST /api/brief`, `GET /api/project`, `GET /api/run`; Goal consumes `question`, `hard_constraints`, `preferences`, `background`, `intended_use`, reference strings (`goal.py:validate_brief`, `prepare_input`). |
| New Research | Research focus and objectives | **C** | Extra brief keys may be stored but are not consumed by `prepare_input`; they do not affect Goal/retrieval/generation. Need an explicit contract mapping, not merely an input field. |
| New Research | Uploaded PDFs/manuscripts | **C** | No upload, parsing, persistence or source ingestion; `materials` are only strings. Current HTML demo only shows selected filenames. |
| New Research | Research depth / exploration strategy | **D** | No corresponding global strategies. Removed from HTML demo. P06 has a local `directed`/`open` *seed-generation operation*, not a general workflow strategy. |
| New Research | Maximum research directions | **B/C** | P06 accepts per-operation requested count (Directed <=5, Open <=3), but there is no project-wide enforced limit or autonomous distribution. |
| New Research | Hypotheses per direction / generation modes | **B/C** | P08 generates exactly one candidate per invocation; modes `DIRECT` and `ASSUMPTION_STRUCTURED` exist. No automatic `N per seed` or `Both` controller. Assumption-Structured is a single-call public assumption ledger, **not** iterative reasoning. |
| New Research | Research budget | **C** | `Store.usage()` returns input/output/tool units and partially known cost with explicit unknown counts. No end-to-end USD spend cap / stop policy. |
| My Research | List, open, title, created date | **A** | `GET /api/projects`, `GET /api/project`. |
| My Research | Rename, archive, trash, restore, permanent deletion | **C** | No project mutation endpoints or archive/trash fields. Current UI demo is simulated. |
| My Research | Last updated, actual sort and run progress summary | **B/C** | Can derive latest task/activity timestamps; `projects` currently has no `updated_at`. Prefer a normalized project summary read endpoint. |
| Background Research | Planned exact queries + purpose + unknown coverage | **A** | `GET /api/background`, P03 artifact `queries: [{query, question, why}]`, `coverage_unknowns`. Must not count planned queries as executed. |
| Background Research | Executed search text, status, returned sources, pagination | **A** | `GET /api/literature`; `literature_actions.request.query`, actual `acquisition.items`, `reported_total`, `next_cursor`, execution status, `background_context` when applicable. |
| Background Research | Automatic query selection, relevance triage, pagination stopping | **C/D** | P03 creates a plan only; execution currently manually triggered, no dedicated scientific selection/relevance model or automatic retrieval policy. Provider `reported_total` is not an independently verified article count. |
| Literature | Bibliographic display and access level | **A/B** | Search `SourceRecord` has `source_ref`, citation URL and title; original Europe PMC metadata is retained in details. A normalized bibliographic response simplifies author/year/journal rendering. |
| Evidence Review | Actual reading, source quotes, context, negative observations, interpretation, limitations | **A** | `GET /api/background` P04 finding_cards; saved `material_views` record scope, crops, source URL and text. |
| Evidence Review | Neutral background synthesis, contradictory explanations, questions | **A** | P05 `overview`, `competing_explanations`, `unranked_questions`, `knowledge_edges`, `limitations`, `finding_refs`. No formal evidence quality or novelty scoring. |
| Evidence Review | “Selected papers” and unique “read papers” metrics | **B/C** | Must derive unique `source_ref` from fetched `material_views`, P04 and executed searches; no dedicated automatic selection decisions or selection-score artifacts. Views != studies; hits != returned articles. |
| Research Directions | Seed identity, directed/open type, question, unresolved relationship, known anchor references | **A** | P06 `artifact.seeds` through `GET /api/background` (`seed_id`, kind, question, unresolved_relationship, known_anchor_refs, orientation_ref). |
| Research Directions | Why this seed, scientific rationale, priority | **B/D** | Can show unresolved relationship and linked evidence. No dedicated narrative rationale or scientific priority ranking contract. Do not manufacture confidence scores. |
| Focused Investigation | Search query per seed, results, focused literature readings, packet | **A/B** | `background_context.seed_id` on planned query executions; P04/P05 actions have `seed_id`; `SeedBackgroundPacket` saved. Aggregate by Run + seed. |
| Focused Investigation | Per-seed readiness and follow-up gaps | **A** | P07 `decision`, six `checks`, `premise_gaps`, `hypothetical_unknowns`, `focused_followups`, `allowed_specificity`, limits. |
| Focused Investigation | Automated follow-up loop and per-seed stage status | **C** | No bounded controller to execute P07 follow-ups or advance a seed automatically; progress can be *inferred* from persisted tasks/actions, but is not an existing domain summary. |
| Hypotheses | Candidate title, claim, mechanism, assumptions, source anchors, alternatives, predictions, falsification | **A** | `GET /api/generation` P08 saved `result.candidate`. Exact source refs and seed linkage (`request.seed_id`) exist. |
| Hypotheses | Direct vs Assumption-Structured method | **A** | P08 `request.mode`; both supported individually as single calls. No actual iterative hypothesis refinement/lineage. |
| Hypotheses | Side-by-side comparison | **B** | Both candidate artifacts can be read and displayed together. No backend Ranking score or winner. |
| Initial Review | Candidate Ethics, R0 outcome, blocking defects, uncertainties and R1 checks | **A/B** | `GET /api/candidate-review` has P09/P10 actions + saved artifacts; bind to generation by `generation_ref` and content identity. R0 is factual first-pass gate, **not** overall ranked quality. |
| Initial Review | Candidate-level stage summary | **B** | Derive latest P09/P10 per candidate from actions/statuses; a normalized candidate summary endpoint would prevent frontend misbinding or status confusion. |
| Live Research | Task states, actual timestamps, events and usage | **A/B** | `GET /api/run` tasks/results/usage, history/action statuses and `execution_facts` in export. No unified meaningful research-activity feed today. |
| Live Research | Automatic Start → P03…P10, background continuation, cross-Seed execution | **C** | Manual submit/execute/query endpoints exist but no persistent autonomous Research Run Controller. Current Scheduler executes previously created tasks only; a Run has one write lock and no real multi-Seed parallelism. |
| Live Research | Real Pause / Resume / Stop | **C** | No complete lifecycle endpoints or state machine for a long autonomous run. Explicit recover/query is not user-level Pause/Resume. |
| Live Research | Live push stream / automatic remote ID polling | **C (optional)** | Read-only GET snapshots exist; UI can poll GET. Responses ID query is explicit, with no persisted polling controller/stream. Keep uncertain-send safeguards. |
| Research Timeline | Sequence of persisted scientific operations | **B** | Can construct from `tasks`, `results`, `background_actions`, `literature_actions`, `generation_actions`, `candidate_review_actions`, timestamps; no research-facing event stream/read model. |
| Researcher Notes | Note on run, candidate or fetched material view | **A** | `GET/POST /api/annotations` + SHA-bound targets; no automatic model ingestion. |
| Researcher Notes | Notes attached directly to Seed, planned query or individual finding | **C** | `WorkspaceRecords.targets` only supports `run`, `candidate`, `material_view`. |
| Export | Full immutable record for a single Run | **A** | `GET /api/export?run_id=...`. |
| Export | Research-level export across multiple Runs | **C** | No project-wide export/read model. |
| Production Start | Genuinely screened Goal + approved policies | **C** | Current Goal preparation/screening is deterministic development-only; no configured real Goal adapter or default approved production policy. Hiding controls does not resolve this. |

## 2. Exact existing read endpoints

- `GET /api/projects`, `GET /api/project?id=...`, `GET /api/run?id=...`
- `GET /api/literature?run_id=...`, `GET /api/background?run_id=...`
- `GET /api/generation?run_id=...`, `GET /api/candidate-review?run_id=...`
- `GET /api/annotations?run_id=...`, `GET /api/export?run_id=...`
- Separate read-only historical `GET /api/history` (not an active editable Run).

The frontend can already assemble most read-only scientific pages from these APIs, but a read-only product projection such as `GET /api/research-workspace?run_id=...` would reduce repeated joins and codify cross-module provenance.

## 3. Priority sequence for backend readiness

**P0 — Product truth and data:** Do not treat research focus/objectives as active inputs unless mapped into Goal; do not imply user attachments are ingested. Represent query-plan vs executed queries and fetched vs read sources separately. Remove unsupported “Research Depth” and “Exploration Strategy” controls (done). Decide whether to hide or implement other unsupported settings, especially project-level budget.

**P0 — Actual automation:** Persistent bounded Research Run Controller to create/reuse IDs, plan and execute search, select/retrieve sources, read/summarize, create seeds, do focused searches/P07 follow-ups, generate candidate(s), run P09 then P10; stop at R0 and fail safely. Must not mimic automation with frontend clicks, and must not silently resend uncertain external requests.

**P1 — Product read model:** Unified project/run/seed/candidate/status summaries, meaningful activity feed, normalized source metadata, verified counts, stable per-seed progress. This is primarily aggregation over existing data.

**P1 — Research management and controls:** Rename/archive/trash/restore/permanent delete with preservation of active-task safety, run lifecycle Pause/Resume/Stop and restart/reconnect semantics, project-wide export.

**P2 — Additional user interaction:** Seed-level/finding-level notes, optional relevance annotations, better bibliography and user-uploaded source ingestion. Do not confuse P07 readiness with evidence grading or R0 with Ranking.

## 4. Key implementation references

- `src/co_scientist_next/goal.py`: `validate_brief`, `prepare_input`, Goal dev adapter and screening.
- `src/co_scientist_next/workspace.py`: current HTTP routes.
- `src/co_scientist_next/background_ops.py`: exact P03–P07 artifact contracts.
- `src/co_scientist_next/background.py`: seed/material relationships and snapshots.
- `src/co_scientist_next/literature_runtime.py` and `europe_pmc.py`: query/result/source data.
- `src/co_scientist_next/generation_ops.py`, `generation.py`: P08 fields and frozen seed identity.
- `src/co_scientist_next/candidate_review_ops.py`, `candidate_review.py`: P09/P10 independent decisions and contracts.
- `src/co_scientist_next/store.py` and `workspace_records.py`: database and annotations/export.
- `src/co_scientist_next/scheduler.py`: executes already-created tasks, not autonomous planning.
