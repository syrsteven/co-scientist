# Task 8 Report: Raw-First ExternalCall Runner and Recovery

## Outcome

Implemented the raw-first external-call runner, immutable provider/result contracts,
canonical request fingerprints, recovery from persisted raw artifacts, and durable
external-call failure states. The runner stops at `agent_result_submitted`; it never
marks `domain_result_applied`.

## RED evidence

1. Initial raw-first scenario:

   ```text
   PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3.11 -m pytest \
     tests/scenario/test_external_call_raw_first.py -q
   ERROR tests/scenario/test_external_call_raw_first.py
   ModuleNotFoundError: No module named 'co_scientist.agents'
   1 error in 0.86s
   ```

   This failed because the Task 8 contracts and runner did not exist.

2. Durable submission failure:

   ```text
   PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3.11 -m pytest \
     -p pytest_asyncio.plugin \
     tests/scenario/test_external_call_raw_first.py::test_submission_failure_is_durable_after_validation -q
   FAILED: expected 'submission_failed', got 'validated'
   1 failed in 0.41s
   ```

3. Durable raw-metadata failure:

   ```text
   PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3.11 -m pytest \
     -p pytest_asyncio.plugin \
     tests/scenario/test_external_call_raw_first.py::test_raw_metadata_failure_is_durable_and_skips_validation -q
   FAILED: expected 'raw_persist_failed', got 'started'
   1 failed in 0.67s
   ```

4. Durable validated-payload persistence failure:

   ```text
   PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3.11 -m pytest \
     -p pytest_asyncio.plugin \
     tests/scenario/test_external_call_raw_first.py::test_validated_payload_persistence_failure_is_durable -q
   FAILED: expected 'validation_failed', got 'raw_response_persisted'
   1 failed in 0.44s
   ```

## GREEN evidence

Each focused RED test passed after its minimal production change:

```text
test_submission_failure_is_durable_after_validation: 1 passed in 0.37s
test_raw_metadata_failure_is_durable_and_skips_validation: 1 passed in 0.41s
test_validated_payload_persistence_failure_is_durable: 1 passed in 0.39s
```

Task 8 scenarios:

```text
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3.11 -m pytest \
  -p pytest_asyncio.plugin \
  tests/scenario/test_external_call_raw_first.py \
  tests/scenario/test_external_call_recovery.py -q
9 passed in 0.52s
```

Task 7 persistence regression:

```text
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3.11 -m pytest \
  -p pytest_asyncio.plugin tests/contract/persistence -q
23 passed in 1.02s
```

Full suite after implementation:

```text
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3.11 -m pytest -p pytest_asyncio.plugin -q
70 passed in 1.25s
```

Static checks:

```text
python3.11 -m ruff check src tests
All checks passed!

PYTHONPATH=<temporary-orjson-shim>:<worktree>/src \
  python3.11 -m mypy --no-incremental \
  src/co_scientist/ports/external_provider.py \
  src/co_scientist/agents src/co_scientist/runtime
Success: no issues found in 5 source files
```

The temporary mypy shim only forced standard-library JSON because the host Python has
an incomplete empty `orjson` namespace package. It was outside the repository and was
removed immediately after the check.

## Self-review

- Raw bytes are written and fsynced by the existing `FilesystemArtifactStore` before
  any validator invocation.
- Provider response metadata and usage are committed with the raw artifact reference.
- Resume reads and integrity-checks the persisted artifact and never invokes provider.
- Provider, raw persistence, validation, and submission failures transition durably.
- Canonical fingerprints use sorted compact JSON with UTF-8 SHA-256.
- `AgentResult` is frozen and carries task, idempotency, skill/schema, input snapshot,
  external-call, and raw-artifact traceability fields.
- Successful execution ends at `agent_result_submitted`; Supervisor remains the only
  owner of `domain_result_applied`.

No known Task 8 correctness concerns remain.
