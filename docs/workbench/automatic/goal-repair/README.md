# Goal preparation failure and entry simplification

Review baseline: `87906a4257cd19f4c6f2e7d6c8b386ca559c00d0`.
PR #21 remains unmerged. No new supplier/model/search requests. `science_validated=false`.

## Evidence, not an error-name inference

The verified service PID 19803 used this worktree and
`/private/tmp/co-scientist-v6-automatic/runs/stage.sqlite`.
Run `a5d7c9aef42640858423fec3ea1116b0` stopped in **Goal Preparation**,
Task `830eb3b661244dd2b5694c01f626168b`, Attempt
`12a32e8d68134467b948320a525ff449`. Goal Screening and literature never started.

The Chat completion finished: HTTP 200, `finish_reason=stop`, no truncation.
Provider usage: input 592, output 1620, total 2212, including 670 reasoning tokens.
Cost is unknown. M15 correctly retained a successful transport Attempt; the module
returned `invalid_output`. A succeeded Task here means its failure result was
persisted, not that Goal preparation succeeded.

The exact first failing branch is `parse_prepare`: the source-map membership check
inside `hard_requirements`, at `hard_requirements[0].input_locator`.
Actual: `$.explicit_constraints[0]`; accepted legacy locator: `explicit_constraints[0]`.
The Prompt asked for a locator but did not specify its grammar.

A second discrepancy prevents a syntax-only recovery: after the five explicitly
listed constraints, entries 5 and 6 classify background and intended-use text as
hard requirements, with `$.supplied_background` and
`$.intended_use_if_supplied`. These are actual user spans, not fabricated quotations,
but their classification exceeds the legacy contract's source map. Removing only
`$.` still fails. Silently dropping or reclassifying these entries would change the
model result. We therefore do not manufacture an offline successful Goal.

Root cause: underspecified preparation Prompt / strict parser contract coupling,
with model-selected classification outside that contract. Response extraction,
network completion and JSON decoding succeeded. The old frozen Prompt is
`v6-goal-focus-v2`; its saved developer message matches the retained legacy text.
The runtime checkout was the review baseline. That Run did not persist a Git SHA,
so its exact historical code commit cannot be established solely from DB metadata.
No new parser is applied retroactively.

`diagnostic-evidence.json` contains hashes, usage, read-only reproduction and
preservation results. User scientific text and complete raw responses are **not**
committed. Original response and failure remain in the local database. The
repository uses synthetic text to reproduce the same locator/classification shape.

## Minimal versioned correction

New Runs freeze `v6-goal-semantic-v3`. The program constructs original/prepared
question, explicit hard constraints, preferences, background and material manifest
from the frozen Brief. Model output contains only source-located, separately labeled
interpretations, unspecified details, essential clarification and an explicit empty
`additional_conditions` list. Extra output fields, fabricated spans, invalid
clarification and additional conditions are rejected. The model cannot replace the
program-owned fields or promote preferences/background into them. This is an
engineering separation; interpretation quality and ambiguity judgment remain
unvalidated. The legacy parser and saved message assembly remain available for old
Runs; successful saved calls replay without sending.

No successful recovery was applied to this Run. It remains **blocked**, with its
original invalid result. There is no ordinary Resume/Retry button for this state.
A new semantic judgment requires a separately authorized, versioned successor; this
change exports the proposed request only and intentionally provides no paid-send
shortcut. No new Task, Attempt, result, usage or global unblock is fabricated.

Read-only preparation command (output must not already exist):

```sh
PYTHONPATH=src python scripts/prepare_goal_recovery.py \
  --db /private/tmp/co-scientist-v6-automatic/runs/stage.sqlite \
  --run a5d7c9aef42640858423fec3ea1116b0 \
  --output /private/tmp/goal-recovery-a5d7-v3-unsent.json
```

The private export is mode 0600. It binds original Task/Attempt/request/response
hashes, new Prompt version, complete new messages and unchanged model parameters.
It is explicitly `executable=false` and `execution_authorized=false`. Repeated
read-only proposal construction is identical and does not duplicate usage. Any
future execution must add explicit successor authorization and provenance rather
than mutate this historical failure or call ordinary Start as a retry.

## Product behavior

New Research retains the complete Brief but removes editable engineering parameters.
The server freezes `journey-defaults-2026-11-07-v1`: 1 Directed + 1 Open, one DIRECT
candidate per ready direction, two queries/round, one page/query, five records/page,
three selected sources/round, one follow-up/direction. Existing hard limits remain:
80 model calls, 20 search pages, 40 material fetches, six 12,000-character segments
per source, 60 remote queries at minimum 15-second intervals. This is an upper
bound, not a promise of two candidates, exhaustive coverage or a dollar budget.
Existing Run settings (including this Run's Both mode) are unchanged. Existing
start keys replay their original configuration; fresh client overrides are rejected.

Failure UI identifies preparation versus screening, invalid response versus
technical failure, clarification, explicit rejection and uncertain send. View Issue
shows the local failure and safe next step, without a fake retry. Diagnostics/audit
retain technical details. Candidate labels derive from saved P09/P10 results.
Reading artifacts render structured scientific fields, with raw JSON folded; actual
source remains separate. Query `question` and `why` are shown only when recorded.
Human assessments restore retrieval relevance/omissions, reading context/negative
results/wording/source fidelity and candidate fidelity/value/testability/concerns,
alongside free text, bound and independently saved.

## Local service and acceptance

The old worker process was stopped after verifying the only research Run was
blocked. The updated service is available at **http://127.0.0.1:8770/** with no
credentials, no execution authorization and `--suspend-controller-worker`.
Opening, refreshing or restarting it cannot resume a supplier task. Start is disabled
and the server rejects Start in this diagnostics mode. Do not run the ordinary
`start_automatic_workbench.sh` to diagnose historical failures: that command resumes
previously authorized running controllers.

Safe restart (after stopping the verified listener; use the existing Python env):

```sh
PYTHONPATH=src python -m co_scientist_next.workspace \
  --db /private/tmp/co-scientist-v6-automatic/runs/stage.sqlite --port 8770 \
  --automatic-research --responsive --suspend-controller-worker --real-goal \
  --reading-model-config docs/workbench/reading-model.json \
  --generation-responses-config docs/workbench/responses-model.json \
  --review-responses-config docs/workbench/responses-model.json \
  --allow-development-goal-policy --allow-development-review-policy \
  --credential-env CO_SCIENTIST_DIAGNOSTICS_NO_KEY
```

Leave `CO_SCIENTIST_DIAGNOSTICS_NO_KEY` unset. No `--allow-real-model-calls`.

Desktop and actual 390px browser checks: full Brief, fixed scope, no editable
Research Configuration, preparation-specific failure and View Issue, no recovery
button, structured assessment fields, no horizontal overflow (`innerWidth=390`,
`scrollWidth=390`). Screenshots contain only the empty New Research UI, not private
scientific text. An extension connection error was present in browser logs; no
Journey script exception was observed and the inspected controls rendered normally.

See `new-research-desktop.jpg` and `new-research-390.jpg`. Clinical/scientific quality,
real v3 model behavior, physical mobile devices, a paid recovery and downstream
Screening remain untested. No new scientific method or module is added.

## Executed final checks

- `PYTHONPATH=src python -m pytest tests/next --import-mode=importlib -p no:cacheprovider -m 'not online' -q`: **436 passed in 69.46s**, 0 failed/skipped. Includes subprocess crash/replay, saved response reproduction, fixed defaults, notes persistence and suspended HTTP service.
- Full workflow Ruff command (`src tests scripts`, existing migration I001 ignores): passed.
- `node --check` Journey and workbench JavaScript: passed.
- `python -m build --wheel --no-isolation`: passed. `git diff --check`: passed.
- Original response replay and prefix-only normalization both rejected; private proposal generation twice produced identical output and no DB/usage changes.
- Initial sandbox HTTP binding failures were environment restrictions; the complete final suite used approved localhost access. Earlier contract tests target v3 crash injection; a separate legacy-frozen replay test remains.
- Legacy G3 full local regression: **not run**; remote CI is reported separately.
