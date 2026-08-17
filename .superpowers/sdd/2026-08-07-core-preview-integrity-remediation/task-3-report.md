# Task 3 Report: Run Integrity and Complete Projections

## Status

DONE_WITH_CONCERNS. The requested implementation is complete and all behavioral,
regression, full-offline, lint, type, and whitespace gates pass. The only concern
is a broken host Python environment: the unmodified host `click` package prevents
test collection and the host `orjson` namespace makes bare mypy crash. Verification
therefore used the pre-existing, task-local `/private/tmp/cs-task2-shims` import
shim. No shim or dependency workaround was added to the repository.

## Base

- Required base: `cc5c88b23f186241b5a12bb34914c6e41d2eed16`
- Verified starting `HEAD`: `cc5c88b23f186241b5a12bb34914c6e41d2eed16`
- Branch/worktree: `/Users/lemintea/Documents/co-scientist/.worktrees/core-preview`

## Valid RED

The specified fence, create-start, and projection tests were written before
production edits.

- The first exact command without a shim failed during collection because the
  host `click` import did not expose `click.command`; this was an environment
  failure, not behavioral RED.
- With only `PYTHONPATH=/private/tmp/cs-task2-shims` added to the exact command,
  the valid behavioral RED was: `37 failed, 48 passed in 8.06s`.
- Failures demonstrated the intended gaps: terminal mutations were accepted,
  stopping leaked exploration follow-ups, exact run-start replay collided on a
  unique key, unsupported versions were accepted, and the canonical projection
  omitted required scientific state.
- A later focused relationship test was also run RED before its production fix:
  a match with no matching content/epoch tournament entry was accepted
  (`1 failed`). It passed after the reducer relationship check was added.
- A paused-state fence was likewise proven RED (`1 failed`) before changing the
  policy to reject new task creation while paused.
- A direct scientific event-store append bypass was proven RED (`1 failed`)
  before extending the same transaction-layer fence to that public UoW path;
  its generic no-Run stream contract remained green (`7 passed` with the focused
  compatibility selection).

## Changed Files

Production:

- `src/co_scientist/domain/run_mutations.py` (new)
- `src/co_scientist/events/contracts.py` (new)
- `src/co_scientist/domain/hypothesis.py`
- `src/co_scientist/events/reducers.py`
- `src/co_scientist/adapters/persistence/sqlite.py`
- `src/co_scientist/supervisor/orchestrator.py`

Tests and fixture migrations:

- `tests/contract/persistence/test_run_state_fences.py` (new)
- `tests/unit/events/test_complete_hypothesis_projection.py` (new)
- `tests/contract/persistence/test_sqlite_uow_atomic.py`
- `tests/unit/events/test_hypothesis_replay.py`
- `tests/unit/domain/test_hypothesis_models.py`
- `tests/unit/supervisor/test_admission.py`
- `tests/contract/llm/test_openai_raw_persistence.py`
- `tests/scenario/test_fake_core_loop.py`
- `tests/scenario/test_core_release_invariants.py`
- `tests/scenario/test_external_call_raw_first.py`
- `tests/scenario/test_external_call_recovery.py`
- `tests/smoke/test_lens_replay_smoke.py`

`src/co_scientist/export/run_export.py` was inspected but did not require a diff:
`SqliteRunReadModel.hypothesis_projections` already delegates exclusively to
`replay_hypothesis(...).model_dump(mode="json")`, so there was no duplicate SQL
projection implementation to remove. `tests/scenario/test_finalization_path.py`
also required no fixture edit and passes unchanged.

## Specification Mapping

### Run mutation fences

- Added the exact `RunMutationKind` enum and `validate_run_mutation` policy.
- Supervisor rejects disallowed enqueue/result commands before constructing
  result work.
- SQLite reads the durable Run state inside the same `BEGIN IMMEDIATE`
  transaction that applies domain batches, and fences events, follow-up tasks,
  external-call result application, and costs.
- Direct UoW enqueue and external-call planning paths are fenced transactionally.
- Every terminal Run state rejects new tasks, calls, scientific events, results,
  and cost mutations without changing durable state.
- Paused Runs preserve existing work and reject new task creation.
- Stopping Runs accept already-submitted result settlement, suppress exploration
  follow-ups, and allow only authorized `finalize_run` task/call work.

### Event version contracts

- Added immutable `EVENT_SCHEMA_VERSIONS` for the complete Task 1/2 scientific
  matrix.
- Known scientific event versions fail closed in both UoW batches and canonical
  replay.
- Task 2 admission event versions remain exactly
  `HypothesisTournamentReady` v2, `TournamentEntryCreated` v1, and
  `InitialRatingAssigned` v1.

### Exactly replayable run start

- `create_started_run` fingerprints the Run ID, full canonical manifest,
  `RunStarted` type/version/payload, and idempotency key.
- The exact retry returns the original persisted `CommitResult`.
- Changed manifest/payload/key reuse and orphan existing-Run state fail closed
  with the stable initialization conflict.

### Complete canonical projection

- Added frozen projection DTOs for revisions, review/safety history, novelty,
  proximity, entries, rating history, and match participation.
- Replay retains stale historical evidence while recomputing applicability for
  the current revision.
- Content/plan/epoch/entry/match/rating relationships are checked while reducing.
- Lifecycle, clusters, access issues, current rating, and exact created/updated
  sequences are event-derived only.
- Exported projections use the canonical reducer byte-for-byte after canonical
  JSON serialization.

### Scope preservation

- No Task 4 migration, lease, budget reservation, Worker, or CLI primitive was
  implemented.
- The deferred Task 2 admission-reducer revision-history minor was not broadened;
  only Task 3's required second-content-revision projection coverage was added.
- Task 2 same-key replay and loaded-tip concurrency behavior remains covered by
  the admission regression tests.

## GREEN and Regression Evidence

Final exact focused selection (with the documented import shim):

```text
91 passed in 3.94s
```

Final required affected regression selection (with the documented import shim):

```text
194 passed in 16.44s
```

Expanded offline discovery (`tests/unit tests/contract tests/scenario tests/smoke`
with `-m 'not online'` and the documented import shim):

```text
391 passed, 3 deselected in 25.10s
```

## Static Verification

```text
$ python3.11 -m ruff check src tests
All checks passed!

$ python3.11 -m mypy src/co_scientist
host failure: AttributeError: module 'orjson' has no attribute 'loads'

$ PYTHONPATH=/private/tmp/cs-task2-shims python3.11 -m mypy src/co_scientist
Success: no issues found in 56 source files

$ git diff --check
(no output; exit 0)
```

## Self-Review

- Verified policy checks occur before state-changing SQL and again inside UoW
  transactions for bypass resistance.
- Verified exact idempotent replays remain readable after later state/stream
  advance where that is part of the existing domain-batch contract; initialization
  replay is intentionally stricter and rejects orphan/advanced initialization
  state.
- Verified reducer inputs are authoritative events; no current scientific state
  is copied from caller metadata or rebuilt by SQL.
- Verified all nested projection collections are created afresh on update and
  projection models are configured frozen.
- Verified no repository dependency or compatibility shim was introduced.
- Verified `.planning/` working notes are excluded from the commit.

## Residual Risks

- The machine's globally installed `click` and `orjson` packages are malformed.
  Repository behavior is verified with the narrow existing `/private/tmp` shim,
  but bare commands on this host remain blocked until that environment is repaired.
- Lower-level lease/claim fencing and reservation primitives are deliberately left
  to Task 4, as required by scope.
