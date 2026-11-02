# W0 engineering runtime

`src/co_scientist_next/` is a separate Python package chosen after checking the
existing G3 `src/co_scientist/` tree, entrypoints and dependencies. It imports no
old runtime, and needs only the Python 3.11/3.12 standard library. The repository's
existing setuptools package discovery also includes it in the wheel. The existing
G3 command remains historical; use the new explicit entrypoint below.

From a checkout of `codex/w0-t0-t1`, run with an existing Python environment:

```sh
PYTHONPATH=src python -m co_scientist_next --db /tmp/w0-demo.sqlite
```

Use a new database filename for a new example. It measures the 16 characters in
`engineering only`, then doubles the saved measurement to 32. Both modules are
independently callable functions in `demo.py`, registered by versioned module
names. They neither prepare a scientific Goal nor perform ethics screening.
`completed` means the engineering plan finished; it does not mean scientific
success, Admission, qualified Winner or a completed scientific workflow.

To stop after the first task and resume in a separate process:

```sh
PYTHONPATH=src python -m co_scientist_next --db /tmp/w0-resume.sqlite --steps 1
# Copy run_id from the JSON output into the next command.
PYTHONPATH=src python -m co_scientist_next --db /tmp/w0-resume.sqlite --run-id RUN_ID
```

The two commands print different PIDs. The first task/result is retained; only
step 2 executes on resume. `--steps 0` persists a prepared engineering plan without
executing it. CLI output includes identifiers, task states, fixture results and
partial usage totals; arbitrary call requests/responses/errors remain in SQLite.

For development tests use an environment with pytest (install `pytest>=8.2,<9` if
needed). Ruff is optional for execution, required for the recorded style check:

```sh
PYTHONPATH=src python -m pytest -q -s tests/next
python -m ruff check src/co_scientist_next tests/next
```

No package installation or credentials are required for source execution. Optional
repository wheel build: `python -m build --wheel --no-isolation` with the existing
build, setuptools and wheel tools installed. A full repository installation still
uses its existing G3 dependency list; this skeleton does not need that stack.

## APIs and saved facts

- `Store.create_project`, `revise_brief`, `create_run` provide M14a. Brief payloads
  may contain question/background/constraints/material references. Editing appends
  a revision with an optional explicit parent. Run pins a revision, policy reference,
  optional M01-owned GoalContext reference and explicit module sequence. References
  supplied by future modules must resolve to immutable content; this skeleton does
  not implement a Goal/policy document service.
- `Registry.register` and `Scheduler.step/run` provide the M12 sequence. A module
  receives detached `TaskInput` JSON and `TaskCalls`, and returns `ModuleResult`.
  The scheduler only passes the previous output forward. Scientific schemas and
  branching workflows belong to later modules; arbitrary plans are engineering
  plans, not validated production scientific routes.
- SQLite stores Projects, Brief revisions, Runs, Tasks, results, call Attempts and
  small execution facts. `results.task_id` is the stable result/application identity.
  Result insertion, task completion, successor insertion and Run advancement share
  one transaction. Repeating the same Task result is a no-op; a different result
  for that Task is rejected. There is no second checkpoint service: these rows are
  the checkpoint. Requests and responses are JSON payloads, not provider wire bytes.
- `TaskCalls.execute(key, target, request, invoke, max_attempts=1)` is the narrow
  model/tool adapter boundary. `target` identifies provider/model or tool version;
  `request` must include the actual input and visible materials, not just references.
  Adapters return JSON `CallResponse` and optional `Usage`. The stable per-Task key
  binds exact request/target; changing it on resume is rejected. Persist the Attempt
  before invocation and its response before applying module output.
- `KnownCallFailure` means the adapter confirms a failed response that permits a
  technical retry. Its actual error, optional failed response and known usage are
  saved. Each retry is a new Attempt linked to the previous one. Other exceptions,
  including timeouts and malformed adapter responses, are conservatively uncertain.
  Adapters must not hide additional sends/retries behind this boundary.
- Tokens, cost and tool units default to JSON `null`. `Store.usage` reports
  `known_total` and `unknown_attempts` separately per Run or Task; no known values
  gives `known_total: null`. A partial known total is never a complete bill when
  unknown attempts exist. Local replay records a fact and adds no Attempt/usage.
  Stage aggregation is represented by the module/step of each Task; no stage service.

## Recovery contract

Use `with Store(path) as store:` and call `store.recover()` once before starting a
new runtime. The POSIX lock excludes another active Store on the same resolved
path. This is a single-process, single-thread scheduler for local filesystems,
not a distributed worker protocol. Do not use `recover()` on a running scheduler.
Databases from G3 or another application are rejected. There are no migrations or
backward compatibility promises for this initial W0 schema.

A module interrupted without a saved result may run again. It must route external
side effects through stable `TaskCalls` keys and avoid hidden I/O. A saved success
is read locally, without sending the request again. An in-flight request left by a
process exit becomes `uncertain`; its Task/Run becomes `blocked`. A timeout is also
uncertain. Unknown usage remains unknown. Modules cannot submit a result while a
latest call is unresolved.

Recovery may keep the Run blocked pending provider reconciliation. If an operator
chooses to send again after investigation, the explicit API is:

```python
store.authorize_uncertain_retry(attempt_id, "reason; accept possible duplicate effect")
store.retry_task(task_id, "reason for resuming this task")
Scheduler(store, registered_modules).run(run_id)
```

The original Attempt remains uncertain; authorization and retry reasons are saved,
and a new Attempt links to it. This may duplicate an external effect: there is no
absolute provider exactly-once guarantee. No automatic provider reconciliation or
operator UI is implemented. Confirmed module failures are locatable by Run/Task,
module and stored error; `retry_task` preserves earlier error facts. Module IDs and
stable call keys must remain consistent across processes. Arbitrary module code or
external state is not automatically snapshotted or rolled back.

The process tests use actual child interpreters and `os._exit` after a saved call
and during a send. They check real send counters on disk, not just object recreation.
See [verification evidence](verification/w0-t0-t1.txt).
