# Task 5 report

## Delivered

- Added frozen `BudgetPolicy`, `CostEntry`, and immutable `BudgetLedger` models.
- Added frozen convergence snapshot/decision models and `evaluate_stop` policy.
- Enforced terminal precedence: scientist cancel, scientist stop, then hard budget.
- Requires anchor plateau, top-k stability, cluster diversity plateau, and minimum budget before quality convergence; Elo remains auxiliary only.

## Test-first evidence

The initial focused run was attempted as specified, but pytest plugin autoload failed before collection because the installed `respx` plugin imports an incompatible `click` (`AttributeError: module 'click' has no attribute 'command'`). Re-running with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` produced the expected missing-module collection errors. The first two tests then passed after implementation.

### Mandatory RED evidence

Pre-implementation command:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3.11 -m pytest tests/unit/domain/test_budget.py tests/unit/domain/test_convergence.py -q
```

Relevant output:

```text
ERROR collecting tests/unit/domain/test_budget.py
ModuleNotFoundError: No module named 'co_scientist.domain.budget'
ERROR collecting tests/unit/domain/test_convergence.py
ModuleNotFoundError: No module named 'co_scientist.domain.convergence'
```

This failure was expected: the tests were added before either required production module existed, so collection could not import the `BudgetLedger`/`BudgetPolicy` or `ConvergenceSnapshot`/`evaluate_stop` interfaces.

## Verification

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3.11 -m pytest tests/unit/domain/test_budget.py tests/unit/domain/test_convergence.py -q` — 5 passed
- `python3.11 -m ruff check src/co_scientist/domain/budget.py src/co_scientist/domain/convergence.py tests/unit/domain/test_budget.py tests/unit/domain/test_convergence.py` — all checks passed
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3.11 -m pytest -q` — 27 passed

## Self-review

Reviewed the four implementation/test files and `git diff --check`. No task-scoped issues found. The plugin autoload incompatibility remains an environment concern; the project was not modified to mask it.

## Round 1 corrective TDD evidence

### RED

Command run before the corrective implementation:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3.11 -m pytest tests/unit/domain/test_budget.py tests/unit/domain/test_convergence.py -q
```

Relevant output:

```text
TypeError: BudgetLedger.settle() got an unexpected keyword argument 'hypotheses'
AssertionError: assert 'stop' == 'continue'
3 failed, 5 passed
```

The new ledger tests requested the missing immutable hypothesis/match settlement counters. The new convergence test supplied all boolean quality signals without an anchor-set identifier and exposed that it incorrectly stopped.

### GREEN

Command run after the corrective implementation:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3.11 -m pytest tests/unit/domain/test_budget.py tests/unit/domain/test_convergence.py -q
```

Output:

```text
8 passed in 0.12s
```

### Changes

- `BudgetLedger` now stores immutable `hypotheses` and `matches` counters; `settle` records their deltas and hard-limit evaluation honors `max_hypotheses` and `max_matches` at the threshold.
- `ConvergenceSnapshot` now carries `anchor_set_id`; quality convergence requires a non-empty frozen anchor-set identifier as well as the existing anchor, top-k, diversity, and minimum-budget signals.

### Round verification

- `python3.11 -m ruff check src/co_scientist/domain/budget.py src/co_scientist/domain/convergence.py tests/unit/domain/test_budget.py tests/unit/domain/test_convergence.py` — `All checks passed!`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3.11 -m pytest -q` — `30 passed in 0.19s`
