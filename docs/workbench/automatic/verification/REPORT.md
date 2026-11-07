# Offline and browser evidence — 2026-11-07

- New-system regression: 413 passed (58.87 seconds); final repeat recorded separately.
- Controller-specific: 10 passed, including whole chain Both/multiple candidates,
  cross-Run material reuse, seed isolation, unchanged vs substantive followup,
  resource guards, pass-only R0, real subprocess restart, notes/export.
- Ruff and JS syntax passed; wheel built successfully without dependency installation.
- Chrome desktop 1680px: document scrollWidth=1680. Mobile viewport 390x844:
  document scrollWidth=390. Screenshots: desktop-overview, mobile-literature,
  mobile-candidate, paused, stage-settings. This is viewport emulation, not physical-device testing.
- Arbitrary plant question, fixture Run ed56069dc1bd44569fe98ae837e04084:
  Start → background → 2 seeds → Both → 4 candidates → P09/P10, completed.
  Pause persisted through refresh; resume continued. No per-step manual task submission.
  Candidate human assessment persisted across reload and remained separate from model output.
- Export click produced research-ed56069dc1bd44569fe98ae837e04084.json in Downloads,
  1,642,417 bytes with one human annotation. Browser event observer timed out, but
  actual downloaded JSON was independently parsed successfully.
- Earlier fixture-policy mismatch was retained as an invalid P09 result, not rewritten.
  Fixture UI now supplies fixture-specific policies; real service uses explicit nonproduction policies.
- Stage service 8770 opened in browser; real profiles and credential availability shown
  without keys. Read-only DB check: 0 Runs, 0 Tasks, 0 Attempts. No research started.
- Original dirty workspace fingerprint: 232 files unchanged, including index/status.
- Historical database SHA-256 unchanged:
  p04-v2-prepared.sqlite a1414816be01c06535e9493f9eaa62d40ee892ad45cf024af61dc7776ab7a2b9
  candidate-review.sqlite 3da6812c150d38c712952ed1148c4a8f740b22a96886a69cc1bb296a5db70874
- No paid model sends or real literature acquisition. Scientific quality unvalidated.

Final repeat on delivery code: 413 passed in 61.76 seconds; 0 failed/skipped.
