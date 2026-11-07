# Final checks — 2026-11-07

Environment: existing conda coscientist Python 3.12; local Node; Chrome extension.

- `PYTHONPATH=src python -m pytest -q tests/next`: **420 passed in 66.72s**, 0 failed/skipped.
- `python -m ruff check src/co_scientist_next tests/next scripts/serve_product_fixture.py`: passed.
- `node --check src/co_scientist_next/frontend/journey.js`: passed.
- `node --check src/co_scientist_next/frontend/workbench.js`: passed.
- `python -m build --wheel --no-isolation`: wheel built successfully.
- `git diff --check`: passed.
- Original 232-file fingerprint: unchanged, including index and status.
- Historical p04-v2 database SHA256: a1414816be01c06535e9493f9eaa62d40ee892ad45cf024af61dc7776ab7a2b9.
- Historical candidate-review database SHA256: 3da6812c150d38c712952ed1148c4a8f740b22a96886a69cc1bb296a5db70874.
- Updated stage service 8770: 0 Runs, 0 Tasks, 0 Attempts; user Start not invoked.

HTTP tests run in isolated child processes with local fixture transports, following
the repository socket-blocking test convention. A first regression exposed the older
HTTP test's missing annotation submission ID; that test was updated for the new contract.
Sandbox-denied socket binding was not presented as a product failure. Final tests ran
with approved loopback binding. No paid model or real literature requests were made.

Physical mobile devices, real end-to-end scientific quality and old G3 suite: not run.
Remote CI is separate from these local results; this PR is not merged.
