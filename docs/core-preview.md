# Co-Scientist Core Preview

Core Preview is a single-machine, CLI-first engineering preview. Its release evidence
is a deterministic offline replay of the lens-regeneration vertical slice, backed by
SQLite events and tasks, raw filesystem artifacts, `ExternalCallRunner` recovery,
Supervisor-owned result application and finalization, epoch-scoped Elo projections,
and a durable multi-file export.

## Install

Use Python 3.11 from the repository root:

```bash
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
co-scientist config check --data-dir .co-scientist
```

## Credential-free replay smoke

The release smoke is intentionally a test-hosted composition of the existing Core
Preview interfaces. It does not use a hidden orchestration path: replayed responses go
through `SkillExecutor`/`ExternalCallRunner`, raw persistence, SQLite external-call
state, `Supervisor.handle_result`, admission, convergence stop, and finalization before
`export_run` reads the durable state.

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3.11 -m pytest \
  -p pytest_asyncio.plugin \
  tests/smoke/test_lens_replay_smoke.py -q -m 'not online'
```

No credentials or network access are used. The smoke creates two mechanistic lens
hypotheses, both required review stages, PubMed replay provenance, NoveltyAssessments,
a Proximity edge, six decisive/non-decisive tournament matches, epoch-local ratings,
quality-convergence stop evidence, complete finalization, and a deterministic export.

The replay test verifies behavior that ran locally. It does not establish the quality
of a live model's scientific reasoning.

## Opt-in OpenAI and PubMed smoke

Live execution is disabled unless all three gates below are explicitly present. The
separate PubMed contract additionally uses `CO_SCIENTIST_PUBMED_ONLINE=1`.

```bash
export OPENAI_API_KEY='...'
export CO_SCIENTIST_OPENAI_MODEL='your-enabled-model-id'
export CO_SCIENTIST_NETWORK_ONLINE=1
export CO_SCIENTIST_PUBMED_ONLINE=1

PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3.11 -m pytest \
  -p pytest_asyncio.plugin -p respx.plugin \
  tests/contract/llm/test_openai_online.py \
  tests/contract/literature/test_pubmed_online.py \
  tests/smoke/test_lens_online_smoke.py -q -m online
```

`NCBI_TOOL` and `NCBI_EMAIL` are optional identity settings for the online lens smoke.
The default tool name is `co-scientist-core`; no email is sent unless configured.

The online lens smoke sends one schema-constrained OpenAI request and one PubMed
E-Search request through the raw-first runner and applies both results through the
Supervisor. Expected evidence includes provider response IDs, raw artifact manifests,
at least two generated hypotheses, at least one PMID, ExternalCall terminal states,
and one logical cost entry per applied call. Online behavior remains unverified unless
this opt-in command actually passes in the operator's configured environment.

## Durable export

`export_run(run_id, output_dir, read_model, artifacts)` refuses to overwrite an
existing output directory and writes the following deterministic bundle:

- `manifest.json`: lifecycle history, stop/completeness/finalization, profile/goal,
  epoch/anchor/ranking state, counts, provider/model/skill/request metadata, cost total,
  and PubMed cutoff/access issues;
- `events.jsonl`, `tasks.json`, and `external_calls.json`;
- immutable `hypotheses.json` content plus event-rebuilt projections;
- `reviews.json`, `novelty_assessments.json`, `proximity.json`;
- `tournament_epochs.json`, `matches.json`, and `ratings.json`;
- `costs.json`, `literature.json`, and `artifacts.json`;
- byte-preserved raw response files under `raw_artifacts/`.

The Task 14 bundle is currently a production Python interface:

```python
from pathlib import Path

from co_scientist.adapters.artifacts.filesystem import FilesystemArtifactStore
from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork
from co_scientist.export import SqliteRunReadModel, export_run

uow = SqliteUnitOfWork("sqlite:///path/to/co-scientist.db")
export_run(
    "run-id",
    Path("run-export"),
    SqliteRunReadModel(uow),
    FilesystemArtifactStore(Path("path/to/artifacts")),
)
```

The CLI `run export` command listed below is the earlier Task 13 single-file lifecycle
snapshot, not this richer evidence bundle. This distinction is deliberate and avoids
claiming a CLI integration that Core Preview does not yet have.

## CLI operations

Use one explicit `--data-dir` for every command so independent invocations share the
same SQLite run. Status prints the current optimistic sequence needed by lifecycle
commands.

```bash
co-scientist run start \
  --goal examples/lens_regeneration_goal.yaml \
  --profile configs/profiles/core_preview.yaml \
  --provider replay \
  --data-dir .co-scientist

co-scientist run status RUN_ID --data-dir .co-scientist
co-scientist run pause RUN_ID --expected-sequence N --data-dir .co-scientist
co-scientist run resume RUN_ID --expected-sequence N --data-dir .co-scientist
co-scientist run stop RUN_ID --expected-sequence N --data-dir .co-scientist
co-scientist run cancel RUN_ID --expected-sequence N --data-dir .co-scientist
co-scientist replay RUN_ID --data-dir .co-scientist
co-scientist run export RUN_ID --output snapshot.json --data-dir .co-scientist
```

`run start` creates and starts durable lifecycle state; it does not itself execute the
full autonomous lens workload or call a provider. `stop` performs the Core Preview
synchronous partial-finalization path, while `cancel` is a distinct hard terminal path.

## Budgets and release verification

The Core Preview profile sets `max_usd: null`: dollar cost is unlimited. This is not a
spending promise or safety cap. The profile still guards the run at 40 model calls, six
hypotheses, and 12 matches; operators running online remain responsible for provider
limits and charges.

The complete offline release gate is:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3.11 -m pytest \
  -p pytest_asyncio.plugin -p respx.plugin \
  tests/unit tests/contract tests/scenario tests/smoke -q -m 'not online'
python3.11 -m ruff check src tests
python3.11 -m mypy src/co_scientist
git diff --check
```

## Scope and reproduction disclaimer

Core Preview excludes FastAPI/HTTP, SSE, React, four additional LLM providers,
PostgreSQL deployment, GPQA, full benchmark and ablation packages, production
multi-user isolation, and claims of wet-lab validation. Those belong to later preview
stages.

The offline run is deterministic replay evidence for the implementation's engineering
contracts. The online smoke, when explicitly run, is connectivity and traceability
evidence. Neither is a bit-for-bit reproduction of unavailable internal systems, a
replication of original paper scores or compute scale, a biomedical validation, or a
claim that the ranked lens mechanisms are scientifically correct.
