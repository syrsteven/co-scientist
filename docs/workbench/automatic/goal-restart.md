# Explicit Goal v3 successor

Baseline: `63b77bc6ea34bcd3bc3d26a1fb7007691377660d`. PR21 remains unmerged.

Open the failed Run, choose **Restart with updated preparation**, review the diff,
then choose **Confirm and start bounded research** once. The first button performs
only a local GET. The second authorizes one linked successor's existing automatic
Goal → literature → seed → P08 → P09 → pass-only P10 chain. No R1 or new methods.
The development/nonproduction policies remain such even with real model execution.

The scientific Brief revision is reused exactly. The proposal binds original
Run/failed Task/Attempt/response hash, Brief hash, old/new Prompt versions, current
adapter profiles, controlled policies and server-default configuration. Actual
new Task requests are frozen by existing M15 services. This is not ordinary Resume
or resending the old failed request. Original failed records and usage never change.

For the target Run, the displayed differences are **Both → DIRECT** and maximum
directions **4 → 2**. New defaults are 1 Directed +1 Open, one DIRECT candidate per
ready direction, two queries/round, one page/query, five results/page, three selected
sources/round, one follow-up/direction. Other existing hard limits remain, including
80 model calls. Counts are upper limits, not guaranteed outputs or a dollar budget.

`GET /api/research/goal-restart?run_id=…` is read-only. A POST must include the
source Run, current preview hash and `authorize_successor_execution=true`.
The unique source key, successor Run, initial Task, Start identity and provenance
commit in one immediate transaction. Configuration/profile changes invalidate an
unconfirmed preview. Duplicate confirmations return the same saved successor.
If the HTTP response is lost, the browser looks up the original source; refresh or
browser restart can reopen that source and find the same successor without another
POST. A successor that fails remains failed/blocked; it cannot create a restart
chain. No automatic uncertain retry or global unblock is introduced.

The current local service uses `--goal-restart-only`: both scheduler advancement
and the external-send guard require the Run to be a persisted confirmed successor.
Ordinary Start and historical Resume are refused. This remains true after restart;
existing authorized successors can continue safely from persisted facts. Existing
no-ID uncertain and same-ID Responses rules remain unchanged. This service mode
intentionally does not start unrelated new research.

## Current local service

Page: http://127.0.0.1:8770/#run=a5d7c9aef42640858423fec3ea1116b0

Before enabling it, all saved research statuses were inspected: one original Run,
blocked. Existing `OPENAI_API_KEY` was confirmed available without outputting its
value or making a connectivity request. The browser opened only the preview, closed
it and refreshed. Afterward there were **zero successors and one original Attempt**;
all original input/execution table fingerprints were unchanged. The user must make
the final confirmation. `science_validated=false`.

Restart from this worktree with the existing environment (stop the verified 8770
CoScientist listener first; do not kill unrelated processes):

```sh
PYTHONPATH=src /Users/lemintea/anaconda3/envs/coscientist/bin/python -m co_scientist_next.workspace \
 --db /private/tmp/co-scientist-v6-automatic/runs/stage.sqlite --port 8770 \
 --automatic-research --responsive --goal-restart-only --real-goal --public-literature \
 --reading-model-config docs/workbench/reading-model.json \
 --generation-responses-config docs/workbench/responses-model.json \
 --review-responses-config docs/workbench/responses-model.json \
 --allow-development-goal-policy --allow-development-review-policy \
 --credential-env OPENAI_API_KEY --allow-real-model-calls
```

No frontend credentials. Process PID file: `/private/tmp/co-scientist-product-stage.pid`;
log: `/private/tmp/co-scientist-goal-successor.log`. Preserve the `--goal-restart-only`
flag; ordinary startup has broader previously authorized controller-resume semantics.

## Evidence and limits

Offline tests cover explicit consent/stale preview refusal, transaction interruption,
immutable original records, same Brief and differing defaults, repeated confirmation,
server reopening after lost response, a complete successor chain with fixtures,
HTTP confirmation/lookup, and no loop after successor failure. Existing source
fidelity, constraints and historical parser/replay tests remain.

Browser: actual original failure remains visible, configuration diff Both→DIRECT and
4→2, new version and scope displayed, final confirmation available; closing and
refreshing do not create a successor. No real confirmation was clicked. Screenshot
`goal-restart-preview.jpg` is cropped to the observed dialog and excludes private
scientific text. No raw database or credentials committed.

Real successor execution, real v3 quality and scientific validity remain untested.

Final checks: `PYTHONPATH=src python -m pytest tests/next --import-mode=importlib -p no:cacheprovider -m 'not online' -q`: **439 passed in 69.03s**, zero failed/skipped. Final focused Goal repair/restart suite: **19 passed in 3.01s**. Workflow Ruff, both JS syntax checks, wheel build and diff check passed. Full legacy G3 local suite not run. Remote CI reported on PR21 separately.
