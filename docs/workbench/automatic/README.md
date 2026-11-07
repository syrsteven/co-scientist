# V6 automatic research — engineering stage test

Baseline: PR #20 merged at `0e5600f55a54412e27d48b56fedf85de64305c5c`.
Original supplied Journey HTML and gap audit remain byte-preserved under
`docs/design/workspace-journey-user-provided/`, with SHA-256 provenance.

## Start / restart

```sh
cd /private/tmp/co-scientist-auto-research
CO_SCIENTIST_PYTHON=/Users/lemintea/anaconda3/envs/coscientist/bin/python sh scripts/start_automatic_workbench.sh
```

Open http://127.0.0.1:8770/. Database:
`/private/tmp/co-scientist-v6-automatic/runs/stage.sqlite`.
Override `CO_SCIENTIST_AUTO_DB` and `CO_SCIENTIST_AUTO_PORT` explicitly if needed.
Stop the server with Ctrl-C in its terminal before restarting on the same port.
The backend reads existing `OPENAI_API_KEY`; never enter it in the browser.
Startup on an empty database sends nothing. Restart resumes only previously
explicitly started running automatic research; pause/stop first if that is unwanted.
Historical/manual runs are not adopted. Missing configuration never selects fixtures.

## User path

1. Settings: inspect separate Goal/reading Chat and generation/review Responses profiles.
2. New Research: question, background, objectives, focus, hard constraints, preferences,
   intended use. Objectives/focus enter Goal preparation separately from hard constraints.
3. Review nonproduction policies and resource limits, then explicitly Start Research.
   This authorizes bounded external work, including paid models, until stop/pause/limit.
4. Live Research and Directions show saved progress; Literature shows actual queries,
   selection reasons, original view ranges and separate readings. Hypotheses contains
   immutable scientific text and separate Ethics/R0 outcomes, never a scientific score.
5. Save independent human assessments and export. Assess relevance/omissions, preservation
   of negative results and context, evidence fidelity, testability and major concerns.
   Notes do not enter model inputs. Viewing/refreshing only reads local facts.

## Adopted defaults and limits

Sequential controller: 1 directed + 1 open direction, maximum 2; one candidate per
mode/direction, DIRECT by default. Both means two independent calls per requested
candidate slot, not iteration. Defaults: 2 queries/round, first page only, 5 records/page,
3 selected sources/round, one followup round, 12,000-character contiguous segments,
maximum 6 segments/source, 80 model sends, 20 search pages, 40 material HTTP sends,
60 same-ID remote queries with at least 15 seconds between queries. All are frozen
per Run; limits count reservations before sends, not guessed dollars. Unknown costs
remain unknown. The API profile stays gpt-6.1-sol/high/32768, JSON, no temperature,
600 seconds, 262144 request bytes; oversized requests stop without silent truncation.

The workspace material cache reuses exact saved source/access/content snapshots with
acquisition provenance. Re-reading across new Run/Seed is conservative: interpretations
are not reused solely by paper ID. Existing background tables retain scoped reading,
Prompt/model/view bindings and query/packet/candidate relationships. Cache freshness
is a saved snapshot, not a fresh network check. Source IDs are not independent-study counts.
Unavailable full text falls back with explicit access limitations; segment omissions
are recorded. Full-text text extraction does not imply figures/supplements were read.

New English prompts: `v6-goal-focus-v2`, `v6-abstract-relevance-v1`, and the narrow
`v6-p07-bounded-followups-v1` supplement (see PROMPTS.md). Existing scientific prompts
and historical requests remain unchanged. Abstract screening is relevance, not M05 grading.
Experiment-only gaps stop a seed; unchanged information cannot automatically become ready.
One seed's followup reference never crosses into a sibling seed.

Pause/stop blocks new reservations; already submitted work can complete and is not
claimed cancelled. Successful results replay locally; saved remote IDs are queried;
no-ID uncertain stops and never auto-POSTs. Manual operation endpoints cannot bypass
a managed Run's frozen controller. No R1/M03, Ranking or Evolution is implemented.

## Validation and remaining limits

Offline tests and controlled browser fixtures only; model requests 0, real retrievals 0.
Real Goal adaptation is wired but its scientific performance is untested. Policies are
nonproduction even when a real model executes them. science_validated=false.
The initial bounded strategy and relevance/seed quality require user scientific review.
No distributed scheduler, automatic uncertain recovery, dollar budget guarantee, or
cross-Run reuse of interpretations is claimed.

Commands:
```sh
PYTHONPATH=src python -m pytest -q tests/next
python -m ruff check src/co_scientist_next tests/next
node --check src/co_scientist_next/frontend/journey.js
node --check src/co_scientist_next/frontend/workbench.js
python -m build --wheel --no-isolation
```
See verification/REPORT.md and screenshots. Databases and credentials are not committed.
