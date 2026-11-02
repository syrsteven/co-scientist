# Project status — W0-T0 + W0-T1

Updated: 2026-11-02 (Asia/Shanghai). Engineering delivery on independent branch
`codex/w0-t0-t1`; this round does not merge main or accept the full W0 proposal.

## Baseline and scope

- Repository: https://github.com/syrsteven/co-scientist
- Actual fetched `origin/main` and implementation starting commit:
  `7313ca032e4f5f0c84578523e0f5639ad038e7af` (rechecked on 2026-11-02).
  Tree: `3af0c224d664c3df5d1ba7528323f04041b0d6a1`.
- Original user workspace: `/Users/lemintea/Documents/co-scientist`, local main
  `c2ddbda03f84d5a52f46b47d942b2cce710c919b`, with existing tracked/untracked
  changes. They were not reset, staged, committed or copied into this branch.
- Isolated implementation checkout: `/private/tmp/co-scientist-w0`.
  Final delivery head is the PR head (`git rev-parse HEAD` on this branch), not
  an assertion that the original checkout or main contains this implementation.
- No existing repository `AGENTS.md` was found in either checkout. New root rules
  preserve the accepted scientific constraints and identify the new code location.
- Original design packages are under `docs/design/m00-accepted-v1.0/` (29 files)
  and `docs/design/w0-proposed-v0.1/` (2 files). All 31 files are byte-identical to
  the ZIP entries. `docs/design/source-integrity.json` records ZIP/file SHA-256.
  M00 remains `design_accepted`; W0 remains `proposed`; M00 `reference/` is historical.
- Old G3 fixed reference: `7313ca032e4f5f0c84578523e0f5639ad038e7af`.
  Old code, entrypoints and tests are retained. Its representative scientific
  outputs/independent experiment environment are not archived by this task.

This request adopts only the W0 semantics needed for input snapshots, Task/Attempt/
result facts, actual I/O, errors, consumption, retries and recovery. Document text
about future approval is preserved as original design history; this user request
provides authorization for this limited implementation. Other W0 sections remain
future inputs. No cross-module scientific semantic conflict requiring a control
team decision was found within this implementation scope.

## Module state and files

| Area | Actual state |
|---|---|
| W0-T0 | Baselines preserved; AGENTS and this status added |
| M14a | Project/append-only Brief revisions/Run snapshot and fixed policy, optional GoalContext reference |
| M12 | Versioned module registry and persisted mechanical sequence; structured output passed to next Task |
| M15a | SQLite tasks/results/call Attempts, error and retry facts, unknown usage, local replay, recovery |
| M01 Goal preparation / M02 Ethics | Not implemented; no fabricated scientific preparation or screening |
| M01–M11 production science | Not implemented or scientifically validated |
| M09a / M11a / remaining M20a | Proposal retained; no claim of implementation or full scientific scenario coverage |
| Frontend / ranking / evolution / R3 | Not implemented for the new system |

Actual additions:

- `AGENTS.md` and `docs/STATUS.md`.
- `docs/design/README.md`, `source-integrity.json`, and all 31 original design files.
- `src/co_scientist_next/__init__.py`, `contracts.py`, `store.py`, `calls.py`,
  `scheduler.py`, `demo.py`, `__main__.py`.
- `tests/next/test_runtime.py`, `tests/next/test_process_recovery.py`.
- `docs/W0_RUNTIME.md`, `docs/verification/w0-t0-t1.txt`.

The new directory avoids coupling to old `co_scientist` Orchestrator, state/schema,
profiles and dependencies. No existing Python code or packaging configuration was
modified. Existing setuptools discovery includes the new package in the wheel.

## Environment, installation and running

Validated on macOS with Python 3.11.4 and SQLite from the Python standard library.
Tests/lint/build used the existing environment at
`/Users/lemintea/Documents/co-scientist/.venv/bin/python`; use any compatible
Python 3.11/3.12 or conda environment. Creating/using `.venv` is not required.
No new production dependency, environment installation or live API key was needed.

From the PR checkout, replace `python` with the selected interpreter:

```sh
PYTHONPATH=src python -m co_scientist_next --db /tmp/w0-fresh.sqlite
PYTHONPATH=src python -m pytest -q -s tests/next
python -m ruff check src/co_scientist_next tests/next
python -m ruff format --check src/co_scientist_next tests/next
python -m build --wheel --no-isolation
```

Only tests require pytest; lint/build require their existing development tools.
Source execution needs no installation. Full repository installation retains the
old package's dependency requirements; see [runtime guide](W0_RUNTIME.md).

## Executed verification

| Check | Actual result |
|---|---|
| Focused suite `tests/next` | 15 passed, 0 failed, 0 skipped |
| Two-step normal completion | Saved first output → created second task → result 32 → completed |
| Brief edited after Run creation and between steps | Existing Run/task inputs/policy/GoalContext reference unchanged |
| Separate-process boundary resume | PID 78144 → 78145, only second Task executes, 2 total Attempts |
| Hard exit after saved successful call | PID 78146 → 78147, local replay, 1 total external send/Attempt |
| Hard exit during external send | PID 78148 → blocked PID 78149; explicit authorization → PID 78150, original uncertain + linked success |
| Duplicate result delivery | No second result application, downstream Task or external send; conflicting result rejected |
| Module/known-call failure | Run/Task/module and actual error retained; no result or successor; retry preserves error facts |
| Retry/unknown consumption/replay | Linked Attempts; unknown `null`, partial totals with unknown counts; replay adds no charge |
| Atomic result + successor | Injected successor write failure rolls back result/task update; recovery completes |
| Single runtime / unrelated database | Second open rejected; historical/unrelated schema rejected without replacing its tables |
| Source package integrity | Both ZIP hashes and all 31 extracted files verified against actual input ZIPs |
| Ruff check and format check | Passed; 9 Python files formatted |
| Wheel build `--wheel --no-isolation` | Passed |
| Isolated wheel smoke (`python -I`, no source path) | New package ran with standard library, completed with result 32 |
| Authored-file whitespace check | Passed; full diff flags original archived Markdown trailing spaces, preserved for byte fidelity |

Recorded stdout, distinct process IDs and result/send counts are in
[verification evidence](verification/w0-t0-t1.txt). The example uses two deterministic
engineering modules (text length and doubling), not scientific modules. The first
source example was also run directly with system `python3`, without repository
package installation. Initial Ruff/style findings were fixed before the final
passing checks. The full staged whitespace check flagged original design-package
Markdown hard-break spaces; these are preserved rather than rewriting source
attachments. The check excluding those two original package directories passed. Initial sandbox Git fetch DNS failure was resolved by authorized
network access. The optional `gh` command is absent; GitHub tools are used for PRs.

**未运行:** old G3 full suite (no shared runtime code changed), live model/tool API
integration, full browser/frontend acceptance, Python 3.12/Windows validation,
14 complete W0 scientific scenarios, real research Runs, expert scientific
validation, G3 scientific comparison. None is claimed by the passing engineering tests.

## Known limitations and remaining work

- Single process/thread, POSIX local-file lock and SQLite; no distributed worker,
  multiuser workspace or cross-platform lock implementation. Initial schema has
  no migration or G3 compatibility layer.
- Fixed explicit engineering sequence only; scientific branch selection, stopping,
  Admission/Ranking/Evolution and formal scientific terminal semantics remain later work.
  `completed` is execution completion, not scientific validity or a Winner.
- GoalContext and policy are immutable references supplied by future owners, not
  a Goal/policy preparation service. Research materials are referenced JSON, not
  an implemented literature fetch/storage system.
- All external effects must go through stable call keys and explicit JSON adapter
  payloads. Hidden adapter retries or direct module side effects cannot be replayed
  safely. Module code/environment is not automatically snapshotted.
- Successful saved calls replay locally. A send without a saved response blocks
  automatic retry; an explicit reasoned retry may duplicate provider effects.
  No absolute external exactly-once guarantee or automatic provider reconciliation.
- Unknown token/cost/tool usage stays unknown. No live provider accounting or pricing.
  SQLite intentionally contains actual input/output/error data; do not commit Run DBs
  or place credentials in adapter request payloads.
- No remaining cross-module policy decision was required to deliver this skeleton.
  Scientific interfaces, thresholds and expert evaluations remain with their owners.
