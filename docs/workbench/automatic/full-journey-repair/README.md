# Start failure, Run Trash and full offline journey

Baseline de1368ce5a59a7ded99067187fb600d15262fe50, clean codex/v6-auto-research.
PR21 remains unmerged; original checkout and scientific history preserved.

## Root cause of this Start failed

Read-only database inspection found the original project in project_lifecycle=trash.
The browser's New Research form retained the same scientific fields and failed launch
state. The frontend saveDraft path reused savedBrief.project_id, then controller.start
correctly refused a hidden project. Refresh discarded the visible error while retaining
only Start failed. This is different from the earlier disabled-button/service gate.

New Research now detaches stale project/revision/start/error identity while preserving
scientific draft text. Explicit Edit as new revision still selects an existing project.
Saving a draft whose selected project was since hidden creates an independent project
instead of submitting into Trash. No hidden project is silently restored. Persistent
launch_error keeps the actual safe server error visible after refresh; pending unknown
Starts still require lookup and cannot detach to bypass duplicate protection.

## Run deletion

My Research now offers Move Run to Trash and stop / Restore Run (stays stopped).
This is recoverable hiding, not physical deletion. Run/Task/Attempt/Result/usage and
original outputs stay in place. Trashing atomically stops running/paused scheduling;
already submitted remote work is not cancelled. The execution guard rejects trashed
Runs. Restore does not resume. Lifecycle facts are included in audit export.
No real historical Run was deleted by Codex during acceptance.

## Offline acceptance

Use the clearly labeled fixture server8779 (`PYTHONPATH=src python
scripts/serve_product_fixture.py`). It contains invented sources and deterministic
model adapters, no real credentials/transports. P04 deliberately waits12seconds.
First Start response is deliberately lost after commit; lookup recovers the same Run.
The unrelated ALS placeholder queries are engineering fixture outputs, not valid
plant literature coverage or model quality evidence.

Fresh frontend Run: 30dbe7e8dff543499b5f25f9f4b55615, arbitrary plant question.
Started through visible Brief/consent controls; no per-step task/ID entry.
Browser inspected source access/failure/fulltext/abstract fallback, direction preparation,
structured independent assessment saving during execution and reload of same Run.
Further completion evidence is recorded below.

Regression: 448 new-system offline tests passed in73.74seconds. Additional Run Trash
and hidden-project isolation tests:2passed. Workflow Ruff, JS and wheel build passed.
No new real model/search calls. Scientific performance remains unvalidated.

## Completed browser result

The new Run completed automatically with3 executed search pages,9 P04 readings,
3 P05 packets,2 seeds,2 ready records,2 DIRECT candidates and2each P09/P10.
Both candidate reviews are fixture pass/proceed_to_R1, waiting for unimplemented R1.
Actual source links, candidate detail, two-column comparison, saved independent
assessment and reload were checked. Historical fixture Run moved to Trash and restored.
Browser export downloaded valid JSON with2 generation actions,4review actions and
saved annotation. The automation download-event waiter timed out; filesystem inspection
confirmed a download had occurred. Export now uses a direct same-origin downloadable
JSON link instead of immediate object-URL creation/revocation, and the new download
was verified by hash. No claim that the tool timeout was a server failure.

Evidence: completed.jpg, compare.jpg, download-evidence.json. The actual downloaded
fixture JSON remains in local Downloads; no real scientific data is published here.
