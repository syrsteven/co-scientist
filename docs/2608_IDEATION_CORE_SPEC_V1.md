# 2608 Ideation Core Spec v1

**Document status:** FINAL FREEZE PROPOSAL — becomes **FROZEN** only after explicit user approval and a matching canonical `project_state.json` state-sync. This file is not evidence that current code complies.

**Scientific target:** *Accelerating Scientific Research with Gemini in the Real-World*, arXiv:2608.26701v1, **Ideation only**. The predecessor Nature / arXiv:2502.18864v2 paper and Kaimen-Inc/Co-Scientist are references, not the primary scientific specification.

**Decision basis:** Candidate v0.9 (SHA-256 `3359dd2b21e4c0a71d5643a7d27cf731b0553947c67d68dbb8c33ea8a91ab345`), GPT-6 Pro final paper/spec/code adjudication supplied 2026-10-08, the Codex `SPEC_CODE_EVIDENCE_MATRIX.md` (SHA-256 `97033a2387a2f852a7d66ffbba395a32f6b120a7fe63869ef624258e3b7654bc`), and 12 focused source excerpts. Paper attributions in this document reflect the supplied Pro paper review; code observations are static source-audit findings, not runtime proofs.

**Code evidence identity at review:** HEAD `c2ddbda03f84d5a52f46b47d942b2cce710c919b`; tracked diff SHA-256 `1b278fe49a7518fdf0ec9b686a3fbe84ec7d1b404fa0179708b9a0c8241fcfe5`; inventory SHA-256 `30317d0c779f4332e40adb245c20047471be6c98956c9c2c7d3c0ad10c513858` (376 paths). This identifies the **audit snapshot**, not the future implementation worktree. Candidate v0.9 retains its own earlier inventory reference and must not be rewritten.

## 0. Authority, terms, and scope

Normative labels are atomic:

- **[PAPER]** Explicit public-paper mechanism as confirmed in the supplied GPT-6 Pro review; sections referenced include paper §2, Ideation discussion §2.1.1, §2.2 and appendix.
- **[IMPLEMENTATION CHOICE]** A locally frozen choice where the public paper is silent, context-specific, or insufficiently precise. A **baseline profile default** is not a claimed paper parameter.
- **[LOCAL INFRA]** Strict identity, safety of execution, provenance, transport, budget, and recovery invariants. Such infrastructure cannot silently decide scientific validity.
- **[LOCAL OPTIONAL AUDIT]** Additional structured claim/evidence/lineage/proximity verification; by default not required for candidate continuation and not authoritative scientific input.
- **[ENHANCED PROFILE ONLY]** Additional scientific inputs, gates, scoring, or scheduling that change the paper-faithful baseline. Must have a distinct versioned profile.

In scope: the Ideation scientific search lifecycle, explicit baseline decisions, deterministic offline acceptance criteria, and preservation of reliability boundaries. Out of scope: Experimentation, Paper Writing, HOLDOUT, cross-model benchmarking, live provider calls, generalized tool ecosystems, UI redesign, and claims of unpublished implementation equivalence. This spec does **not** certify current implementation compliance.

The lifecycle is **logically ordered** by dependencies. Independent Reflection and Ranking work may run concurrently where valid input/decision boundaries are preserved; a five-agent description does not require five separate processes, models, or API calls. No writing-stage numeric plagiarism/hallucination loss is imported as Ideation fitness.

## 1. Scientific core workflow

**[PAPER]** Screen the top-level research directive; generate independently literature-grounded root hypotheses; apply candidate Ethics; accumulate scientific Reflection critiques; use pairwise Ranking to update TrueSkill ratings; select reproductive parents using UCB; create crossover or reflection-guided mutation offspring; evaluate new candidates; and select the highest-rated eligible hypothesis after the configured evolutionary search. Scientific evaluation considers plausibility, prior research, testability, originality and unjustified complexity; its result is not reduced to a locally fabricated composite score.

**[IMPLEMENTATION CHOICE]** The paper-faithful v1 baseline uses versioned transitions and immutable candidate identity, explicit technical-vs-scientific statuses, and a distinct completion barrier before final selection. Every generated offspring re-enters Ethics/Reflection/Ranking; it does not inherit a parent's numeric rating or admission result.

## 2. Frozen baseline profile

All entries below are versioned baseline implementation choices except those marked as public-paper parameters:

```yaml
profile_id: 2608-ideation-baseline-v1
scope: ideation
literature_backend: pubmed
literature_domain_scope: biomedical
root_slots: 4                           # implementation choice
reproduction_slots_per_transition: 2   # implementation choice
G: 10                                  # paper-reported default; counting convention is local
initial_generation_index: 0           # implementation choice
reproduction_transitions: 10          # implementation choice for G=10
crossover_probability: 0.7            # paper
mutation_probability: 0.3             # paper
ucb_kappa: 1.0                        # paper
tournament_k: 2                       # implementation choice
tournament_contestants: uniform_seeded_without_replacement
ranking_min_valid_decisive_per_candidate: 2
ranking_max_focal_logical_attempts: 6
candidate_safe_redesign_max: 1
trueskill:
  mu0: 25
  sigma0: 25/3
  beta: 25/6
  tau: 25/300
  draw_probability: 0
generation:
  temperature: 1.6                    # paper for Ideation Generation only
  simplicity_instruction: required    # paper
population_retention: cumulative_eligible
final_score: posterior_mean_mu
core_claim_verification_required: false
core_claim_lineage_audit_required: false
core_semantic_proximity_required: false
```

The above is a *normative configuration sketch*, not a claim that an existing parser accepts these exact YAML keys. Codex must translate it into versioned real configuration only after an implementation task is authorized. The run must freeze profile version, seed, sampling algorithm version, prompt/schema/provider/model versions, task boundaries and rating epoch. Existing Pilot/probe profiles must not be silently rewritten.

## 3. Candidate identity, parentage, and critique history

**[PAPER]** Candidates have unique IDs, hypothesis-level parent identifiers for offspring, accumulated critiques and Bayesian skill ratings. Crossover has two distinct scientific parents; mutation has one.

**[LOCAL INFRA]** The scientific candidate body is immutable and content-hashed; updates create new candidate/content IDs. Record `run_id`, `directive_version`, `hypothesis_id`, `content_hash`, `scientific_parent_ids`, creation slot, generation index, request/result identity and rating epoch. Reject stale/wrong/self-referential/cyclic scientific parent references. All derived artifacts are content/version-bound. Parent score, Ethics result, evidence verdict, eligibility, or claim-audit result is never copied as the child's authoritative value.

**[PAPER]** All applicable critiques must actually reach reflection-guided mutation; merely storing reviews in an event log is insufficient.

**[LOCAL INFRA]** Reviews are ordered and bound to hypothesis ID/content hash, review ID, stage/type, event order and source result. Model-facing views preserve multiple critiques from the same stage rather than retaining only the last. A child may receive its *parent's* critiques as generation context, but the child's own review history only contains reviews actually directed at its content. Do not silently merge different hypothesis versions.

## 4. Literature-grounded Generation

**[PAPER]** Each initial hypothesis has its own independently traceable literature-review/Generation context; root generation may proceed in parallel. Post-generation claim search is not a substitute for grounding before generation. The paper's Ideation Generation uses `temperature=1.6` and an explicit preference for simple proposals; this setting is not automatically copied to Ethics, Reflection or Ranking.

**[IMPLEMENTATION CHOICE]** For each of the four planned root slots, create a separately identified research/review task and frozen Generation context. Identical underlying documents or completed identical retrieval requests may be shared/cache-backed, but **one shared review must not be presented as four independent reviews**. Store the actual source set/bundle, scoped retrieval outcome, directive version, provider/model/prompt/schema/config IDs, and what the model saw. Offspring record the exact parent literature, critiques, and any other documents actually included in their own input. Offspring need not automatically run an entirely new search.

**[IMPLEMENTATION CHOICE]** v1 uses existing Supervisor-authorized PubMed/raw-first/EvidenceSnapshot primitives. The backend is initially restricted to biomedical research: this does **not** claim cross-domain literature coverage. No unbounded Worker-directed autonomous retrieval, hidden tool calls, or extra web/arXiv/EuropePMC requirement is introduced. All external retrieval is authorized, durable and accounted; no actual retrieval is authorized by freezing this spec.

Grounding outcomes must remain distinct:

| Grounding state | Generation continuation | Interpretation |
|---|---|---|
| `SUCCESS_NONEMPTY` | Allowed after the exact input is frozen | Source exists; support/novelty is not established |
| `SEARCHED_EMPTY` | Allowed and explicitly flagged | Scoped zero results; **not** evidence-backed, novel, or disproven by that absence |
| `PARTIAL` with a trustworthy usable subset | Allowed; persist omissions/failures and actual subset | Incomplete review, not a complete survey |
| `GROUNDING_UNAVAILABLE` or `PARTIAL` without a usable subset | Do not dispatch Generation for the affected root slot; record technical incompleteness | Neither scientific rejection nor zero hits |

**[IMPLEMENTATION CHOICE / execution clarification]** A root slot whose grounding fails does not silently retry or receive an automatic replacement slot. Other independent root slots may continue. The run's **execution completeness** becomes `PARTIAL` if a prescribed slot remains unfulfilled, even if later scientific evaluation finds a useful `best_so_far`. A candidate generated after `SEARCHED_EMPTY` must retain that label; the manuscript/benchmark must not describe it as substantively grounded by nonempty sources. No invented fallback evidence.

## 5. Ethics, safety redesign, and scientific Reflection

**[PAPER]** Top-level directive Ethics precedes Ideation. Candidate-level Ethics applies to each root/offspring; safety rejection is distinct from scientific criticism. Rejected candidate/plan may receive safety feedback for safe redesign.

**[IMPLEMENTATION CHOICE]** Directive decision state is one of:

- `PASS`: allow planned Generation.
- `REJECT`: stop this directive; a user revision creates a *new* directive/run identity and must be screened anew. Do not automatically rewrite the rejected directive.
- `TECHNICAL_UNKNOWN`: pause; no PASS or scientific REJECT is inferred.

**[IMPLEMENTATION CHOICE]** Candidate Ethics may share an output payload/provider call with Reflection, but is independently projected as a content-bound verdict (`PASS`, `REJECT`, `TECHNICAL_UNKNOWN`) with policy/prompt identity and reason. Only the Ethics verdict controls safety admission; a scientific Reflection recommendation of `not pass`, weak novelty, or critical flaws is **not** an automatic baseline eligibility rejection. Reflection must be completed and available as scientific feedback, regardless of its favorability.

**[IMPLEMENTATION CHOICE / baseline profile default]** An Ethics-rejected candidate may receive at most **one** automated, explicitly identified safe redesign within its original scientific proposal slot. Record `redesign_of` separately from `scientific_parent_ids`. New text gets a new hypothesis ID/hash; the original scientific parents remain the scientific parents of a redesigned offspring, and a redesigned root does not acquire fictional crossover parents. Do not redraw an Evolution operator, create another generation, or grant another ordinary proposal slot. A second rejection closes that slot. Safety-rejected content never enters Ranking or the parent pool. A technical Ethics failure is not an authorization to redesign and is not PASS.

**[PAPER]** Negative Reflection critiques remain meaningful evaluation/feedback for Ranking and future mutation; they are not an independent science-pass hard gate. Additional Ideation constraints against fictitious equipment, unsupported derivative claims or implausible complexity may be expressed via prompting and scientific critique, not transplanted writing-stage numeric penalty formulas.

## 6. Pairwise Ranking and TrueSkill

**[PAPER]** Valid, decisive pairwise science comparisons update TrueSkill Bayesian ratings. TrueSkill represents each candidate via `(mu, sigma)`. Pair scheduling is a distinct policy from UCB parent selection. `kappa=1.0` is a paper value for UCB, **not** a pairing requirement.

**[IMPLEMENTATION CHOICE]** The frozen TrueSkill environment is `mu0=25`, `sigma0=25/3`, `beta=25/6`, `tau=25/300`, `draw_probability=0`. Each new candidate receives a fresh prior. Apply exactly one rating update per valid decisive match in deterministic committed-match order, not model response-arrival order. Track candidate/content pair, prompt/comparison context, match ID, orientation, decision, prior/posterior, rating epoch and replay identity. Invalid, abstaining, tied, cannot-judge, technical or contract-failed results never generate fabricated loss/draw/win or change rating.

**[IMPLEMENTATION CHOICE]** A *logical attempt* is a separately authorized, durably recorded match opportunity. Such an attempt counts when established, even if its provider result fails or is nondecisive; recovery of the same identity never counts it again. A **valid decisive comparison** counts toward both participants' minimum-valid quota and updates their ratings. Technical, contract, tie, abstain or cannot-judge results count only as attempts, not as valid comparisons. No hidden resend of an unknown-delivery request; a new attempt uses a new explicitly authorized identity.

### 6.1 Separate eligibility sets

**[IMPLEMENTATION CHOICE]** Let `R` be **Ranking-ready** hypotheses: valid core identity, permitted grounding path, Candidate Ethics PASS, Reflection completed, same run/target/rating epoch, without any prerequisite rating quota. Let `P` be the subset of `R` with **at least two valid decisive comparisons** accumulated under the same content identity/rating epoch. `P` is the parent/final-eligible pool. Entering `R` must not require already belonging to `P` (avoid a Ranking deadlock). Negative scientific critiques do not by themselves remove a hypothesis from `R`.

### 6.2 Balanced seeded pairing

**[IMPLEMENTATION CHOICE / baseline profile default]** Required valid quota per candidate is 2; max focal logical attempts per candidate is 6. Pairing from `R` is deterministic:

1. Choose the below-quota focal with the fewest valid comparisons, then fewest focal logical attempts, then frozen seeded priority, then stable hypothesis ID ascending.
2. Select an opponent from `R` excluding the focal; prioritize the fewest historical logical attempts for the **pair**, then the opponent's valid count, then frozen seeded priority, then hypothesis ID ascending.
3. Determine first left/right orientation from the seed, and alternate on subsequent comparisons of the same pair. Orientation balancing does not set scientific quality priority.
4. Exclude UCB, sigma-based information bonuses, scientific quality, semantic cluster/diversity, and offspring count from pairing priority.
5. A quota-complete candidate remains available as an opponent and may receive additional valid updates. Valid counts carry through generations within the same rating epoch; they are not reset per generation.

When a focal reaches 6 logical attempts without quota, record `EVALUATION_INCOMPLETE`; the full planned run cannot be reported as complete and further reproduction must not be silently authorized as though all evaluation had succeeded. If `|R|=1` when a required comparison is pending, record `NO_COMPARABLE_PAIR` and stop that evaluation path; do not lower the quota or promote a prior-only winner. Runtime budgets/caps can also produce explicit partial outcomes. `seed`, sampling/scheduler version, eligible set snapshot, pair/orientation identities and ordered rating updates must be persisted.

## 7. Parent selection via UCB

**[PAPER]** UCB for parent selection is `mu + kappa*sigma` with `kappa=1.0`; uncertainty is an exploration bonus and must not automatically become the final winner score.

**[IMPLEMENTATION CHOICE]** Parents are sampled **uniformly without replacement** from the entire cumulative `P` pool, using a frozen deterministic PRNG/sampling version and recorded eligible set. Tournament `k=2`, `k_eff=min(2, n)`.

- Mutation (`n>=1`): draw `k_eff` contestants; select exactly one parent.
- Crossover (`n>=2`): draw contestants for parent A; remove A from the pool; draw a second tournament independently from the remaining pool to select distinct parent B.
- Tie: sort by **UCB descending**, then **mu descending**, then stable hypothesis ID **lexicographically ascending**. Do not silently reweight by sigma alone, diversity, number of children, previous pair counts or cluster.
- If `n=0`, no reproduction is possible. If crossover is sampled with `n=1`, record `SKIPPED_INSUFFICIENT_DISTINCT_PARENTS`; consume the slot without provider call, operator redraw or compensating mutation. `0.7/0.3` are operator *draw probabilities*, not guaranteed fractions of accepted children.

`P` for tournament is the cumulative set of qualified candidates, not a quality/sigma-truncated active prefix. Explicit budgets and slot counts bound work; no hidden survivor-selection policy substitutes for the frozen baseline.

## 8. Population Evolution and generation boundary

**[PAPER]** Operator selection: crossover probability `0.7`, reflection-guided mutation probability `0.3`. Crossover substantively combines useful content from two different parents; mutation revises one parent in response to applicable accumulated critiques. Unique parent IDs and new offspring IDs are preserved.

**[IMPLEMENTATION CHOICE]** The baseline must not mandate a *new* critical causal bridge, critical claim, or distinguishing experiment for every offspring. Do not impose fixed random `simplify/feasibility/out_of_box/targeted_revision` subtypes as replacements for feedback-guided mutation. Optional extra fields may be diagnostic, never hidden acceptance gates. Whether scientific content actually integrates both parents/responds to critiques is a scientific assessment, not automatically proven by a nonempty provider field or a citation count.

**[IMPLEMENTATION CHOICE / baseline profile default]** G0 has 4 root proposal slots, and each of 10 reproduction transitions has 2 offspring slots. Each slot makes at most one ordinary scientific proposal; duplicate, failed, skipped or rejected slots are not silently replenished. An explicitly authorized single candidate-Ethics redesign is inside the same slot, not a new ordinary operator opportunity. Thus there are **up to** 4 root plus 20 offspring proposal slots, not a guarantee of 24 successful candidates or a fixed number of provider calls.

**[IMPLEMENTATION CHOICE]** G0 is the initial generation; `G=10` means reproduction transitions `G0→G1→...→G10`. G10 offspring must still complete all required candidate Ethics, Reflection, Ranking and rating updates; no G11 reproduction. A generation cap stops only *new reproduction*, never pending terminal evaluation. If execution stops early or a required evaluation is unavailable, record partial/incomplete state; do not manufacture full-G completion.

**[IMPLEMENTATION CHOICE]** Population retention is **cumulative qualified**: eligible historical candidates remain in `R` for comparisons and, once quota-complete, in `P` for parent selection and final selection. Do not remove a candidate solely because of age, mu, sigma, Proximity, offspring count or a fixed active-population size. Exact canonical content duplicates may be deduplicated: keep the attempt/source record but do not create a second independent rating for the same content identity.

## 9. Final selection and run status

**[PAPER]** The Ideation output is the highest-rated hypothesis. The primary paper does not specify the exact final statistic, pool definition or tie-break.

**[IMPLEMENTATION CHOICE]** A **complete** run selects `argmax(mu)` from **all** `P` hypotheses generated in this run under the frozen directive version and rating epoch—not just the newest generation, benchmark top-K, or external anchors. Tie: compare full stored numeric posterior `mu` (no display rounding), then stable hypothesis ID lexicographically ascending. UCB, `mu-k*sigma`, prior-only ratings and benchmark extraction cannot substitute.

**[LOCAL INFRA]** Persist an Ideation-native final selection event/artifact with at minimum: run ID, versioned rule, directive/version, selected hypothesis ID/content hash (or null), exact eligible-pool IDs and validation basis, frozen rating epoch, posterior `(mu,sigma)`, valid/attempt counts, comparison event boundary, execution-completeness status, and provenance. Benchmark ProductionB top-K remains a separate product.

**[IMPLEMENTATION CHOICE]** Outcomes:

| Condition | Execution result | Scientific selection result | Winner |
|---|---|---|---|
| All prescribed slots/transitions and required evaluations finish, `P` nonempty | `COMPLETE` | `FINAL_WINNER` | max-mu candidate |
| Complete lifecycle but `P` empty | `COMPLETE` when no required work remains incomplete | `NO_ELIGIBLE_HYPOTHESIS` | `null` |
| Technical/budget/grounding failure, quota exhausted, or prescribed task unfinished | `PARTIAL` / explicit reason | `INCOMPLETE`; optional `best_so_far` from current `P` | **no final winner** |
| Directive Ethics REJECT | `REJECTED_DIRECTIVE` | `NOT_RUN` | `null` |
| Directive Ethics TECHNICAL_UNKNOWN | `PARTIAL` / `ETHICS_UNRESOLVED` | `NOT_RUN` | `null` |

`best_so_far` is an explicitly labeled interim analysis and never masquerades as a completed-run final winner. If all root slots fail before generating any candidate, record `failure_detail=NO_ROOT_CANDIDATE` under `PARTIAL`; the scientific eligible pool is empty and final winner is null. **This is an explanatory diagnostic subtype, not a replacement for Pro's `NO_ELIGIBLE_HYPOTHESIS` complete-run outcome.** If candidates existed but none satisfied final eligibility, record that distinct fact; never call a technical initialization failure scientific disproof. A failed root grounding slot does not invalidate independently completed candidates but prevents an unqualified full-completeness claim.

## 10. Local audit and scientific-policy boundary

**[PAPER]** Hypothesis-level scientific parent IDs are core. The paper does not require strict local frozen claim targets, one-to-one child claim mapping, exhaustive parent-claim accounting, or a deterministic claim–evidence verifier as an Ideation hard gate.

**[LOCAL OPTIONAL AUDIT]** In `2608-ideation-baseline-v1`, ClaimVerificationV2, ClaimLineageV2 and Semantic Proximity are **not mandatory upstream calls**, hard eligibility gates, parent-selection filters, pairing bonuses, or model-input scientific verdicts. Optional audits may run **after the core output is frozen** and retain `complete/incomplete/invalid` diagnostic status. Injecting their own verdicts into Reflection/Ranking or adding their completeness requirements changes science and is **[ENHANCED PROFILE ONLY]** with distinct identity. Existing audit implementations, old profiles, and old live artifacts are preserved.

**[LOCAL INFRA]** When authoritative SourceUnit/EvidenceSnapshot/EvidenceUnit/EvidenceBinding/audit content is actually supplied, exact ID, content, offset, hash, snapshot and source-result validations remain fail-closed **for that proposed fact**. Reject wrong task/result, stale parent, forged source/evidence binding, wrong schema or content hash, stale fence and invalid provider/domain contracts for the affected core operation. Do not promote an invalid audit fact to model-visible scientific evidence. Independently valid core candidates may continue only through a new **explicitly versioned core/audit separation**, not by catching and ignoring all exceptions.

**[ENHANCED PROFILE ONLY]** Stricter evidence-completeness admission, claim-level lineage-complete admission, mandatory semantic Proximity, proximity-driven pairing/parents, score-penalty fitness, and extra crossover obligations may be studied independently, but may not silently influence paper-faithful core search.

**[LOCAL INFRA]** Exact deterministic canonical-content duplicates can be collapsed for rating identity while preserving the attempted-generation record. That differs from LLM/embedding-based semantic duplicate judgments, which are not active core gates.

## 11. Reliability, replay and trust boundary

**[LOCAL INFRA]** Preserve Supervisor-only authoritative application, raw-first persistence, immutable task/request/response/content identities, strict schema/domain normalization, replay, idempotency, lease/fence, budget reservation, controlled envelopes, provider/model pinning, and immutable A/B historical records. Failed contracts, incomplete retrieval, technical Ethics errors and scientific negatives are separate states. Historical A-only remains `PASS` for its original contract, and historical B-only ClaimLineage V3 remains `CONTRACT_FAIL` due duplicate target assignment—not a scientific rejection. A new baseline never retroactively rewrites historical task/raw/event identities.

**[LOCAL INFRA / pre-live prerequisite]** On a STARTED external call without durable raw and with unknown delivery, the new baseline must transition to `DELIVERY_UNKNOWN / NEEDS_ATTENTION` with reservation uncertainty preserved; it must not automatically call the provider again. Raw persistence must be tested across usage-parser, normalization and domain-validation exceptions. Unknown usage is not zero cost. Recovery of raw/results must not double-call, double-rate, double-create offspring, double-count attempts or double-settle money. Changes are required in implementation/offline acceptance; current normal-path code is **not** claimed to satisfy this invariant.

**[LOCAL INFRA]** Retrieved literature is untrusted data. Model-visible rendering must not grant it instruction/tool authority; render-only quoting/marking must not alter authoritative source bytes, offsets or hashes. Tools are Supervisor-authorized and budget-bound; no implicit fallback, free-form retries, or hidden unaccounted calls.

## 12. Minimum offline acceptance contract

Before claiming **implementation compliance**, not merely document freeze, an offline test suite must demonstrate:

1. Directive `REJECT` and `TECHNICAL_UNKNOWN` cause zero Generation dispatches; candidate Ethics independent of scientific Reflection result; one correctly identified candidate redesign maximum.
2. Four root slots have distinct review/Generation identities; retrieval `SUCCESS_NONEMPTY`, `SEARCHED_EMPTY`, `PARTIAL` and `GROUNDING_UNAVAILABLE` preserve factual differences; no novelty inference; root technical failure does not silently retry or replace a slot. Generation request includes 1.6 + simplicity and pins actual literature inputs.
3. Multiple same-stage critiques survive and actually appear in a later mutation's model context; stale/misattributed critiques do not.
4. Pair scheduler exactly follows the frozen seed/valid-quota rules; valid decisive comparisons update both candidates' TrueSkill once; technical/contract/tie/nondecisive outcomes count attempts but not valid quota or rating. Include 2-valid/6-focal cap, one-candidate case, and deterministic orientation/replay.
5. A fixture whose maximal-mu candidate differs from maximal-UCB candidate proves k=2 seeded parent choice uses UCB, final winner uses mu. Cover singleton mutation, skipped singleton crossover, tie IDs and recorded contestant draws.
6. Cumulative `P` retains old eligible hypotheses without mu/sigma/Proximity trimming. Fixed `G0 + G transitions` semantics and terminal G10 evaluations complete before final selection; no prior-only child selected.
7. Valid identity/provenance remains fail-closed. Optional ClaimVerification/ClaimLineage/Proximity failure cannot silently kill a separate core-valid candidate; an invalid proposed evidence fact is never promoted. Keep historical B replay semantics unchanged.
8. Native final event selects only qualified in-run same-epoch candidates; tie/empty/partial/rejected/no-root conditions produce unambiguous status; ProductionB top-K does not become the scientific winner.
9. No hidden retries, unknown-delivery resend, fabricated usage or double application; crash/replay/fence/ledger invariants hold under deterministic fault injection.
10. New baseline profile/versioned contracts are isolated from legacy Pilot/probe workflows. No HOLDOUT, live provider, PubMed network, or scientific workflow is required for these acceptance tests.

Failure of any implementation test leaves **code compliance unverified/failed**. It does not retroactively invalidate a frozen target specification.

## 13. Implementation batches (not authorization)

- **Batch 1 — Versioned core boundary and gate separation.** Introduce an opt-in baseline mode with isolated core candidate eligibility; preserve exact authority checks; decouple mandatory ClaimVerification/ClaimLineage/Proximity and scientific review-pass gate. No legacy contract mutation. Offline identity/admission/continuation fixtures.
- **Batch 2 — Grounding, Ethics, critique projection.** Independent per-root authorized literature input, Directive Ethics, Candidate Ethics projection/redesign, Generation 1.6+simplicity, ordered cumulative critiques. Mocked retrieval/LLM only.
- **Batch 3 — Rating, reproduction, population.** Valid-quota balanced Ranking, frozen TrueSkill, k=2 UCB parent tournaments, cumulative `P`, critique-guided mutation, minimal crossover/offspring contracts. Seeded/failed/edge-case fixtures.
- **Batch 4 — Terminal selection and full offline acceptance.** Terminal evaluation barrier, native final artifact and partial/best-so-far/empty semantics, full-run deterministic fixture, replay/cost/identity regression. Pre-live reliability gate must separately pass before any provider authorization.

These batches are proposals for separate bounded Codex tasks. This document does not authorize any source/config/test modification, scientific network request, paid model call, live Pilot, HOLDOUT opening, commit or push.

## 14. Public claim and freeze conditions

Until implementation passes independent code/fixture review, describe it as **an in-development public-spec Ideation reimplementation**; do not claim current code is already faithful. After implementation compliance, a defensible scoped statement is:

> A faithful public-spec reimplementation of the Ideation workflow in arXiv:2608.26701v1, with explicitly documented paper-silent implementation choices and a PubMed-based biomedical grounding profile.

Do not claim exact unpublished internal Google behavior or complete cross-domain retrieval coverage.

**Document freeze gate:** (i) user explicitly approves this exact file SHA-256; (ii) Codex writes the exact approved file to `project_management/specs/2608_IDEATION_CORE_SPEC_V1.md`; (iii) matching canonical `project_state.json` records that SHA and M1 PASS; (iv) `CURRENT_TASK.json`/`index.html` sync consistently. The existing v0.9 Candidate, evidence matrices, audit artifacts, and historical A/B runs remain unchanged. **M1 PASS refers to specification freeze, not implementation compliance.**
