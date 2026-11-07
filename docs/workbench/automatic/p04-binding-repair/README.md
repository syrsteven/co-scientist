# P04 selected-view binding repair

Baseline a34c2cd1a892f92b0d61275a14919f52025f66ca, clean codex/v6-auto-research.
Target Run c112c098940f4a8f9f02041e8c0654bf failed during P04, not retrieval or P05.
Task97ae7a90332946528d5dcc212c308f2f, Attempt4c3dbd5f762b40acb58e288f1a690535.

Read-only evidence: HTTP200, finish_reason=stop, input4733/output11433 tokens,
including2050reasoning tokens, total16166. Cost unknown. JSON decoded successfully.
There were26finding cards. Card index1 contained a repeated substring in its view ID:
expected `8e07d726b7454f0d9bfea0d1de4fb266`, returned
`8e07d726b7454f0d9bfea0d9bfea0d1de4fb266`.
Its supporting quote exists exactly in the frozen source text; all other selected
view/quote checks and all negative quote checks passed. The legacy combined error
hid which field failed. No output truncation or provider failure caused this result.

Old Prompt w1-l2-p04-context-v2 asks the model to copy source_view_ref on every card.
The source selection was already frozen, single-view and bound by the application.
New Prompt **w1-l2-p04-bound-view-v3** retains all v2 scientific/context/negative-result
instructions but omits opaque source IDs from model card output; the application
assigns the single frozen view ID when absent. A supplied wrong ID still fails.
Every supporting/negative quote must still occur exactly in the selected text.
Errors now identify card index and source identity versus quote mismatch.

Historical v1/v2 Prompt registry and strict parser behavior remain. background_actions
freeze the new version per newly submitted reading; changing defaults does not
rewrite old requests/results. Original failure, Attempt, response and usage are
unchanged. No paid request or retrieval was issued. No scientific reading is inferred
from a format repair. The target Run remains blocked; this patch does not silently
repair its original card or resume the controller. Reprocessing this historical
response would require an explicit separately recorded recovery decision; none was
applied here. Do not ordinary-Start a duplicate to bypass its blocked task.

The page now identifies background reading failure and offers local issue detail,
with technical diagnosis folded. It does not offer an unsafe generic Retry.

Tests cover absent-ID program binding, copied wrong/repeated IDs rejected, fabricated
positive/negative quotes rejected and frozen legacy Prompt/replay. The actual saved
response was replayed offline to reproduce card1 identity failure. Public evidence
contains identities/hashes/usage only, not private Brief, scientific output or raw
licensed article. science_validated=false.

Final validation:453offline new-system tests passed73.22seconds, zero failed/skipped.
Workflow Ruff, Journey JS, wheel build and diff checks passed. Browser opened actual
failed Run and issue detail without sends. Original execution/input table hashes
unchanged after reload and browser inspection. Full legacy G3 local suite not run.
Earlier new-task version assertions were updated for v3; frozen legacy tests remain.
