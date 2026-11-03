# Co-Scientist development constraints

- Current architecture: `docs/design/m00-accepted-v1.0/01_ARCHITECTURE_BASELINE.md`
  and its accepted decision, ownership, dependency and handoff files. Its
  `reference/` directory is historical. W0 in `docs/design/w0-proposed-v0.1/`
  remains Proposed. W0-T0/T1 adopts M14a/M12/M15a engineering semantics;
  W0-T2 adds only M09a/M11a/LiteraturePort representations and structural tests.
  W0-T3 adopts the supplied real-case package as public development data and a
  Proposed M01/M02 plan. W0-T4 separately authorizes only Goal preparation, binary
  Goal Ethics, narrow conditional advancement and its persisted local page.
  Read docs/W0_T4_DECISIONS.md for accepted overrides; W1 originals stay Proposed.
  W1-L1 separately authorizes explicit human-query Europe PMC search/fetch only
  after a saved completed Goal Ethics pass; see docs/W1_L1_LITERATURE.md.
  Development Goal screening plus real public acquisition is not real ethical
  review or a production scientific chain. No model reading/readiness/generation.
- For W0 real cases read `docs/W0_REAL_CASES.md`. Raw casebooks and reviewer
  expected/critical_failures/assessment must never be sent to tested models. Use
  the explicit data export; source paraphrases, original facts and author model
  outputs are distinct. Scientific expectations remain provisional without experts.
- Read `docs/STATUS.md` for actual implementation and validation. Design
  acceptance, engineering tests and scientific validation are separate facts.
- New system lives in `src/co_scientist_next/`, independent of old
  `co_scientist` Orchestrator, profiles, events and Run recovery. Preserve G3 at
  `7313ca032e4f5f0c84578523e0f5639ad038e7af`; do not delete historical code.
- M09a records fixed Admission references; M10 separately owns parent and final
  qualification. M11 proposes Delta intent, M03 resolves it after child Inventory;
  M04/M05 independently decide material/appraisal reuse. Contract checks cannot
  prove scientific decisions, real Inventory completion or source access truth.
- Completed Goal Ethics decisions are only pass/reject. Clarification, policy/input
  problems and failures are execution states, not a third verdict. This does not
  change Candidate Ethics. R0 is not implemented; its accepted policy permits
  reliable core factual-error blocking, but not solely model memory or assistant
  paraphrase presented as original-source contradiction.
- M14 owns immutable Brief revisions; M01 owns scientific Goal preparation;
  M02 owns ethics. M12 schedules and does not judge scientific quality.
- Future scientific workflow: Goal preparation → Goal Ethics → background research → Generation;
  candidate Ethics/R0 → R1 → R2; ordinary R1 supplements return to R2;
  only R2 high-impact issues trigger R3, which returns to R2. Reflection
  cannot edit hypotheses. Ranking cannot retrieve or request scientific checks.
- Normal Run has one continuous Epoch and fixed admitted scientific inputs.
  Nondecisive matches do not update ratings. UCB selects only qualified admitted
  parents; final selection uses highest qualified μ, or no qualified winner.
  Children undergo their own scientific review and never inherit ratings.
- Record actual requests, responses/errors, retry lineage and available usage;
  unknown consumption stays unknown. Replay saved success locally. Applying one
  result and creating its successor must be atomic and idempotent. Ambiguous
  external outcomes require explicit recovery; never claim provider exactly-once.
- No user total resource budget, distributed framework, full event bus, separate
  Evidence View service, or G3 compatibility layer. W0 fixtures prove engineering
  behavior only. M01–M11 production science requires its own approved work.
- Focused checks: `PYTHONPATH=src python -m pytest -q tests/next` and
  `python -m ruff check src/co_scientist_next tests/next`. Use an available Python
  environment; no mandatory `.venv`. Update STATUS with executed checks and limits.
