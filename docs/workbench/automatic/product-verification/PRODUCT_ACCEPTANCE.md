# V6 product fidelity and interaction acceptance

Date: 2026-11-07 (Asia/Shanghai). Engineering acceptance only; science_validated=false.
Reviewed starting head: f07f04c395d171576c565a4a46dbc89a36ca029b, original PR #21.
The supplied original design remains unchanged. Comparison uses its interactive HTML
served only by the offline fixture, with explicit script hashes and no network access.

## Design requirement → implementation → evidence → remaining difference

Desktop comparison used a 1440 × 1000 viewport for both pages. Mobile tests used
390 × 844; the actual innerWidth and document scrollWidth were both 390 for all
seven research/settings pages, comparison, New Research and My Research.
An earlier screenshot batch still had 1440px applied to the reference tab; it was
not counted as mobile acceptance. The final `mobile-*` files replace that batch.

| Page / design requirement | Actual implementation and exercised behavior | Evidence | Remaining difference |
|---|---|---|---|
| My Research: project cards, search/order, Active/Archived/Trash | All saved projects including drafts without Runs; title search; name/newest sort; Rename/Archive/Trash/Restore in Manage project. Trash/Archive first stop scheduling; Restore never resumes it. Draft found after refresh and Trash restore. | demo-my-research.jpg, actual-my-research.jpg, mobile-my-research.jpg, draft-restored.jpg | Controls use a disclosure instead of the prototype's overflow modal. No irreversible deletion. |
| New Research: full brief and right-hand Journey preview | Title, question, background, objectives, hard constraints, preferences, focus, use and text references; configuration disclosure, controlled policy consent, Save Draft, durable launch state. File chooser visibly disabled. Failed configuration corrected through a new Brief revision. | demo-new-research.jpg, actual-new-research.jpg, mobile-new-research.jpg, start-failed.jpg | No example brief is injected into real projects. Resource limits replace the prototype's unsupported dollar-budget control. |
| Live Research: five stages, current activity/query, directions, emerging candidates, findings and researcher input | Five-stage layout and two-column scientific cards; independent per-seed states; actual query and result counts; notes separate from activity regions. No percentage or scientific score. | demo-live.jpg, live-research.jpg, mobile-live-research.jpg, live-input-preserved.jpg | Stage labels describe bounded execution. They do not claim all directions complete the same stage together. |
| Research Directions: index/detail, question origins, focused search, findings, gaps, hypotheses | Direction selectors connect original question/anchors → exact query purpose → saved P04 findings → P05/P07 scope/gaps → bound candidates and reviews. Captured one direction finished while another was in initial review. | demo-research-directions.jpg, research-directions.jpg, actual-research-directions.jpg, mobile-research-directions.jpg | No invented progress or direction quality ratings. Long structured scientific records grow vertically. |
| Literature: broad/seed filter, query purpose, source/access, selection and findings | Exact planned/executed queries, returned source modal, source metadata; actual access and character ranges; original text opens on demand. Relevance exclusions, access failures and relevant-but-resource-omitted items are distinct. Saved reading findings and context links remain separate from originals. | demo-literature.jpg, actual-literature.jpg, mobile-literature.jpg, original-source.jpg | Provider IDs are not adjudicated as independent studies. Full-text extraction does not imply images/supplements were read. |
| Hypotheses: scientific reading and true side-by-side comparison | Four persisted candidates from two independent single-call modes. Shared fields are displayed in two columns on desktop, stacked on mobile. Claim → context/mechanism → evidence → assumptions/alternatives → prediction/falsification → limitations/review. Source buttons open the actual frozen views. No score/rank. | demo-hypotheses.jpg, hypothesis-comparison.jpg, hypothesis-detail.jpg, mobile-comparison.jpg | Test candidate titles remain their original language. Explicit fixture scientific outputs are invented, not translated or repaired. |
| Overview: complete fixed brief and neutral background | Every frozen Brief field is visible with actual broad P05 findings and saved candidates; later draft editing does not alter a Run. | demo-overview.jpg, actual-overview.jpg, mobile-overview.jpg | No claims about scientific completeness or novelty. |
| Timeline: scientific activities with related records | Persisted events are named as query planning, reading, synthesis, preparation, generation or review; linked actions open the relevant literature/direction/candidate rather than raw logs. Omissions and bounded pagination are visible. | demo-research-timeline.jpg, actual-research-timeline.jpg, mobile-research-timeline.jpg | No simulated event animation; technical audit is separate. |
| Settings: connections and researcher options | Four role connections, real/fixture execution and credential availability; policy maturity independent of execution. Endpoints/parameters/policy JSON live in a separate Diagnostics modal and audit export. | demo-settings.jpg, actual-settings.jpg, mobile-settings.jpg, stage-settings.jpg | Production policy is not configured/approved; the selected policy remains nonproduction. |

## Failure and persistence acceptance

- Annotation writes use a separate connection, foreign-key checking and BEGIN IMMEDIATE
  short transaction, plus atomic submission identity/hash deduplication. They bypass
  the long-operation scheduling lock, not database integrity checks.
- Actual delayed P04 interval: 04:09:13.626359–04:09:25.635623 UTC. Browser note was
  saved at 04:09:24.439122 UTC, before that request ended. Immediately readable.
  The isolated HTTP test also holds the adapter behind an Event and asserts save
  latency <1.5s while the adapter remains blocked. No 409 retry loop.
- Unsaved text survived incremental live updates and a full reload; save failure
  retains it. Run-level notes bind the immutable Brief revision; candidate/view notes
  bind their exact content hash. Historical binding versions remain identifiable.
- The fixture deliberately closed the first Start response after committing the Run.
  Browser recovered Run `1faf0234aadc4a3cbdcad875f57f4581` through its persistent
  start_key, then reloaded the same Run. It did not POST a second launch. The HTTP
  regression independently tests the lost-response path.
- Definite configuration errors permit edits and another Brief revision. Unknown
  Start state preserves the frozen launch request and identity for lookup or explicit
  same-key recovery. Repeated click is guarded; server start identity remains unique.
- Server-controlled policy ID/version/hash is resolved before launch. Client policy
  bodies, unknown IDs, changed hashes or versions are rejected. The selected bundle
  and its public identity freeze with the Run; no production approval is implied.
- Per-seed hold records identify exact Tasks. Other independent seeds may continue;
  unresolved Attempt history remains unchanged and counted against reserved sends.
  Common/background failures, credential/configuration and Run resource problems
  remain Run-level stops. No-ID uncertain never re-POSTs; remote-ID behavior reuses
  existing same-ID machinery. No global exemption or mutation of historical Attempts.

## Complete isolated fixture

`offline-run-export.json` contains the completed final fixture Run, two seeds,
planned/executed queries, full-text and abstract fallback, material 999003 access
failure, relevant material 999004 omitted by resource cap, six P04 readings,
P05/P07, four P08 candidates and eight P09/P10 records. Notes are a separate export
section. Provider/model transports are deterministic local fixtures only.

Fixture database: /private/tmp/co-scientist-product-fixture/runs/fixture.sqlite.
Reproducible fixture server: `PYTHONPATH=src python scripts/serve_product_fixture.py`.
It intentionally delays P04 by 12 seconds and loses one Start response, and never
loads model credentials. The failure/recovery draft and older fixture Run are retained.
The database itself is not committed. The export is explicit invented development data.

## Validation and limits

Final command/results are recorded in FINAL_CHECKS.md. Browser measurements and
screenshots substantiate the listed exercised paths, not scientific effectiveness.
Desktop and emulated mobile Chrome were tested; physical mobile devices and a real
scientific research run were not tested. Real model sends 0; real retrieval sends 0.
Original worktree 232-file fingerprint and historical database hashes remain unchanged.
Automatic strategy defaults are unchanged: 2 queries/round, 1 page/query, 5 results/page,
3 selected sources/round, 1 followup/seed (fixture explicitly chose 2 selected sources).
Stopping at a cap never means evidence is sufficient or upgrades readiness.
