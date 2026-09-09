# Co-Scientist Core Preview

Core Preview is a single-machine, CLI-first engineering preview. The foreground
`CoreRunner` and durable `Worker` execute six typed agent skills, while the Supervisor
alone creates tasks, applies scientific results, admits hypotheses, evaluates stopping,
and finalizes the Run. SQLite stores Run, task, lease, reservation, checkpoint, and
scientific events; raw provider bytes are written to the filesystem before validation.

## Install and initialize

Core Preview supports Python 3.11 and 3.12. From a repository checkout:

```bash
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
co-scientist config check --data-dir .co-scientist
```

The application upgrades its SQLite database to Alembic head before every command and
then checks the execution schema. The current head is `0003`. For an explicit migration:

```bash
CO_SCIENTIST_DATABASE_URL=sqlite:////absolute/path/co-scientist.db \
  python -m alembic upgrade head
```

There is intentionally no destructive reset command. To start clean, select a new
`--data-dir`; archive an old directory if its audit trail matters. Schema migration does
not make a pre-contract development Run executable: a Run without
`execution_contract_version: 3` fails closed and should remain archival evidence.

## Credential-free replay

The checked-in profile resolves typed replay resources relative to its own location, so
no test fixture or replay environment variable is required. A stable `--run-id` makes an
interrupted foreground run discoverable and resumable:

```bash
co-scientist run execute \
  --run-id lens-replay-001 \
  --goal examples/lens_regeneration_goal.yaml \
  --profile configs/profiles/core_preview.yaml \
  --provider replay \
  --data-dir .co-scientist
```

The command prints JSON at its durable boundary. The checked-in lens trace reaches
`completed` with stop reason `quality_converged`. It creates two hypotheses, completes
the required reviews and PubMed-derived novelty evidence, runs six tournament matches,
records epoch-local ratings and convergence evidence, then performs recoverable
finalization.

The production resources are:

- `examples/lens_regeneration_replay/core_trace.json`, containing schema-valid results
  for generation, reflection, ranking, evolution, proximity, and meta-review;
- `examples/lens_regeneration_replay/pubmed_search.json`;
- `examples/lens_regeneration_replay/pubmed_summary.json`.

Resource paths and SHA-256 hashes are frozen into the Run manifest. The same CLI works
from outside the repository working directory when goal and profile paths are absolute;
core Skill paths are resolved from the installed source rather than the current working
directory.

## Interruption, resume, and status

If `run execute` is interrupted, restart the durable worker with the same data directory
and operator-chosen Run ID:

```bash
co-scientist run status lens-replay-001 --data-dir .co-scientist
co-scientist worker run lens-replay-001 --data-dir .co-scientist
```

The worker reconstructs configuration from the frozen manifest, recovers expired leases,
and resumes from the persisted external-call boundary. A raw response or submitted result
is reused instead of recalling the provider; a call that returned but never durably wrote
raw bytes may be called again. Completed, completed-partial, failed, cancelled, paused,
and needs-attention Runs return without further work.

Lifecycle controls use the sequence reported by `run status` for optimistic concurrency:

```bash
co-scientist run pause lens-replay-001 \
  --expected-sequence N --data-dir .co-scientist
co-scientist run resume lens-replay-001 \
  --expected-sequence N --data-dir .co-scientist
co-scientist run stop lens-replay-001 \
  --expected-sequence N --data-dir .co-scientist
co-scientist run cancel lens-replay-001 \
  --expected-sequence N --data-dir .co-scientist
```

`stop` is a soft stop with Supervisor-owned partial finalization. `cancel` is a hard
terminal transition. `run resume` changes a paused lifecycle state; `worker run` performs
the actual durable work.

## Budget semantics and provider charges

A task claim and its budget reservation are one SQLite transaction. Estimates reserve
model calls, input/output tokens, USD, hypotheses, and matches before provider invocation.
The Supervisor settles actual usage exactly once when it applies the result, or releases
the reservation when work cannot proceed. Settled plus active reservations are checked
against every configured hard limit.

The Core Preview profiles cap 40 model calls, six hypotheses, and 12 matches. Their
`max_usd: null` means the software imposes no dollar ceiling. The OpenAI adapter records
reported input/output tokens but currently stores `cost_usd: 0` with pricing version
`unpriced`; it does not calculate an invoice estimate. Online operators are responsible
for provider pricing, account limits, and charges.

## Deterministic rich export

Export requires a new destination directory and refuses to overwrite an existing one:

```bash
co-scientist run export lens-replay-001 \
  --output lens-replay-001-export \
  --data-dir .co-scientist
```

Database-backed files come from one SQLite transaction snapshot. Repeating the export to
two new directories produces identical bytes for an unchanged Run. The exporter rejects
raw artifacts whose digest, Run/task/call identity, request fingerprint, execution
context, provider response ID, usage, or artifact reference disagrees with persistence.
Reusable lease tokens and credentials are never exported.

The evidence bundle contains:

- `manifest.json`: frozen goal/profile/policies, execution contract, resource hashes,
  provider/model/tool and prompt identities, anchor and epoch contracts, counts, costs,
  admission provenance, ranking state, and final stop/finalization evidence;
- `events.jsonl`, `tasks.json`, `budget_reservations.json`, and
  `external_calls.json`: ordered events, attempts/max-attempts and token-free lease
  history, reservation estimate/actual settlement, and raw-first call state;
- `convergence_checkpoints.json` and `stop_decisions.json`: source-bound budget,
  coverage, anchor, top-k, cluster, novelty, unresolved-work, stop, and finalization
  provenance;
- `hypotheses.json`, `hypothesis_projections.json`, `reviews.json`,
  `novelty_assessments.json`, and `proximity.json`: immutable content revisions and
  evidence-bound current projections;
- `tournament_epochs.json`, `matches.json`, and `ratings.json`: frozen epoch contracts,
  decisive and non-decisive results, and only legitimate epoch-local Elo updates;
- `costs.json`, `literature.json`, and `artifacts.json`, plus byte-preserved files under
  `raw_artifacts/`.

`co-scientist replay RUN_ID --data-dir PATH` prints the event-reconstructed Run snapshot;
it does not invoke a provider or mutate the Run.

## Opt-in OpenAI and PubMed gate

Live tests are selected only when a credential, an explicit model, and the explicit
network flag are all present:

```bash
export OPENAI_API_KEY='...'
export CO_SCIENTIST_OPENAI_MODEL='your-enabled-model-id'
export CO_SCIENTIST_NETWORK_ONLINE=1

PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3.11 -m pytest \
  -p pytest_asyncio.plugin -p respx.plugin \
  tests/contract/llm/test_openai_online.py \
  tests/contract/literature/test_pubmed_online.py \
  tests/smoke/test_lens_online_smoke.py -q -m online
```

`CO_SCIENTIST_PUBMED_EMAIL` is optional NCBI request identity. The online smoke uses the
same independent `run execute`, `run status`, and rich `run export` CLI path as replay. It
checks typed results, OpenAI model and PubMed tool identities, response IDs, raw manifests,
one settled reservation and one logical cost per applied call, reported OpenAI token
usage, terminal state, and stop/finalization evidence. If any prerequisite is absent, all
three tests are skipped and online behavior remains unverified; mocked or replay results
must never be reported as live success.

## Release verification

The credential-free release gate is:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3.11 -m pytest \
  -p pytest_asyncio.plugin -p respx.plugin \
  tests/unit tests/contract tests/scenario tests/smoke -q -m 'not online'
python3.11 -m ruff check src tests alembic
python3.11 -m mypy src/co_scientist
git diff --check
```

The persistence contracts cover both a fresh Alembic `head` and an upgrade from `0002`
to `0003`.

## Scope and reproducibility disclaimer

The CLI now also supports DeepSeek, Qwen, Gemini and Claude; see
[multi-provider usage](multi-provider.md) for credentials and example commands.
Live results for these adapters require separate credentialed validation.

Core Preview excludes FastAPI/HTTP, SSE, React, role-level model mixing, distributed
queues, PostgreSQL deployment, GPQA, and full benchmark or ablation packages. It is a
single-machine developer/researcher preview, not a production multi-user service.

Offline replay demonstrates deterministic engineering behavior for the checked-in input
and responses. The opt-in online gate demonstrates live connectivity and traceability
only when it actually runs. Neither gate reproduces unavailable internal systems or
original paper compute, validates a biomedical mechanism, establishes experimental
safety, or guarantees that ranked hypotheses are scientifically correct.
