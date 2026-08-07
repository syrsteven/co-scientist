# Co-Scientist Core Preview Integrity Remediation Design

**Status:** Approved for implementation planning

**Date:** 2026-08-07

**Branch baseline:** `b772f26`

**Chosen approach:** Integrity-first staged repair

## 1. Purpose

The current Core Preview has a well-tested deterministic kernel, raw-first external calls, SQLite event persistence, epoch-scoped tournament ratings, crash-boundary recovery tests, and deterministic evidence export. A whole-branch review nevertheless demonstrated that the release can still accept malformed scientific results, admit hypotheses without durable evidence, and mutate terminal runs. It also confirmed that durable budget enforcement, convergence evidence, complete hypothesis projections, worker leases, and the production CLI vertical slice remain incomplete.

This remediation closes those gaps without expanding into the Research Preview or Product Preview. The target is a developer-facing Core Preview that a technical researcher can deploy, execute through the CLI, interrupt and resume, and audit from raw provider response through final ranked hypotheses and stopping evidence.

## 2. Scope

### 2.1 In scope

- Six versioned, typed Core agent result contracts.
- Canonical scientific content hashing controlled by the system.
- Evidence-derived safety, review, novelty, proximity, admission, and hypothesis projections.
- Run-state mutation fences and resumable stopping/finalization.
- Persistent task lease fencing, heartbeat, expiry recovery, attempts, and retry policy.
- Persistent budget reservation and settlement.
- Evidence-bound convergence checkpoints and stop decisions.
- A production single-process worker and CoreRunner composition.
- CLI execution, recovery, status, and rich evidence export.
- Lens-regeneration replay smoke through production Application/CLI interfaces.
- Gated OpenAI and PubMed online verification through the same runtime path.

### 2.2 Explicitly out of scope

- FastAPI, SSE, React, and the research cockpit Web client.
- DeepSeek, Qwen, Gemini, and Claude production adapters.
- Distributed queues, multi-node coordination, or exactly-once external effects.
- GPQA, paper-QA substitutes, test-time scaling experiments, and the complete benchmark program.
- Multi-user isolation, hosted secrets management, and production operations.
- Backward-compatible execution of databases created before migration `0003`.

## 3. Approach Decision

Three approaches were considered:

1. **Integrity-first staged repair — selected.** Close scientific evidence and state invariants before adding the durable runtime, then connect the production CLI slice. This preserves the validated kernel and makes each repair independently reviewable.
2. **Vertical-slice rewrite — rejected.** Building inward from a new CLI runner could demonstrate execution sooner, but it would place new orchestration on top of untrusted scientific facts and increase regression risk.
3. **Narrow the release claim — rejected.** Renaming the current code as a library-only preview would avoid runtime work but would not meet the approved Core Preview goal.

## 4. Authority Boundaries

The remediated system has four strict authority layers. A later layer may consume only facts validated and persisted by the earlier layers.

### 4.1 Typed scientific results

Every Skill manifest resolves its `output_schema` through a closed registry to one of:

- `GenerationResultV1`
- `ReflectionResultV1`
- `RankingResultV1`
- `EvolutionResultV1`
- `ProximityResultV1`
- `MetaReviewResultV1`

All models are frozen Pydantic models with `extra="forbid"`. They validate non-empty identifiers, schema and plan versions, current content fingerprints, result-specific status, and exact nested structures. Partial, rejected, and failed execution results use non-scientific payload contracts and cannot produce scientific domain events.

`SkillExecutor` validates raw JSON against the manifest-selected schema before constructing an `AgentResult`. The persisted execution context records the schema identifier and version, prompt hash, provider, and model. `Supervisor.handle_result` selects the same schema from durable task and execution context and validates again before applying any domain event.

Generation content is converted to `HypothesisContent` and canonically serialized by the system. The system computes `content_hash`; a provider-supplied hash, if present, must match exactly and is never authoritative.

### 4.2 Evidence-derived scientific state

Public orchestration commands do not accept scientific verdict booleans. Tournament admission accepts only `run_id`, `hypothesis_id`, and concurrency/idempotency metadata.

An `AdmissionEvidenceSnapshot` reducer loads one consistent durable event stream and binds:

- the latest immutable hypothesis content and canonical content hash;
- the active ResearchPlan and admission policy versions;
- the required review stages and their event/result identifiers;
- the initial safety verdict and unresolved-critical-flaw status;
- the applicable `NoveltyAssessment` identifier;
- proximity evidence, cluster assignment, and duplicate threshold;
- the active TournamentEpoch and rating policy.

Every referenced review, novelty, and proximity result must match the current hypothesis, current content hash, plan version, and policy. Missing, stale, ambiguous, or conflicting evidence fails closed. `HypothesisTournamentReady` records the complete evidence snapshot, policy version, and source event sequences. Entry and initial rating are committed in the same atomic domain batch.

### 4.3 Durable runtime authority

Supervisor and SQLite/UoW both enforce run-state mutation fences:

- `running` may create or claim exploration tasks;
- `paused` may preserve work but may not claim new work;
- `stopping` may settle already-submitted results, suppresses exploration follow-ups, and may run only authorized finalization work;
- terminal states reject new tasks, external-call plans, scientific events, results, and cost/reservation mutations.

Task execution is fenced by a random lease token and monotonically increasing attempt. Claim, heartbeat, result submission, domain application, lease expiry, and retry all compare the current token and attempt. A reclaimed task invalidates every result from the previous worker.

Budget reservations are persistent and idempotent. Work is reserved before claim or provider invocation, settled with actual usage during result application, and released when work cannot execute. Supervisor does not accept caller-computed budget or convergence truth.

### 4.4 Production composition

Application parses and validates the ResearchGoal and profile before creating a Run. It freezes resolved content, policies, anchor membership, provider configuration without secrets, and SHA-256 fingerprints into the immutable run manifest.

`Supervisor.bootstrap_run` atomically creates and starts the Run, opens its initial TournamentEpoch, and creates the initial Generation task. This removes the test-only direct UoW epoch seed.

A single-process `CoreRunner` composes Supervisor, SQLite UoW, Skill registry, provider registry, literature tools, ExternalCallRunner, checkpoint builder, and foreground Worker. Replay and OpenAI/PubMed runs use the same orchestration path and differ only in configured adapters.

## 5. Data Contracts and Migration

### 5.1 Event contracts

Existing events remain when their payload already represents the required fact. New or versioned contracts include:

- `NoveltyAssessmentRecorded`
- evidence-bound `HypothesisTournamentReady`
- `BudgetReserved`
- `BudgetSettled`
- `BudgetReleased`
- `TaskLeaseClaimed`
- `TaskLeaseExpired`
- `TaskRequeued`
- `ConvergenceCheckpointRecorded`
- `StopSignalObserved`
- `StopPolicyTriggered`

Admission and any other materially changed payload receive a new event schema version. Unknown or unsupported versions fail replay. Because this is an unpublished developer database, old runs are not silently upgraded into new scientific semantics.

### 5.2 Complete HypothesisProjection

The canonical reducer rebuilds, from ordered events:

- immutable content revision and current content ID/hash;
- lifecycle state;
- safety status and source evidence;
- review coverage by stage and content revision;
- novelty assessment IDs and active assessment;
- proximity edges, cluster membership, and access issues;
- TournamentEntry per epoch;
- initial/current rating and rating history per epoch;
- match participation and decisive/non-decisive outcomes;
- created and last-updated event sequence.

Stale reviews and assessments do not apply to the current projection. `TournamentEntryCreated` transitions the projection to `tournament_active`. Export consumes this canonical reducer and does not maintain a second projection implementation.

### 5.3 Migration `0003`

The task table gains:

- `lease_token`
- `heartbeat_at`
- `max_attempts`

A `budget_reservations` table records:

- reservation ID and idempotency key;
- run, task, and optional call identity;
- estimated model calls, input/output tokens, cost, hypotheses, and matches;
- actual settled usage;
- `reserved`, `settled`, or `released` state;
- policy version, timestamps, and optimistic version.

Goal, profile, anchor set, and policies remain resolved immutable JSON in the Run manifest; only their source provenance retains input file locations. No secret value enters this manifest.

Development databases may be recreated. Migration tests prove clean upgrade from the current schema to `0003`, but existing pre-`0003` runs are rejected for execution with a stable diagnostic rather than heuristically repaired.

## 6. Worker, Budget, and Convergence

### 6.1 Worker lifecycle

The SQLite task port provides atomic claim, heartbeat, expire/requeue, and terminal acknowledgement operations. Claim uses compare-and-swap semantics under SQLite write locking. Attempt increments only on a successful new lease. Expired tasks are requeued until `max_attempts`; exhaustion produces a durable failure result and may trigger partial finalization according to policy.

The Worker executes one already-created task at a time. It cannot create follow-ups or mutate hypotheses. It resolves the task's immutable Skill/provider context, runs ExternalCallRunner, submits the typed AgentResult, and hands domain application to Supervisor.

### 6.2 Budget enforcement

The resolved profile produces a frozen `BudgetPolicy`. A successful task claim atomically verifies remaining capacity and creates exactly one reservation for the task's estimated work, including its expected provider call when applicable. Provider invocation must reference that reservation and cannot reserve the same work again. Settlement reads persisted CostEntry and scientific events. Restart reconstructs the same ledger from reservations, costs, tasks, hypotheses, and matches.

Unlimited fields remain supported as explicit policy values; unlimited does not disable cost and token recording.

### 6.3 Convergence and stop decisions

A checkpoint builder persists exact evidence for:

- fixed anchor comparisons and anchor-set identity;
- top-k ranking identity and stability window;
- cluster membership/diversity and novelty plateau;
- minimum completed budget/coverage;
- auxiliary Elo improvement plateau;
- current budget ledger and unresolved work.

`Supervisor.tick` accepts only run identity, expected sequence, optional scientist action, and checkpoint identity. It loads and validates the checkpoint. Elo plateau alone never causes automatic quality convergence. A stop decision persists its reason and evidence IDs before finalization begins.

Stopping and finalization are resumable from durable state. A crash after `RunStopping` cannot strand a run: the authorized finalization task is idempotently discovered or created and advanced until the terminal event is committed.

## 7. Application and CLI Vertical Slice

The production CLI exposes:

```text
co-scientist run execute --goal PATH --profile PATH --provider replay|openai --data-dir PATH
co-scientist worker run RUN_ID --data-dir PATH
co-scientist run status RUN_ID --data-dir PATH
co-scientist run export RUN_ID --output PATH --data-dir PATH
```

`run execute` validates configuration, bootstraps a Run, and drives the foreground CoreRunner until a durable stop, partial finalization, scientist interruption, or permanent error. `worker run` resumes an existing non-terminal run. `run export` invokes the deterministic rich evidence exporter.

Application command/query interfaces remain transport-neutral so a future Web/API client can use the same behavior. The CLI does not directly manipulate UoW transitions or reconstruct orchestration logic.

## 8. Error and Recovery Semantics

- Configuration and schema failures occur before Run creation whenever possible.
- Provider bytes are persisted before validation or domain submission.
- Transient provider failures follow explicit retry policy; provider fallback is never implicit.
- Invalid typed output may retry up to `max_attempts`; exhaustion becomes a stable failed or partial outcome without scientific event pollution.
- Stale lease, exhausted budget, terminal mutation, unsupported event version, evidence mismatch, and artifact mismatch fail closed.
- Stable Application/CLI diagnostics do not disclose SQL, credentials, prompt secrets, or provider raw bodies.
- Raw artifacts and evidence bundles retain provenance, provider response identifiers, usage, and cost without storing API keys.

## 9. Implementation Sequence

1. Typed Agent results and canonical scientific content.
2. Evidence-derived admission.
3. Terminal fences, create-start idempotency, and complete HypothesisProjection.
4. Migration `0003`, lease persistence, and budget reservation primitives.
5. Worker runtime and lease recovery.
6. Durable budget, convergence, stopping, and resumable finalization.
7. Application/CoreRunner/CLI vertical slice and rich export integration.
8. Lens replay, gated online verification, whole-branch release invariants, and documentation.

Each task uses an exact RED-to-GREEN cycle, one implementation commit, independent task review, and scoped fix rounds. After all tasks, a fresh reviewer evaluates the entire branch from this specification and the original Core Preview plan.

## 10. Release Acceptance

Core Preview is complete only when all of the following are demonstrated:

- A CLI lens replay run starts from an empty database and reaches durable finalization.
- No test or production path directly seeds TournamentEpoch, admission verdicts, or convergence booleans.
- Deleting projections and replaying events reproduces complete hypothesis state and ratings.
- Restart, stale worker, heartbeat loss, lease reclaim, retry exhaustion, terminal mutation, budget race, and finalization crash tests pass.
- The evidence bundle traces every scientific conclusion through content, review, novelty, proximity, admission, match, rating, prompt, provider, raw artifact, cost, checkpoint, and stop decision.
- Full pytest, Ruff, full-tree mypy, migration smoke, deterministic export, and `git diff --check` pass.
- Online OpenAI/PubMed behavior is reported as verified only when the explicit model, credential, and network gates were actually executed.
