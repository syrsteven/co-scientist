# P05 request byte capacity

Baseline fb49cd35c13f22997b710a15bb0df877f37fd7ff.
Run c91774672901422ea27a8a1ec38d0aa6 stopped in P05 Task
25800f45184949a3bd794ba6a24a2f97 before any model send.

The complete request is646381bytes; the Task freezes262144bytes. It combines16
reading records (~411593bytes),16 actual source views (~201318bytes), fixed Goal,
executed searches and coverage manifest. There is no provider response or Attempt
for this Task. This is neither invalid scientific output nor provider context overflow.
Unknown cost is not converted to a paid call with zero usage.

The workbench Chat and Responses profiles now use the existing supported maximum
2000000bytes. This is an explicit local serialization bound, not a token count or
provider context guarantee. Model/high/32768/JSON/no-temperature/600seconds and
scientific Prompt/material content remain unchanged. No material trimming, model
switching or hidden retry. Offline reconstruction proved old/new actual requests
identical and646381bytes, now within the new local cap. The cap remains enforced;
existing tests verify capacity_exceeded produces no external send.

Historical Task/Run configs are unchanged. The failed Task remains blocked. No retry,
new Task, new Run or resumption was performed. Reusing its acquired materials and
saved readings under a new execution configuration requires a separately authorized
recovery path; this change does not pretend an old frozen config was updated.
No need to re-fetch or re-read the already saved materials solely for this byte limit.
Provider token context for this specific request has not been verified by a real call.

The page distinguishes a capacity stop, displays complete byte count/frozen limit in
issue detail and explicitly states no model send. Raw scientific data remains in
local storage; public evidence contains only counts, identities and hashes.
Science_validated=false; no real model/search requests in this repair.

Validation:454offline tests passed73.06s, zero failed/skipped; workflow Ruff, JS,
wheel build and diff checks passed. Actual page issue detail verified. Target Task
still has zero Attempts and frozen262144byte configuration. Whole-table fingerprint
check was discarded because its initial sqlite.Row repr included object addresses;
that check is not preservation evidence. Exact frozen request equality/hash and
target-record checks above are the valid evidence. Full legacy G3 local suite not run.
