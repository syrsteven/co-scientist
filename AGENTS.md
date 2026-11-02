# Co-Scientist development constraints

- Current architecture: `docs/design/m00-accepted-v1.0/01_ARCHITECTURE_BASELINE.md`
  and its accepted decision, ownership, dependency and handoff files. Its
  `reference/` directory is historical. W0 in `docs/design/w0-proposed-v0.1/`
  remains Proposed; this task adopts only M14a/M12/M15a engineering semantics.
- Read `docs/STATUS.md` for actual implementation and validation. Design
  acceptance, engineering tests and scientific validation are separate facts.
- New system lives in `src/co_scientist_next/`, independent of old
  `co_scientist` Orchestrator, profiles, events and Run recovery. Preserve G3 at
  `7313ca032e4f5f0c84578523e0f5639ad038e7af`; do not delete historical code.
- M14 owns immutable Brief revisions; M01 owns scientific Goal preparation;
  M02 owns ethics. M12 schedules and does not judge scientific quality.
- Future scientific workflow: Goal preparation → Goal Ethics → Generation;
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
