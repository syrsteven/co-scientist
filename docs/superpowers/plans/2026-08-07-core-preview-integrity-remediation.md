# Core Preview Integrity Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the existing deterministic Core Preview kernel into an integrity-closed, resumable, CLI-executable vertical slice whose scientific admission, ranking, budget, convergence, and finalization claims are derived from durable evidence.

**Architecture:** Repair the system in dependency order. Typed Agent results become the only scientific input; admission and projections reduce immutable events; SQLite enforces run, lease, and budget fences; a foreground Worker and CoreRunner execute the same production path used by CLI smoke tests. Existing raw-first ExternalCall, event, tournament, and export components are strengthened rather than replaced.

**Tech Stack:** Python 3.11, Pydantic v2, SQLAlchemy 2, Alembic, SQLite WAL, AnyIO, Typer, httpx, OpenAI Python SDK, PyYAML, pytest, pytest-asyncio, respx, Ruff, mypy.

## Global Constraints

- Python remains `>=3.11,<3.13`; no new runtime framework is introduced.
- Supervisor is the sole authority for task creation, scientific state, admission, stopping, and finalization. Agents only return typed `AgentResult` values.
- External calls preserve `planned → started → raw response persisted → validated → AgentResult submitted → domain result applied`; raw bytes are persisted before parsing.
- Scientific events changed by this remediation use the event versions specified below. Unsupported scientific event versions fail closed; pre-`0003` development Runs are not executed.
- A task claim and its budget reservation are one SQLite transaction. Provider execution references that reservation and never creates a second reservation for the same logical task.
- Every ExternalCall mutation and scientific result application validates the current task lease token and attempt.
- `running` permits exploration; `paused` does not claim; `stopping` permits only settlement of submitted results and finalization; terminal Runs reject new scientific mutations.
- Non-decisive matches never update Elo. Ratings remain comparable only within one frozen TournamentEpoch contract.
- Cost may be configured as unlimited, but model calls, tokens, latency, raw artifacts, and cost entries are always recorded.
- API keys and other secrets never enter Run manifests, events, prompts stored for export, logs, or evidence bundles.
- The Core Preview remains single-instance and developer-facing. FastAPI, SSE, React, DeepSeek, Qwen, Gemini, Claude, GPQA, complete benchmarks, and distributed queues remain excluded.
- Tests must not use a public bypass flag, direct epoch seed, caller-supplied admission verdict, caller-supplied convergence truth, or naked task-state transition in the final vertical slice.
- Every task follows exact RED → GREEN evidence, one focused implementation commit, independent task review, and fix rounds before the next task.

## Scientific Event Version Matrix

| Event | Version after remediation | Rule |
|---|---:|---|
| `HypothesisContentCreated` | 2 | Full immutable content plus system-computed canonical hash |
| `ReviewCompleted` | 2 | Content/plan-bound review, safety, critical flaws, evidence IDs |
| `NoveltyAssessmentRecorded` | 1 | Independent literature novelty object |
| `ProximityAssessed` | 2 | Both content hashes, plan version, duplicate and cluster evidence |
| `MatchEvaluated` | 2 | Content-bound authoritative match; provider winner slot already resolved |
| `MetaReviewCompleted` | 2 | Typed structured feedback and coverage |
| `HypothesisTournamentReady` | 2 | Complete admission evidence snapshot and policy identity |
| Lifecycle, epoch, entry, initial rating, rating update | 1 | Payload remains compatible; reducers still validate supported version |
| Lease, budget, checkpoint, and stop events added here | 1 | New immutable audit contracts |

## Planned File Structure

New focused modules:

- `src/co_scientist/agents/payloads.py` — six scientific result schemas and closed schema registry.
- `src/co_scientist/domain/admission.py` — immutable admission policy, evidence snapshot, reducer, and decision.
- `src/co_scientist/domain/run_mutations.py` — Run-state mutation matrix shared by Supervisor and UoW.
- `src/co_scientist/events/contracts.py` — supported event-version registry and validation.
- `src/co_scientist/ports/task_runtime.py` — lease-fenced task runtime protocol and DTOs.
- `src/co_scientist/adapters/persistence/migrations.py` — Alembic upgrade/current-revision checks used by Application composition.
- `src/co_scientist/runtime/registry.py` — production Skill/provider resolution.
- `src/co_scientist/runtime/worker.py` — single-process foreground Worker.
- `src/co_scientist/runtime/checkpoints.py` — durable budget/convergence checkpoint builder.
- `src/co_scientist/application/config.py` — validated goal/profile resolution and immutable manifest construction.
- `src/co_scientist/runtime/core_runner.py` — production bootstrap/resume/drive loop.

---

### Task 1: Typed Agent Results and Canonical Scientific Content

**Files:**
- Create: `src/co_scientist/agents/payloads.py`
- Create: `tests/unit/agents/test_typed_payloads.py`
- Modify: `src/co_scientist/agents/result.py`
- Modify: `src/co_scientist/agents/executor.py`
- Modify: `src/co_scientist/runtime/external_calls.py`
- Modify: `src/co_scientist/skills/loader.py`
- Modify: `src/co_scientist/domain/hypothesis.py`
- Modify: `src/co_scientist/supervisor/orchestrator.py`
- Modify: `src/co_scientist/adapters/persistence/sqlite.py`
- Modify: `skills/generation/manifest.yaml`
- Modify: `skills/reflection/manifest.yaml`
- Modify: `skills/ranking/manifest.yaml`
- Modify: `skills/proximity/manifest.yaml`
- Modify: `skills/evolution/manifest.yaml`
- Modify: `skills/meta_review/manifest.yaml`
- Modify: `skills/generation/prompts/system.md`
- Modify: `skills/reflection/prompts/system.md`
- Modify: `skills/ranking/prompts/system.md`
- Modify: `skills/proximity/prompts/system.md`
- Modify: `skills/evolution/prompts/system.md`
- Modify: `skills/meta_review/prompts/system.md`
- Test: `tests/contract/skills/test_skill_manifests.py`
- Test: `tests/contract/llm/test_openai_raw_persistence.py`
- Test: `tests/contract/persistence/test_sqlite_event_store.py`
- Test: `tests/contract/persistence/test_sqlite_uow_atomic.py`
- Test: `tests/scenario/fixtures/core_loop_trace.json`
- Test: `tests/scenario/test_crash_boundaries.py`
- Test: `tests/scenario/test_external_call_raw_first.py`
- Test: `tests/scenario/test_external_call_recovery.py`
- Test: `tests/scenario/test_fake_core_loop.py`
- Test: `tests/smoke/test_lens_online_smoke.py`
- Test: `tests/smoke/test_lens_replay_smoke.py`
- Test: `tests/unit/domain/test_hypothesis_models.py`
- Test: `tests/unit/supervisor/test_admission.py`

**Interfaces:**
- Consumes: existing `AgentExecutionContext`, `AgentResult`, `SkillManifest`, `SkillExecutor.execute`, `ExternalCallRunner`, `HypothesisContent`, and raw-first persistence.
- Produces:

```python
CoreOutputSchemaId = Literal[
    "GenerationResultV1",
    "ReflectionResultV1",
    "RankingResultV1",
    "EvolutionResultV1",
    "ProximityResultV1",
    "MetaReviewResultV1",
]

def resolve_output_schema(schema_id: str, schema_version: int) -> type[BaseModel]: ...

CoreScientificResultV1 = (
    GenerationResultV1
    | ReflectionResultV1
    | RankingResultV1
    | EvolutionResultV1
    | ProximityResultV1
    | MetaReviewResultV1
)

def validate_output_payload(
    *,
    status: Literal["completed", "partial", "rejected", "failed"],
    schema_id: str,
    schema_version: int,
    payload: Mapping[str, Any],
) -> CoreScientificResultV1 | NonScientificResultV1: ...

def canonical_hypothesis_bytes(content: HypothesisContent) -> bytes: ...
def compute_hypothesis_content_hash(content: HypothesisContent) -> str: ...
def hypothesis_content_from_draft(draft: HypothesisDraftV1) -> HypothesisContent: ...
```

- `AgentExecutionContext` gains `output_schema_id`, `research_plan_version`, `provider`, and `model_or_tool`. `AgentResult` persists the same fields. `payload` remains frozen JSON for persistence, but construction is permitted only through the typed validator.

- [ ] **Step 1: Add failing model and registry tests**

Create `tests/unit/agents/test_typed_payloads.py` with one valid payload for each schema and parameterized invalid cases:

```python
@pytest.mark.parametrize(
    ("schema_id", "payload"),
    [
        ("GenerationResultV1", {"schema_version": 1, "research_plan_version": 1}),
        ("ReflectionResultV1", {"schema_version": 1, "review_id": "r-1", "extra": True}),
        ("RankingResultV1", {"schema_version": 1, "match_id": ""}),
    ],
)
def test_completed_scientific_payloads_fail_closed(schema_id: str, payload: dict) -> None:
    with pytest.raises(ValidationError):
        validate_output_payload(
            status="completed", schema_id=schema_id, schema_version=1, payload=payload
        )
```

Also assert unknown schema IDs/versions fail, an initial review cannot use `safety_status="not_assessed"`, partial/rejected/failed payloads cannot contain scientific fields, and Ranking never accepts provider-supplied Elo.

- [ ] **Step 2: Add failing full-chain malformed-result tests**

In `tests/scenario/test_external_call_raw_first.py`, drive malformed Generation and Reflection JSON through `SkillExecutor → ExternalCallRunner`. Assert raw artifact persistence succeeds, call becomes `validation_failed`, no `AgentResult` is submitted, no scientific event/cost/task mutation is applied, and provider invocation occurs once.

In `tests/scenario/test_fake_core_loop.py`, persist a syntactically valid but schema-invalid `AgentResult` and call `Supervisor.handle_result`; assert Supervisor rejects it before events, task success, follow-ups, or cost settlement.

- [ ] **Step 3: Run the exact RED selection**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3.11 -m pytest \
  -p pytest_asyncio.plugin -p respx.plugin \
  tests/unit/agents/test_typed_payloads.py \
  tests/unit/domain/test_hypothesis_models.py \
  tests/contract/skills/test_skill_manifests.py \
  tests/scenario/test_external_call_raw_first.py \
  tests/scenario/test_fake_core_loop.py -q
```

Expected: failures prove arbitrary JSON objects pass validation, the registry is absent, forged hashes are accepted, and Supervisor can create malformed scientific events.

- [ ] **Step 4: Implement the six frozen result schemas**

Implement `HypothesisDraftV1`, `GenerationResultV1`, `ReflectionResultV1`, `RankingResultV1`, `ProximityResultV1`, `EvolutionResultV1`, `MetaReviewResultV1`, and `NonScientificResultV1` in `agents/payloads.py`. Every model uses:

```python
model_config = ConfigDict(frozen=True, extra="forbid")
```

Use strict non-empty identifiers, `Literal[1]` schema version, `research_plan_version >= 1`, bounded confidence/duplicate likelihood, `MatchDecision`, and exact winner-slot semantics. A completed status selects the manifest's scientific schema; every non-completed status selects `NonScientificResultV1`.

- [ ] **Step 5: Bind manifest, execution context, and persistence to the schema registry**

Update canonical Skill manifests and prompts to version `0.2.0` and require exact JSON matching the registered `*ResultV1`. Make `SkillExecutor` select its validator from `(manifest.output_schema, context.output_schema_version)`. Persist and cross-check `output_schema_id`, provider, model/tool, plan version, prompt hash, input snapshot, task, Run, and call in SQLite.

`Supervisor.handle_result` must resolve and validate the same schema again from the persisted execution context. It must not trust an in-memory model attached by the worker.

- [ ] **Step 6: Centralize canonical hypothesis content**

Move canonical document construction and SHA-256 computation to explicit functions in `domain/hypothesis.py`. Include every scientific semantic field; exclude `content_id`, parent IDs, and supersession metadata. Normalize through sorted UTF-8 JSON with compact separators. Convert Generation/Evolution drafts to `HypothesisContent`, compute the hash, and reject a non-null provider hash that differs.

Emit `HypothesisContentCreated` schema v2 with the full content plus canonical hash. Remove harness-side hash injection.

- [ ] **Step 7: Run focused GREEN and regression tests**

Run the RED command again. Then run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3.11 -m pytest \
  -p pytest_asyncio.plugin -p respx.plugin \
  tests/contract/llm tests/contract/persistence \
  tests/scenario/test_crash_boundaries.py \
  tests/scenario/test_external_call_recovery.py -q -m 'not online'
python3.11 -m ruff check src tests
python3.11 -m mypy src/co_scientist
git diff --check
```

Expected: all selected tests pass; invalid scientific output never leaves raw validation; Ruff, mypy, and diff-check are clean.

- [ ] **Step 8: Commit Task 1**

```bash
git add src/co_scientist/agents src/co_scientist/domain/hypothesis.py \
  src/co_scientist/runtime/external_calls.py src/co_scientist/skills/loader.py \
  src/co_scientist/supervisor/orchestrator.py \
  src/co_scientist/adapters/persistence/sqlite.py skills tests
git commit -m "feat: validate typed scientific results"
```

---

### Task 2: Evidence-Derived Tournament Admission

**Files:**
- Create: `src/co_scientist/domain/admission.py`
- Create: `tests/unit/events/test_admission_evidence.py`
- Modify: `src/co_scientist/domain/review.py`
- Modify: `src/co_scientist/domain/proximity.py`
- Modify: `src/co_scientist/supervisor/orchestrator.py`
- Modify: `src/co_scientist/events/models.py`
- Modify: `configs/profiles/core_preview.yaml`
- Modify: `tests/unit/supervisor/test_admission.py`
- Modify: `tests/scenario/test_fake_core_loop.py`
- Modify: `tests/scenario/test_epoch_rollover.py`

**Interfaces:**
- Consumes: Task 1 typed Reflection/Proximity outputs, system canonical content hash, ordered `DomainEvent` stream, active TournamentEpoch, and `get_rating_policy`.
- Produces:

```python
class AdmissionPolicy(BaseModel):
    version: str
    review_policy: ReviewPolicy
    literature_novelty_required: bool
    duplicate_likelihood_threshold: float

class AdmissionEvidenceSnapshot(BaseModel):
    run_id: str
    hypothesis_id: str
    content_id: str | None
    content_hash: str | None
    research_plan_version: int | None
    admission_policy_version: str
    required_review_stages: tuple[ReviewStage, ...]
    safety_status: Literal["passed", "blocked", "missing", "conflicting"]
    novelty_assessment_id: str | None
    duplicate_detected: bool | None
    epoch_id: str | None
    rating_policy_version: str | None
    missing_requirements: tuple[str, ...]
    conflicting_evidence: tuple[str, ...]
    source_event_sequences: tuple[int, ...]

def reduce_admission_evidence(
    *, run_id: str, hypothesis_id: str,
    events: Sequence[DomainEvent], policy: AdmissionPolicy,
) -> AdmissionEvidenceSnapshot: ...
```

Supervisor replaces the old caller-verdict API with:

```python
def admit_hypothesis(
    self, *, run_id: str, hypothesis_id: str,
    expected_sequence: int, idempotency_key: str,
) -> AdmissionOutcome: ...
```

- [ ] **Step 1: Write failing evidence-reducer tests**

Create ordered event fixtures for one current content revision and assert admission fails for: nonexistent hypothesis, missing initial review, blocked or conflicting safety, unresolved critical flaw, stale content review, wrong plan version, missing/stale novelty, missing proximity, duplicate likelihood at or above threshold, absent active epoch, and unsupported policy.

Add a positive case that returns an immutable snapshot containing exact review IDs, novelty assessment ID, proximity edge/event sequences, content event, epoch event, policy versions, and no missing/conflicting requirements.

- [ ] **Step 2: Write failing Supervisor admission tests**

Replace tests that pass `safety_passed`, `completed_stages`, `novelty_assessment`, `proximity_complete`, or `duplicate`. Assert the public method accepts only metadata and loads evidence itself. Add a sequence-race test: load evidence, append a new content revision on a second connection, and prove admission commit fails with the normal concurrency error.

- [ ] **Step 3: Run the exact RED selection**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3.11 -m pytest \
  -p pytest_asyncio.plugin -p respx.plugin \
  tests/unit/events/test_admission_evidence.py \
  tests/unit/supervisor/test_admission.py \
  tests/scenario/test_fake_core_loop.py \
  tests/scenario/test_epoch_rollover.py -q
```

Expected: reducer/module is absent and the existing API requires caller-computed scientific facts.

- [ ] **Step 4: Implement admission policy and event reducer**

Implement the reducer as a pure ordered-event fold. Bind every review, safety, novelty, and proximity fact to current `hypothesis_id`, canonical content hash, ResearchPlan version, and supported event version. Derive duplicate status only from persisted proximity evidence and `duplicate_likelihood_threshold`.

Reflection application atomically emits `ReviewCompleted` v2 and, when present, `NoveltyAssessmentRecorded` v1. Proximity application emits `ProximityAssessed` v2. Literature novelty remains separate from candidate-space proximity.

- [ ] **Step 5: Replace the Supervisor admission API**

Load events once, resolve the active epoch's admission policy from the immutable Run manifest, reduce evidence, evaluate fail-closed, and commit with the caller's expected sequence. The accepted batch writes:

1. `HypothesisTournamentReady` v2 containing the complete snapshot;
2. `TournamentEntryCreated` v1;
3. `InitialRatingAssigned` v1 using `get_rating_policy(epoch.rating_policy_version).initial_rating` and recording the rating policy version.

Delete the boolean/object overload. Do not retain a compatibility path.

- [ ] **Step 6: Update the Core profile and scenarios**

Add a resolved admission policy ID/version, required review stages, literature novelty requirement, and explicit duplicate threshold to `configs/profiles/core_preview.yaml`. Update fake-loop and epoch-rollover fixtures so typed provider results first create durable evidence, then call the metadata-only admission command.

- [ ] **Step 7: Run GREEN and regression gates**

Run the RED command again, then:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3.11 -m pytest \
  -p pytest_asyncio.plugin -p respx.plugin \
  tests/unit/supervisor tests/unit/events \
  tests/scenario/test_fake_core_loop.py \
  tests/scenario/test_epoch_rollover.py -q
python3.11 -m ruff check src tests
python3.11 -m mypy src/co_scientist
git diff --check
```

- [ ] **Step 8: Commit Task 2**

```bash
git add src/co_scientist/domain/admission.py src/co_scientist/domain/review.py \
  src/co_scientist/domain/proximity.py src/co_scientist/events/models.py \
  src/co_scientist/supervisor/orchestrator.py configs/profiles/core_preview.yaml tests
git commit -m "feat: derive tournament admission from evidence"
```

---

### Task 3: Run Mutation Fences, Idempotent Start, and Complete Projection

**Files:**
- Create: `src/co_scientist/domain/run_mutations.py`
- Create: `src/co_scientist/events/contracts.py`
- Create: `tests/contract/persistence/test_run_state_fences.py`
- Create: `tests/unit/events/test_complete_hypothesis_projection.py`
- Modify: `src/co_scientist/domain/hypothesis.py`
- Modify: `src/co_scientist/events/reducers.py`
- Modify: `src/co_scientist/adapters/persistence/sqlite.py`
- Modify: `src/co_scientist/supervisor/orchestrator.py`
- Modify: `src/co_scientist/export/run_export.py`
- Modify: `tests/contract/persistence/test_sqlite_uow_atomic.py`
- Modify: `tests/scenario/test_finalization_path.py`
- Modify: `tests/unit/events/test_hypothesis_replay.py`
- Modify: `tests/smoke/test_lens_replay_smoke.py`

**Interfaces:**
- Consumes: Task 2 v2 scientific/admission events, current Run/Task transitions, SQLite `BEGIN IMMEDIATE`, and export read snapshots.
- Produces:

```python
class RunMutationKind(StrEnum):
    ENQUEUE_EXPLORATION_TASK = "enqueue_exploration_task"
    ENQUEUE_FINALIZATION_TASK = "enqueue_finalization_task"
    PLAN_EXPLORATION_CALL = "plan_exploration_call"
    PLAN_FINALIZATION_CALL = "plan_finalization_call"
    APPLY_SCIENTIFIC_RESULT = "apply_scientific_result"
    APPEND_SCIENTIFIC_EVENT = "append_scientific_event"
    RECORD_COST = "record_cost"

def validate_run_mutation(
    state: RunState, kind: RunMutationKind, *, task_intent: str | None = None
) -> None: ...

EVENT_SCHEMA_VERSIONS: Mapping[str, frozenset[int]]
def assert_supported_event_version(event: DomainEvent) -> None: ...
```

`HypothesisProjection` becomes a frozen event-rebuilt DTO containing content revisions/current hash, lifecycle, safety evidence, review coverage by content, novelty, proximity/cluster/access issues, entries, rating history, match participation, and created/updated sequence.

- [ ] **Step 1: Write failing Run-fence and create-start replay tests**

For each terminal state, attempt Supervisor enqueue, UoW enqueue/follow-up, call planning, scientific event batch, result application, reservation-independent cost write, and assert no sequence/state mutation. For stopping, prove an already submitted result can settle but all exploration follow-ups are suppressed and only `finalize_run` may be enqueued.

Call `create_started_run` twice with the exact same run/key/manifest/start payload and assert the same `CommitResult`. Reuse the key with a changed manifest or payload and assert a stable conflict; an orphan existing Run without initialization commit must fail closed.

- [ ] **Step 2: Write failing complete projection tests**

Replay v2 content, current/stale reviews, safety, novelty, proximity, ready, entry, initial rating, decisive/non-decisive matches, rating updates, clusters, access issues, and a second content revision. Assert stale evidence remains historical but does not apply to the active revision; entry sets `tournament_active`; created/updated sequences are exact.

Assert an unsupported version of a relevant event raises instead of being ignored, and exported projection equals `replay_hypothesis(...).model_dump(mode="json")` byte-for-byte after canonical serialization.

- [ ] **Step 3: Run the exact RED selection**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3.11 -m pytest \
  -p pytest_asyncio.plugin -p respx.plugin \
  tests/contract/persistence/test_run_state_fences.py \
  tests/contract/persistence/test_sqlite_uow_atomic.py \
  tests/unit/events/test_complete_hypothesis_projection.py \
  tests/unit/events/test_hypothesis_replay.py \
  tests/scenario/test_finalization_path.py -q
```

Expected: terminal mutations succeed, exact create-start retry raises a unique-key error, and the projection omits most fields.

- [ ] **Step 4: Implement two-layer Run mutation policy**

Supervisor rejects disallowed commands before constructing work. UoW reads the current Run state inside the same `BEGIN IMMEDIATE` transaction and derives mutation kinds from events, tasks, call plans, external-call application, and cost entries. There is no testing bypass.

Stopping result settlement must remove exploration follow-ups before the batch. Terminal state rejects all new scientific writes even if a caller bypasses Supervisor.

- [ ] **Step 5: Make create-start exactly replayable**

Add a run-initialization fingerprint covering run ID, full canonical manifest, RunStarted event type/version/payload, and idempotency key. Under `BEGIN IMMEDIATE`, check an existing matching initialization commit before attempting insert. Return exact replay; reject changed input or orphan state.

- [ ] **Step 6: Implement the complete canonical projection**

Add focused immutable nested projection models and exhaustive reducer branches for the version matrix. Validate content/plan/epoch relationships while reducing. Update `SqliteRunReadModel.hypothesis_projections` to call only the canonical reducer and delete any duplicate projection logic.

- [ ] **Step 7: Update fixtures and run GREEN/regression gates**

All tests that create a Run and then enqueue or plan work must first enter `running`; do not add a bypass. Update lens export assertions to expect `tournament_active`, safety, novelty, entry, rating, match, cluster, and sequence data.

Run the RED command again, then:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3.11 -m pytest \
  -p pytest_asyncio.plugin -p respx.plugin \
  tests/unit/events tests/contract/persistence \
  tests/scenario/test_finalization_path.py \
  tests/scenario/test_fake_core_loop.py \
  tests/smoke/test_lens_replay_smoke.py -q -m 'not online'
python3.11 -m ruff check src tests
python3.11 -m mypy src/co_scientist
git diff --check
```

- [ ] **Step 8: Commit Task 3**

```bash
git add src/co_scientist/domain src/co_scientist/events \
  src/co_scientist/adapters/persistence/sqlite.py \
  src/co_scientist/supervisor/orchestrator.py \
  src/co_scientist/export/run_export.py tests
git commit -m "fix: enforce run integrity and complete projections"
```

---

### Task 4: Migration 0003, Atomic Task Leases, and Budget Reservations

**Files:**
- Create: `alembic/versions/0003_worker_leases_budget_reservations.py`
- Create: `src/co_scientist/ports/task_runtime.py`
- Create: `src/co_scientist/adapters/persistence/migrations.py`
- Create: `tests/contract/persistence/test_sqlite_task_leases.py`
- Create: `tests/contract/persistence/test_sqlite_budget_reservations.py`
- Create: `tests/contract/persistence/test_sqlite_migrations.py`
- Modify: `src/co_scientist/domain/task.py`
- Modify: `src/co_scientist/domain/budget.py`
- Modify: `src/co_scientist/adapters/persistence/sqlite.py`
- Modify: `configs/profiles/core_preview.yaml`
- Modify: `tests/contract/persistence/test_sqlite_event_store.py`
- Modify: `tests/contract/persistence/test_sqlite_uow_atomic.py`

**Interfaces:**
- Consumes: Task 3 Run fences, existing task owner/expiry/attempt columns, Run manifest, event/UoW atomic commit, and frozen budget policy.
- Produces:

```python
class BudgetEstimate(BaseModel):
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal("0")
    hypotheses: int = 0
    matches: int = 0

class BudgetUsage(BudgetEstimate):
    pass

class TaskLeaseFence(BaseModel):
    run_id: str
    task_id: str
    lease_token: str
    attempt: int

class ClaimedTask(TaskLeaseFence):
    worker_id: str
    idempotency_key: str
    intent_type: str
    payload: Mapping[str, Any]
    reservation_id: str
    heartbeat_at: datetime
    lease_expires_at: datetime
    max_attempts: int

class ClaimOutcome(BaseModel):
    status: Literal[
        "claimed", "no_task", "paused", "stopping_no_finalization",
        "terminal", "budget_exhausted",
    ]
    task: ClaimedTask | None = None

class LeaseRecovery(BaseModel):
    task_id: str
    expired_attempt: int
    action: Literal["requeued", "exhausted"]

def claim_next_task(
    self, *, run_id: str, worker_id: str, lease_token: str,
    now: datetime, lease_duration: timedelta,
    allowed_intents: AbstractSet[str] | None = None,
) -> ClaimOutcome: ...

def heartbeat_task(
    self, *, fence: TaskLeaseFence, now: datetime,
    lease_duration: timedelta,
) -> ClaimedTask: ...

def recover_expired_leases(
    self, *, run_id: str, now: datetime, limit: int = 100,
) -> tuple[LeaseRecovery, ...]: ...
```

- [ ] **Step 1: Write migration shape and revision tests**

Assert `0002 → 0003` and fresh `upgrade head` create the same columns, indexes, constraints, and Alembic revision. Assert Application migration helpers detect head and return a stable diagnostic for a Run whose manifest lacks `execution_contract_version: 3`.

- [ ] **Step 2: Write failing lease and budget race tests**

Use two SQLite connections/threads to prove only one worker claims a task, only one of two tasks can reserve the final model-call budget, and injected reservation failure rolls back lease fields, attempt, events, and Run sequence. Test old token/attempt heartbeat and acknowledgement rejection, expiry requeue, and max-attempt exhaustion.

- [ ] **Step 3: Run the exact RED selection**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3.11 -m pytest \
  -p pytest_asyncio.plugin -p respx.plugin \
  tests/contract/persistence/test_sqlite_event_store.py \
  tests/contract/persistence/test_sqlite_migrations.py \
  tests/contract/persistence/test_sqlite_task_leases.py \
  tests/contract/persistence/test_sqlite_budget_reservations.py \
  tests/contract/persistence/test_sqlite_uow_atomic.py -q
```

Expected: migration and task runtime modules are absent; current `pending → leased` leaves token/heartbeat/max attempts unset and has no reservation.

- [ ] **Step 4: Implement migration `0003`**

Add task columns `lease_token`, `heartbeat_at`, and `max_attempts DEFAULT 3`; retain existing owner, expiry, and attempt. Add non-negative attempt/max-attempt checks, token uniqueness, claimable and expiry indexes.

Create `budget_reservations` with estimates/actuals for model calls, input/output tokens, USD cost, hypotheses, and matches; state `reserved|settled|released`; version/timestamps; unique `(run_id,idempotency_key)`, `(run_id,task_id)`, and non-null external call; non-negative/state consistency checks; Run/Task foreign keys; Run/state and Task indexes. Add unique `(run_id,external_call_id)` to cost entries.

Extend `BudgetPolicy` with `max_input_tokens` and `max_output_tokens`. Preserve `None` as explicit unlimited and reject negative finite limits.

- [ ] **Step 5: Implement atomic claim plus reservation**

In one `BEGIN IMMEDIATE`: validate Run state, select a pending authorized task deterministically, load task `BudgetEstimate` and Run `BudgetPolicy`, aggregate settled plus active reservations, reject over-budget work, create or exact-replay one reservation, set lease owner/token/heartbeat/expiry, increment attempt, and append `TaskLeaseClaimed` plus `BudgetReserved` events.

Finalization tasks use an explicit zero estimate but still receive a lease and reservation record.

- [ ] **Step 6: Implement heartbeat and recovery CAS**

Every lease operation compares run/task/token/attempt. Recovery turns an expired lease back to pending and emits `TaskLeaseExpired` plus `TaskRequeued`, or marks it exhausted when attempt reaches max. A new claim generates a new token and permanently invalidates the previous worker.

- [ ] **Step 7: Run GREEN, migration, and regression gates**

Run the RED command again, then:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3.11 -m pytest \
  -p pytest_asyncio.plugin -p respx.plugin \
  tests/contract/persistence tests/unit/domain/test_budget.py -q
python3.11 -m ruff check src tests alembic
python3.11 -m mypy src/co_scientist
git diff --check
```

- [ ] **Step 8: Commit Task 4**

```bash
git add alembic/versions/0003_worker_leases_budget_reservations.py \
  src/co_scientist/ports/task_runtime.py \
  src/co_scientist/adapters/persistence \
  src/co_scientist/domain/task.py src/co_scientist/domain/budget.py \
  configs/profiles/core_preview.yaml tests
git commit -m "feat: persist worker leases and budget reservations"
```

---

### Task 5: Fenced Foreground Worker and Lease Recovery

**Files:**
- Create: `src/co_scientist/runtime/worker.py`
- Create: `src/co_scientist/runtime/registry.py`
- Create: `tests/unit/runtime/test_worker.py`
- Create: `tests/scenario/test_worker_lease_recovery.py`
- Modify: `src/co_scientist/runtime/__init__.py`
- Modify: `src/co_scientist/runtime/external_calls.py`
- Modify: `src/co_scientist/agents/executor.py`
- Modify: `src/co_scientist/agents/result.py`
- Modify: `src/co_scientist/adapters/persistence/sqlite.py`
- Modify: `src/co_scientist/supervisor/orchestrator.py`
- Modify: `tests/scenario/test_external_call_recovery.py`
- Modify: `tests/scenario/test_crash_boundaries.py`

**Interfaces:**
- Consumes: Task 4 `TaskRuntimePort`, claim reservation, Task 1 typed executor, existing ExternalCall recovery state machine, and Supervisor result application.
- Produces:

```python
class WorkerStep(BaseModel):
    status: Literal[
        "idle", "completed", "requeued", "exhausted", "paused",
        "stopping", "terminal", "budget_exhausted",
    ]
    run_id: str
    task_id: str | None = None
    attempt: int | None = None

class Worker:
    async def run_once(self, run_id: str) -> WorkerStep: ...
    async def recover(self, run_id: str) -> tuple[LeaseRecovery, ...]: ...
```

`ExternalCallRunner.execute/resume`, all external-call persistence mutations, and `Supervisor.handle_result` gain `reservation_id` and `TaskLeaseFence` where applicable.

`AgentExecutionContext` and `AgentResult` gain `attempt` and `reservation_id`. The reusable lease token is passed separately as `TaskLeaseFence`; persisted artifacts and exports may store only a one-way fence fingerprint, never the token itself.

- [ ] **Step 1: Write failing Worker behavior tests**

Use fake clock, token factory, Skill registry, provider registry, and TaskRuntimePort. Assert Worker only executes existing tasks; it claims, marks running, plans a call bound to reservation/fence, runs typed Skill, applies through Supervisor, and acknowledges. It never creates follow-ups itself.

- [ ] **Step 2: Write failing stale-worker and crash recovery scenarios**

Cover lease expiry during a long provider wait, reclaim by a second worker, and rejection of old worker raw persistence, validation, submission, domain apply, and acknowledgement. Cover restart at raw/submitted/domain-applied boundaries without provider recall or duplicated cost/event. Prove invalid typed output exhausts attempts without scientific pollution.

- [ ] **Step 3: Run the exact RED selection**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3.11 -m pytest \
  -p pytest_asyncio.plugin -p respx.plugin \
  tests/unit/runtime/test_worker.py \
  tests/scenario/test_worker_lease_recovery.py \
  tests/scenario/test_external_call_recovery.py \
  tests/scenario/test_crash_boundaries.py -q
```

Expected: Worker/registry are absent and ExternalCall/Supervisor writes accept no lease fence.

- [ ] **Step 4: Implement registries and Worker execution**

Resolve Skill by `(skill_id,skill_version)` and provider by immutable provider ID. `run_once` recovers expired leases, claims one task, starts it, binds reservation/fence to the call, and drives the existing raw-first runner. The task payload must contain immutable Skill/provider/schema/prompt/input snapshot and budget estimate.

- [ ] **Step 5: Fence every ExternalCall state write**

Add fence validation to call planning, started transition, raw persistence, validation/submission, resume, failure, and domain application. Bind reservation to ExternalCall before provider invocation. Do not only validate at final apply.

- [ ] **Step 6: Add provider-wait heartbeat and retry semantics**

Use an AnyIO task group to heartbeat at the configured interval while awaiting provider I/O. A heartbeat failure cancels local continuation and prevents further persistence. Retry uses a new attempt/token and new ExternalCall identity but reuses the logical task reservation; exact re-entry remains idempotent.

- [ ] **Step 7: Run GREEN and regression gates**

Run the RED command again, then:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3.11 -m pytest \
  -p pytest_asyncio.plugin -p respx.plugin \
  tests/unit/runtime tests/scenario/test_external_call_raw_first.py \
  tests/scenario/test_external_call_recovery.py \
  tests/scenario/test_crash_boundaries.py -q
python3.11 -m ruff check src tests
python3.11 -m mypy src/co_scientist
git diff --check
```

- [ ] **Step 8: Commit Task 5**

```bash
git add src/co_scientist/runtime src/co_scientist/agents \
  src/co_scientist/adapters/persistence/sqlite.py \
  src/co_scientist/supervisor/orchestrator.py tests
git commit -m "feat: run tasks through fenced workers"
```

---

### Task 6: Durable Budget, Convergence, and Resumable Finalization

**Files:**
- Create: `src/co_scientist/runtime/checkpoints.py`
- Create: `tests/unit/runtime/test_checkpoint_builder.py`
- Create: `tests/scenario/test_budget_enforcement.py`
- Create: `tests/scenario/test_convergence_checkpoint.py`
- Create: `tests/scenario/test_resumable_finalization.py`
- Modify: `src/co_scientist/domain/budget.py`
- Modify: `src/co_scientist/domain/convergence.py`
- Modify: `src/co_scientist/adapters/persistence/sqlite.py`
- Modify: `src/co_scientist/runtime/external_calls.py`
- Modify: `src/co_scientist/runtime/worker.py`
- Modify: `src/co_scientist/supervisor/orchestrator.py`
- Modify: `configs/profiles/core_preview.yaml`
- Modify: `tests/unit/domain/test_budget.py`
- Modify: `tests/unit/domain/test_convergence.py`
- Modify: `tests/scenario/test_finalization_path.py`

**Interfaces:**
- Consumes: Task 4 reservations, Task 5 fence-aware worker, event projections, tournament events, cost entries, frozen anchor set, and Run mutation fences.
- Produces:

```python
class DurableBudgetSnapshot(BaseModel):
    run_id: str
    policy_version: str
    settled: BudgetUsage
    actively_reserved: BudgetEstimate
    hard_limit_reached: bool
    source_reservation_ids: tuple[str, ...]
    source_cost_entry_ids: tuple[str, ...]

class RecordedCheckpoint(BaseModel):
    checkpoint_id: str
    source_sequence: int
    commit: CommitResult

class ConvergenceCheckpointBuilder:
    def build_and_record(
        self, *, run_id: str, expected_sequence: int
    ) -> RecordedCheckpoint: ...

def tick(
    self, *, run_id: str, expected_sequence: int, checkpoint_id: str,
    scientist_action: Literal["soft_stop", "hard_cancel"] | None = None,
) -> TickOutcome: ...
```

`commit_domain_batch` gains optional `lease_fence`, `settle_reservation_id`, and `release_reservation_id`; actual usage is derived inside the transaction from persisted cost/call/scientific events.

- [ ] **Step 1: Write failing durable budget tests**

Test restart-stable snapshots, reserved versus settled non-double-counting, provider call without reservation rejection, idempotent settlement/release, unlimited policy recording, and two-worker budget race. Assert actual totals derive from persisted data rather than caller input.

- [ ] **Step 2: Write failing checkpoint/stop tests**

Build valid and invalid checkpoints. Reject missing anchor membership/comparison IDs, stale epoch/source sequence, changed top-k window, absent cluster snapshot, insufficient minimum coverage, and forged budget totals. Assert Elo plateau alone does not stop. Remove the old public convergence/budget boolean parameters from `tick` tests.

- [ ] **Step 3: Write failing resumable finalization tests**

Inject crashes after each of `StopSignalObserved`, `StopPolicyTriggered`, `RunStopping`, `FinalizationRequested`, finalization task enqueue/claim/result, and terminal commit. After restart, `ensure_finalization` must find or create exactly one finalization task and finish without duplicate events or cost. Terminal state rejects every lease/call/reservation/scientific mutation.

- [ ] **Step 4: Run the exact RED selection**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3.11 -m pytest \
  -p pytest_asyncio.plugin -p respx.plugin \
  tests/unit/domain/test_budget.py \
  tests/unit/domain/test_convergence.py \
  tests/unit/runtime/test_checkpoint_builder.py \
  tests/scenario/test_budget_enforcement.py \
  tests/scenario/test_convergence_checkpoint.py \
  tests/scenario/test_resumable_finalization.py -q
```

Expected: checkpoint builder and durable reservation settlement are absent; current `tick` accepts forged caller truth; finalization uses naked synchronous transitions.

- [ ] **Step 5: Implement durable budget load/settle/release**

Read reservation and cost rows in one snapshot. On domain application, settle reservation and append `BudgetSettled` in the same transaction as task success, call application, cost, events, and follow-ups. Release with `BudgetReleased` when no provider/scientific effect can occur. Exact retry returns the prior commit.

- [ ] **Step 6: Implement evidence-bound checkpoint construction**

Persist anchor set/member IDs, fixed comparison IDs, top-k IDs and stability window, cluster membership/diversity, novelty plateau, minimum coverage, auxiliary Elo plateau, budget snapshot, unresolved tasks, epoch/plan/ranking contract, and source sequences. Validate all referenced facts before recording.

Extend the Core profile with explicit `minimum_hypotheses`, `minimum_model_calls`, `top_k`, `top_k_stability_window`, `cluster_diversity_window`, and `elo_plateau_window`; freeze these values into the Run manifest and checkpoint policy identity.

- [ ] **Step 7: Replace stopping and finalization orchestration**

`tick` loads the checkpoint by ID and derives `StopDecision`. A stop batch writes signal if applicable, policy trigger with evidence IDs, RunStopping, FinalizationRequested, and one finalization task. `ensure_finalization` is idempotent; `complete_finalization` runs through a normal lease fence and derives complete versus partial from durable unresolved work. Delete naked `stop_and_finalize_partial` task transitions.

- [ ] **Step 8: Run GREEN and regression gates**

Run the RED command again, then:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3.11 -m pytest \
  -p pytest_asyncio.plugin -p respx.plugin \
  tests/unit/domain tests/unit/runtime \
  tests/scenario/test_budget_enforcement.py \
  tests/scenario/test_convergence_checkpoint.py \
  tests/scenario/test_finalization_path.py \
  tests/scenario/test_resumable_finalization.py \
  tests/scenario/test_crash_boundaries.py -q
python3.11 -m ruff check src tests
python3.11 -m mypy src/co_scientist
git diff --check
```

- [ ] **Step 9: Commit Task 6**

```bash
git add src/co_scientist/domain/budget.py src/co_scientist/domain/convergence.py \
  src/co_scientist/runtime src/co_scientist/adapters/persistence/sqlite.py \
  src/co_scientist/supervisor/orchestrator.py \
  configs/profiles/core_preview.yaml tests
git commit -m "feat: derive stopping from durable evidence"
```

---

### Task 7: Production CoreRunner, Application, and CLI Vertical Slice

**Files:**
- Create: `src/co_scientist/application/config.py`
- Create: `src/co_scientist/runtime/core_runner.py`
- Create: `tests/unit/application/test_config_resolution.py`
- Create: `tests/unit/runtime/test_core_runner.py`
- Create: `tests/contract/cli/test_cli_execute.py`
- Create: `tests/contract/cli/test_cli_worker.py`
- Create: `tests/contract/cli/test_cli_rich_export.py`
- Modify: `src/co_scientist/application/commands.py`
- Modify: `src/co_scientist/application/queries.py`
- Modify: `src/co_scientist/application/service.py`
- Modify: `src/co_scientist/cli/app.py`
- Modify: `src/co_scientist/supervisor/orchestrator.py`
- Modify: `src/co_scientist/agents/executor.py`
- Modify: `src/co_scientist/adapters/llm/replay.py`
- Modify: `src/co_scientist/adapters/llm/openai_responses.py`
- Modify: `src/co_scientist/adapters/literature/replay.py`
- Modify: `src/co_scientist/adapters/literature/pubmed.py`
- Modify: `src/co_scientist/export/run_export.py`

**Interfaces:**
- Consumes: Tasks 1–6 typed evidence pipeline, migrations, Worker, checkpoint/finalization, current provider/tool adapters, and rich exporter.
- Produces:

```python
class ExecuteRun(BaseModel):
    goal_file: Path
    profile_file: Path
    provider: Literal["replay", "openai"]

class ResearchGoal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    title: str
    goal: str
    required_causal_chain: tuple[str, ...]
    required_outputs: tuple[str, ...]

class TournamentProfile(BaseModel):
    rating_policy_version: str
    evaluation_rules_id: str
    judge_profile_id: str
    match_mode: Literal["research", "paper_faithful_binary"]
    anchor_count: int

class StopProfile(BaseModel):
    minimum_matches: int
    minimum_hypotheses: int
    minimum_model_calls: int
    top_k: int
    top_k_stability_window: int
    cluster_diversity_window: int
    elo_plateau_window: int
    require_anchor_plateau: bool
    require_top_k_stability: bool
    require_cluster_diversity_plateau: bool

class ProviderProfile(BaseModel):
    llm: Literal["replay", "openai"]
    literature: Literal["replay_pubmed", "pubmed"]

class CoreProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    profile_id: str
    admission_policy_version: str
    review_policy: ReviewPolicy
    literature_novelty_required: bool
    duplicate_likelihood_threshold: float
    tournament: TournamentProfile
    stop: StopProfile
    budget: BudgetPolicy
    providers: ProviderProfile

class ResolvedRunConfig(BaseModel):
    goal: ResearchGoal
    profile: CoreProfile
    manifest: Mapping[str, Any]
    manifest_hash: str
    provider_id: str

class RunExecutionResult(BaseModel):
    run_id: str
    state: RunState
    last_sequence: int
    stop_reason: str | None = None

def resolve_run_config(
    *, goal_file: Path, profile_file: Path,
    provider: Literal["replay", "openai"],
    environment: Mapping[str, str],
) -> ResolvedRunConfig: ...

class CoreRunner:
    async def execute(self, *, config: ResolvedRunConfig) -> RunExecutionResult: ...
    async def resume(self, *, run_id: str) -> RunExecutionResult: ...
    async def drive(self, *, run_id: str) -> RunExecutionResult: ...

class ApplicationService:
    def execute(self, command: object) -> object: ...
    async def execute_async(self, command: object) -> object: ...
    def query(self, query: object) -> object: ...
```

- [ ] **Step 1: Write failing configuration tests**

Assert missing/invalid YAML, ResearchGoal/profile schema errors, unsupported provider, missing replay resources, and online model configuration fail before any Run row. Assert the resolved manifest contains canonical goal/profile/policies/anchors/replay resource hashes/provider non-secret configuration and `execution_contract_version: 3`, but never API keys.

- [ ] **Step 2: Write failing Supervisor bootstrap and CoreRunner tests**

`Supervisor.bootstrap_run` must atomically create/start Run, open initial epoch, and enqueue the initial Generation task. `CoreRunner.execute` drives a fresh replay Run to durable terminal; `resume` continues a non-terminal Run. No test directly commits `TournamentEpochOpened` or transitions tasks.

- [ ] **Step 3: Write failing CLI contract tests**

Use independent Typer invocations and one `--data-dir`:

```text
run execute → run status → run export
```

Assert execute returns Run ID/terminal state, worker resumes an interrupted Run, status is stable JSON, export creates the rich directory bundle, config failures create no Run, and pre-contract Runs produce a sanitized nonzero diagnostic.

- [ ] **Step 4: Run the exact RED selection**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3.11 -m pytest \
  -p pytest_asyncio.plugin -p respx.plugin \
  tests/unit/application/test_config_resolution.py \
  tests/unit/runtime/test_core_runner.py \
  tests/contract/cli/test_cli_execute.py \
  tests/contract/cli/test_cli_worker.py \
  tests/contract/cli/test_cli_rich_export.py -q
```

Expected: production config/CoreRunner and commands are absent; existing start/export are lifecycle-only.

- [ ] **Step 5: Implement configuration resolution and migration-backed composition**

Parse and Pydantic-validate goal/profile, resolve policies/anchor members/replay resources, hash canonical content, and build the immutable manifest before Run creation. `build_application_service` upgrades/validates Alembic head instead of using `Base.metadata.create_all()` as a migration substitute.

- [ ] **Step 6: Implement Supervisor bootstrap and CoreRunner**

Bootstrap the initial epoch/task atomically. Compose registries, Worker, checkpoint builder, Supervisor, literature bridge, and exporter. Drive until terminal, scientist interruption, permanent error, or resumable non-terminal exit. Replay and OpenAI use the same task and Worker path.

Unify SkillExecutor request construction with OpenAI `model`, `user_prompt`, and JSON schema requirements. Provide a production PubMed literature bridge instead of a test-private wrapper.

- [ ] **Step 7: Implement Application commands and CLI**

Add `run execute`, `worker run`, and rich-directory `run export`; retain lifecycle pause/resume/stop/cancel through Application commands. CLI never imports or manipulates SQLite UoW directly. Status/export are usable in a separate process with the same data directory.

- [ ] **Step 8: Run GREEN and regression gates**

Run the RED command again, then:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3.11 -m pytest \
  -p pytest_asyncio.plugin -p respx.plugin \
  tests/unit/application tests/unit/runtime \
  tests/contract/cli tests/contract/llm tests/contract/literature -q -m 'not online'
python3.11 -m ruff check src tests
python3.11 -m mypy src/co_scientist
git diff --check
```

- [ ] **Step 9: Commit Task 7**

```bash
git add src/co_scientist/application src/co_scientist/runtime/core_runner.py \
  src/co_scientist/cli src/co_scientist/supervisor/orchestrator.py \
  src/co_scientist/agents/executor.py src/co_scientist/adapters \
  src/co_scientist/export tests
git commit -m "feat: execute Core Preview through the CLI"
```

---

### Task 8: Lens Replay, Online Gate, Release Invariants, and Documentation

**Files:**
- Create: `examples/lens_regeneration_replay/core_trace.json`
- Create: `examples/lens_regeneration_replay/pubmed_search.json`
- Create: `examples/lens_regeneration_replay/pubmed_summary.json`
- Create: `configs/profiles/core_preview_online.yaml`
- Modify: `configs/profiles/core_preview.yaml`
- Modify: `examples/lens_regeneration_goal.yaml`
- Modify: `src/co_scientist/adapters/llm/replay.py`
- Modify: `src/co_scientist/adapters/literature/replay.py`
- Modify: `src/co_scientist/export/run_export.py`
- Modify: `tests/smoke/test_lens_replay_smoke.py`
- Modify: `tests/smoke/test_lens_online_smoke.py`
- Modify: `tests/scenario/test_core_release_invariants.py`
- Modify: `tests/scenario/test_crash_boundaries.py`
- Modify: `tests/contract/llm/test_openai_online.py`
- Modify: `tests/contract/literature/test_pubmed_online.py`
- Modify: `docs/core-preview.md`

**Interfaces:**
- Consumes: the complete production CLI path from Task 7, typed replay resources, fenced runtime, checkpoint/finalization evidence, complete projections, and deterministic rich export.
- Produces: one researcher-runnable Core Preview release gate and evidence bundle with budget, checkpoint, stop, lease audit, scientific provenance, and deterministic bytes.

- [ ] **Step 1: Write the replacement CLI-hosted lens replay smoke RED**

Replace the test-only `LensReplayHarness` orchestration with independent CLI invocations against a temporary empty data directory. Assert `run execute` reaches terminal, `run status` reports the same state/sequence, and `run export` produces a traceable ranked result.

Scan the smoke source and fail if it directly calls UoW epoch seed, `transition_task`, caller admission verdicts, `ConvergenceSnapshot`, or `apply_finalization`.

- [ ] **Step 2: Add release invariant negative controls**

Persist one real violation per invariant and prove the report becomes nonzero or export fails: stale lease accepted, call without reservation, oversubscribed/duplicate reservation, stop without valid checkpoint, stopping without recoverable finalization, terminal mutation, projection mismatch, direct bootstrap/epoch bypass, non-decisive rating update, cross-epoch match, novelty from Proximity, and raw artifact/call mismatch.

- [ ] **Step 3: Add typed production replay resources**

Move replay resources out of `tests/`. Provide schema-valid six-agent results and PubMed responses for the approved lens goal. Profile references the resources; Application freezes source path provenance and content hashes. Tests do not inject provider results programmatically.

- [ ] **Step 4: Extend rich export evidence**

Add deterministic `budget_reservations.json`, `convergence_checkpoints.json`, and `stop_decisions.json`. Add task attempt/max-attempt and lease event history without exporting the current reusable lease token. Manifest binds execution contract, goal/profile/policy/anchor/replay resource hashes, prompt hashes, provider/model/tool identities, raw artifacts, costs, admission evidence, ratings, and final stop evidence.

- [ ] **Step 5: Strengthen the gated online smoke**

Run the same CoreRunner/Worker path with OpenAI and PubMed. Assert provider/model/tool identity, response IDs, raw manifests, exact one logical cost per applied call, nonzero token usage where applicable, typed validation, reservation settlement, terminal state, and rich export. Gate on credentials, explicit OpenAI model, and explicit network enable flag; absence remains a deselected/unverified result.

- [ ] **Step 6: Run the focused release RED/GREEN selection**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3.11 -m pytest \
  -p pytest_asyncio.plugin -p respx.plugin \
  tests/smoke/test_lens_replay_smoke.py \
  tests/scenario/test_core_release_invariants.py \
  tests/scenario/test_crash_boundaries.py -q -m 'not online'
```

Expected after implementation: all pass through production interfaces with no direct scientific-state seed.

- [ ] **Step 7: Update operator documentation**

Document installation, Alembic/reset policy, replay execution, interruption/resume, status, rich export, budget semantics, online gates, provider costs, evidence bundle layout, current exclusions, and a reproducibility disclaimer. Remove the prior lifecycle-only CLI and test-hosted-smoke disclosure because those limitations no longer apply.

- [ ] **Step 8: Run the complete release gate**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3.11 -m pytest \
  -p pytest_asyncio.plugin -p respx.plugin \
  tests/unit tests/contract tests/scenario tests/smoke -q -m 'not online'
python3.11 -m ruff check src tests alembic
python3.11 -m mypy src/co_scientist
git diff --check
git status --short
```

Expected: all offline tests pass, three quality gates are clean, the temporary-database migration contract proves `0002 → 0003` and fresh `head`, and the worktree contains only the Task 8 implementation before commit.

When all online prerequisites are intentionally provided, run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3.11 -m pytest \
  -p pytest_asyncio.plugin -p respx.plugin \
  tests/contract/llm/test_openai_online.py \
  tests/contract/literature/test_pubmed_online.py \
  tests/smoke/test_lens_online_smoke.py -q -m online
```

Report exact execution or non-execution; never infer live success from mocked contracts.

- [ ] **Step 9: Commit Task 8**

```bash
git add configs examples src/co_scientist/adapters src/co_scientist/export \
  tests/smoke tests/scenario tests/contract docs/core-preview.md
git commit -m "test: certify the Core Preview vertical slice"
```

---

## Final Whole-Branch Review

After all eight task reviews are clean:

1. Generate a review package from commit `18128b9` to the final HEAD.
2. Dispatch a fresh high-capability reviewer against this plan, the remediation design, and the original Core Preview specification.
3. Require explicit verdicts on typed scientific integrity, evidence-derived admission, Run fences, complete replay, task lease fencing, budget/convergence evidence, resumable finalization, production CLI path, raw-first provenance, deterministic export, and scope exclusions.
4. Fix all Critical and Important findings, run one scoped re-review, and adjudicate any residual finding according to the SDD five-round breaker.
5. Run the full release gate again from a clean worktree before any completion claim.
