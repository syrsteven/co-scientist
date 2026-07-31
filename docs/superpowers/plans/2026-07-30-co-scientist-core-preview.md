# Co-Scientist Core Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a single-machine, CLI-first Co-Scientist Core Preview that proves the deterministic orchestration loop, durable raw-first external calls, policy-driven review admission, epoch-scoped tournament ranking, replay, and a traceable lens-regeneration smoke run.

**Architecture:** A pure Python domain core owns immutable scientific content, event-rebuilt projections, state transitions, Elo, budgets, and convergence policies. A deterministic Supervisor is the only task/state authority; typed worker skills communicate through AgentResult envelopes, while SQLite and a filesystem artifact store provide durability. Core Preview uses fake/replay adapters for deterministic tests plus one OpenAI adapter and one PubMed adapter; HTTP, SSE, React, four additional LLM providers, and full benchmarks are excluded.

**Tech Stack:** Python 3.11+, Pydantic v2, SQLAlchemy 2, Alembic, SQLite WAL, asyncio/AnyIO, Typer, httpx, OpenAI Python SDK, PyYAML, pytest, pytest-asyncio, respx, Ruff, mypy.

## Global Constraints

- Python requirement is `>=3.11,<3.13`; do not depend on Python 3.13-only features.
- Only Supervisor may create tasks, apply domain events, change lifecycle state, assign rating, or trigger follow-up work.
- `HypothesisContent` is immutable; lifecycle, review coverage, rating, and cluster data exist only in event-built projections.
- Every hypothesis requires `initial_review`; all other review stages are selected by `ReviewPolicy`.
- `paper_faithful` requires `full_review`; deep verification, observation, simulation, and recurrent review remain trigger-driven.
- `NoveltyAssessment` is produced from literature review; Proximity never infers literature novelty.
- Elo is comparable only inside one `TournamentEpoch` with frozen ResearchPlan, evaluation rules, ranking prompt, judge profile, admission policy, and rating policy hashes.
- Only decisive matches update Elo; inconclusive, invalid, and needs_tiebreaker do not.
- Elo plateau is auxiliary; quality convergence requires frozen anchors, top-k stability, cluster diversity plateau, and minimum budget/coverage.
- A normal Run must pass through `stopping` and finalization before `completed` or `completed_partial`.
- External calls follow `planned → started → raw_response_persisted → validated → agent_result_submitted → domain_result_applied`.
- Raw provider bytes are persisted before parsing or domain submission.
- Core Preview includes one real LLM provider, one literature provider, CLI, fake/replay, and a lens smoke test.
- Do not create FastAPI, SSE, React, multi-provider, GPQA, or full benchmark scaffolding in this plan.
- API keys come from environment variables and never enter events, prompts saved for export, logs, or test fixtures.
- Use TDD for every behavioral task and commit only the files named by that task.

---

## Target File Map

| Area | Files | Responsibility |
|---|---|---|
| Packaging | `pyproject.toml`, `src/co_scientist/__init__.py` | Installable Python package and CLI entry point |
| Evidence | `evidence/source_manifest.yaml`, `evidence/behavior_map.yaml`, `src/co_scientist/evidence/loader.py` | Source-level traceability for paper-aligned behavior |
| Domain | `src/co_scientist/domain/*.py` | Immutable models, projections, states, Elo, budgets, stop policy |
| Events | `src/co_scientist/events/models.py`, `src/co_scientist/events/reducers.py` | Versioned events and deterministic replay |
| Ports | `src/co_scientist/ports/*.py` | Provider, literature, artifact, persistence, clock interfaces |
| Persistence | `src/co_scientist/adapters/persistence/sqlite.py`, `src/co_scientist/adapters/artifacts/filesystem.py`, `alembic/*` | Durable event/task/call state and raw artifacts |
| Runtime | `src/co_scientist/runtime/external_calls.py`, `src/co_scientist/runtime/worker.py` | Lease execution and raw-first provider lifecycle |
| Supervisor | `src/co_scientist/supervisor/orchestrator.py`, `src/co_scientist/supervisor/followups.py` | Sole task/state authority |
| Skills | `skills/{generation,reflection,ranking,proximity,evolution,meta_review}/`, `src/co_scientist/skills/loader.py`, `src/co_scientist/agents/executor.py` | Six typed Core Preview agent contracts |
| Adapters | `src/co_scientist/adapters/llm/{fake,replay,openai_responses}.py`, `src/co_scientist/adapters/literature/pubmed.py` | Offline and real external providers |
| Application | `src/co_scientist/application/service.py`, `src/co_scientist/cli/app.py` | Stable command/query boundary and CLI |
| Smoke/export | `configs/profiles/core_preview.yaml`, `examples/lens_regeneration_goal.yaml`, `src/co_scientist/export/run_export.py` | Reproducible lens run and artifact bundle |
| Tests | `tests/unit`, `tests/contract`, `tests/scenario`, `tests/smoke` | Deterministic acceptance evidence |

---

### Task 1: Package Foundation and Evidence Contract

**Files:**
- Create: `pyproject.toml`
- Create: `src/co_scientist/__init__.py`
- Create: `src/co_scientist/evidence/__init__.py`
- Create: `src/co_scientist/evidence/loader.py`
- Create: `evidence/source_manifest.yaml`
- Create: `evidence/behavior_map.yaml`
- Create: `tests/unit/evidence/test_behavior_map.py`

**Interfaces:**
- Consumes: no project code
- Produces: `load_behavior_map(path: Path) -> tuple[BehaviorEvidence, ...]`; installable `co-scientist` package

- [ ] **Step 1: Write the failing evidence contract test**

```python
# tests/unit/evidence/test_behavior_map.py
from pathlib import Path

from co_scientist.evidence.loader import load_behavior_map


def test_every_behavior_has_a_valid_source_level_and_reference() -> None:
    items = load_behavior_map(Path("evidence/behavior_map.yaml"))
    assert {item.behavior_id for item in items} >= {
        "supervisor_single_authority",
        "initial_elo_1200",
        "evolution_child_readmission",
        "reflection_strategy_policy",
        "tournament_epoch_comparability",
    }
    assert all(item.source_level in {
        "paper_explicit",
        "supplement_explicit",
        "replica_default",
        "developer_extension",
    } for item in items)
    assert all(item.source_refs for item in items)
```

- [ ] **Step 2: Run the test and confirm the package is absent**

Run: `python3.11 -m pytest tests/unit/evidence/test_behavior_map.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'co_scientist'`.

- [ ] **Step 3: Create the package metadata**

```toml
# pyproject.toml
[build-system]
requires = ["setuptools>=69", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "co-scientist-replica"
version = "0.1.0.dev0"
requires-python = ">=3.11,<3.13"
dependencies = [
  "pydantic>=2.7,<3",
  "sqlalchemy>=2.0,<3",
  "alembic>=1.13,<2",
  "anyio>=4.4,<5",
  "typer>=0.12,<1",
  "httpx>=0.27,<1",
  "openai>=1.40,<3",
  "PyYAML>=6.0,<7",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.2,<9",
  "pytest-asyncio>=0.23,<1",
  "respx>=0.21,<1",
  "ruff>=0.5,<1",
  "mypy>=1.10,<2",
]

[project.scripts]
co-scientist = "co_scientist.cli.app:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["online: requires live external credentials"]

[tool.ruff]
line-length = 100
target-version = "py311"
```

- [ ] **Step 4: Implement the evidence loader**

```python
# src/co_scientist/evidence/loader.py
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, TypeAdapter

SourceLevel = Literal[
    "paper_explicit",
    "supplement_explicit",
    "replica_default",
    "developer_extension",
]


class BehaviorEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)
    behavior_id: str
    source_level: SourceLevel
    source_refs: tuple[str, ...]
    statement: str


def load_behavior_map(path: Path) -> tuple[BehaviorEvidence, ...]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return tuple(TypeAdapter(list[BehaviorEvidence]).validate_python(raw["behaviors"]))
```

- [ ] **Step 5: Add concrete source and behavior manifests**

```yaml
# evidence/source_manifest.yaml
sources:
  - id: nature_article
    url: https://www.nature.com/articles/s41586-026-10644-y
    accessed: 2026-07-30
  - id: nature_supplement
    url: https://static-content.springer.com/esm/art%3A10.1038%2Fs41586-026-10644-y/MediaObjects/41586_2026_10644_MOESM1_ESM.pdf
    accessed: 2026-07-30
```

```yaml
# evidence/behavior_map.yaml
behaviors:
  - behavior_id: supervisor_single_authority
    source_level: replica_default
    source_refs: [nature_supplement:note_8]
    statement: Supervisor alone creates tasks and applies state transitions.
  - behavior_id: initial_elo_1200
    source_level: paper_explicit
    source_refs: [nature_article:methods]
    statement: A newly admitted tournament entry receives rating 1200.
  - behavior_id: evolution_child_readmission
    source_level: supplement_explicit
    source_refs: [nature_supplement:note_8]
    statement: Evolution creates a child that re-enters the admission path.
  - behavior_id: reflection_strategy_policy
    source_level: replica_default
    source_refs: [nature_supplement:reflection_ladder]
    statement: Initial review is mandatory and advanced reviews are policy-driven.
  - behavior_id: tournament_epoch_comparability
    source_level: replica_default
    source_refs: [nature_article:ranking_methods]
    statement: Elo comparison is restricted to one frozen tournament contract.
```

- [ ] **Step 6: Install and run the evidence test**

Run: `python3.11 -m pip install -e '.[dev]' && python3.11 -m pytest tests/unit/evidence/test_behavior_map.py -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/co_scientist evidence tests/unit/evidence
git commit -m "chore: establish Core Preview package and evidence contract"
```

---

### Task 2: Immutable Hypothesis Content, Review Policy, Novelty, and Proximity Models

**Files:**
- Create: `src/co_scientist/domain/__init__.py`
- Create: `src/co_scientist/domain/hypothesis.py`
- Create: `src/co_scientist/domain/review.py`
- Create: `src/co_scientist/domain/proximity.py`
- Create: `src/co_scientist/domain/provenance.py`
- Create: `tests/unit/domain/test_hypothesis_models.py`
- Create: `tests/unit/domain/test_review_policy.py`
- Create: `tests/unit/domain/test_novelty_proximity_boundary.py`

**Interfaces:**
- Consumes: Pydantic
- Produces: `HypothesisContent`, `HypothesisProjection`, `ReviewPolicy`, `Review`, `NoveltyAssessment`, `ProximityEdge`, `required_review_stages(policy)`

- [ ] **Step 1: Write failing immutability and projection tests**

```python
# tests/unit/domain/test_hypothesis_models.py
import pytest
from pydantic import ValidationError

from co_scientist.domain.hypothesis import HypothesisContent, HypothesisProjection


def test_scientific_content_is_frozen_but_projection_is_rebuildable() -> None:
    content = HypothesisContent(
        content_id="h-content-1",
        title="Capsular mechanics gate lens epithelial cell fate",
        claim="Early capsule strain biases residual cells toward ordered fibers.",
        mechanism_chain=("surgery", "strain", "cell_state", "morphogenesis", "transparency"),
        assumptions=("strain is sensed before EMT commitment",),
        predictions=("early strain normalization reduces fibrosis",),
        falsifiers=("strain changes without cell-state or morphology changes",),
    )
    with pytest.raises(ValidationError):
        content.title = "mutated"

    projection = HypothesisProjection(hypothesis_id="h-1", content_id=content.content_id)
    updated = projection.model_copy(update={"lifecycle_state": "screening"})
    assert updated.lifecycle_state == "screening"
    assert content.title.startswith("Capsular")
```

- [ ] **Step 2: Write failing policy and Novelty/Proximity separation tests**

```python
# tests/unit/domain/test_review_policy.py
from co_scientist.domain.review import ReviewPolicy, ReviewStage, required_review_stages


def test_initial_is_always_required_and_paper_faithful_adds_full() -> None:
    minimal = ReviewPolicy(profile_id="minimal", required_before_admission=())
    faithful = ReviewPolicy(
        profile_id="paper_faithful",
        required_before_admission=(ReviewStage.FULL,),
    )
    assert required_review_stages(minimal) == {ReviewStage.INITIAL}
    assert required_review_stages(faithful) == {ReviewStage.INITIAL, ReviewStage.FULL}
```

```python
# tests/unit/domain/test_novelty_proximity_boundary.py
from co_scientist.domain.proximity import ProximityEdge
from co_scientist.domain.review import NoveltyAssessment, NoveltyVerdict


def test_proximity_has_no_literature_novelty_verdict() -> None:
    edge = ProximityEdge(left_id="h-1", right_id="h-2", similarity=4)
    assert "novelty_verdict" not in edge.model_fields
    assessment = NoveltyAssessment(
        assessment_id="n-1",
        hypothesis_id="h-1",
        content_hash="sha256:abc",
        research_plan_version=1,
        verdict=NoveltyVerdict.PARTIALLY_NOVEL,
        closest_prior_work_ids=("pmid:1",),
    )
    assert assessment.verdict is NoveltyVerdict.PARTIALLY_NOVEL
```

- [ ] **Step 3: Run the tests and verify missing models**

Run: `python3.11 -m pytest tests/unit/domain/test_hypothesis_models.py tests/unit/domain/test_review_policy.py tests/unit/domain/test_novelty_proximity_boundary.py -q`

Expected: FAIL on missing domain modules.

- [ ] **Step 4: Implement the immutable content and projection**

```python
# src/co_scientist/domain/hypothesis.py
from typing import Literal

import hashlib
import json

from pydantic import BaseModel, ConfigDict, Field, computed_field


class HypothesisContent(BaseModel):
    model_config = ConfigDict(frozen=True)
    content_id: str
    title: str
    claim: str
    mechanism_chain: tuple[str, ...]
    assumptions: tuple[str, ...]
    predictions: tuple[str, ...]
    falsifiers: tuple[str, ...]
    parent_content_ids: tuple[str, ...] = ()
    supersedes_content_id: str | None = None

    @computed_field
    @property
    def content_hash(self) -> str:
        canonical = json.dumps(
            {
                "title": self.title,
                "claim": self.claim,
                "mechanism_chain": self.mechanism_chain,
                "assumptions": self.assumptions,
                "predictions": self.predictions,
                "falsifiers": self.falsifiers,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class HypothesisProjection(BaseModel):
    hypothesis_id: str
    content_id: str
    lifecycle_state: Literal[
        "created",
        "screening",
        "admission_pending",
        "tournament_ready",
        "tournament_active",
        "rejected",
        "safety_blocked",
        "duplicate_archived",
        "archived",
    ] = "created"
    safety_status: str = "pending"
    review_coverage: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    novelty_assessment_ids: tuple[str, ...] = ()
    tournament_entries_by_epoch: dict[str, str] = Field(default_factory=dict)
    ratings_by_epoch: dict[str, float] = Field(default_factory=dict)
    cluster_ids: tuple[str, ...] = ()
```

- [ ] **Step 5: Implement review policy and novelty assessment**

```python
# src/co_scientist/domain/review.py
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ReviewStage(StrEnum):
    INITIAL = "initial_review"
    FULL = "full_review"
    DEEP = "deep_verification"
    OBSERVATION = "observation_review"
    SIMULATION = "simulation_review"
    RECURRENT = "recurrent_review"


class ReviewPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)
    profile_id: str
    required_before_admission: tuple[ReviewStage, ...] = ()
    trigger_rules: dict[ReviewStage, tuple[str, ...]] = Field(default_factory=dict)


def required_review_stages(policy: ReviewPolicy) -> set[ReviewStage]:
    return {ReviewStage.INITIAL, *policy.required_before_admission}


class Review(BaseModel):
    model_config = ConfigDict(frozen=True)
    review_id: str
    hypothesis_id: str
    content_hash: str
    stage: ReviewStage
    recommendation: Literal["pass", "reject", "needs_more_evidence"]
    dimension_scores: dict[str, float] = Field(default_factory=dict)
    critical_flaws: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()


class NoveltyVerdict(StrEnum):
    NOVEL = "novel"
    PARTIALLY_NOVEL = "partially_novel"
    NOT_NOVEL = "not_novel"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class NoveltyAssessment(BaseModel):
    model_config = ConfigDict(frozen=True)
    assessment_id: str
    hypothesis_id: str
    content_hash: str
    research_plan_version: int
    verdict: NoveltyVerdict
    closest_prior_work_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...] = ()
```

- [ ] **Step 6: Implement the candidate-space proximity model**

```python
# src/co_scientist/domain/proximity.py
from pydantic import BaseModel, ConfigDict, Field


class ProximityEdge(BaseModel):
    model_config = ConfigDict(frozen=True)
    left_id: str
    right_id: str
    similarity: int = Field(ge=1, le=5)
    mechanism_overlap: tuple[str, ...] = ()
    duplicate_likelihood: float = Field(default=0.0, ge=0.0, le=1.0)
```

```python
# src/co_scientist/domain/provenance.py
from typing import Literal

from pydantic import BaseModel, ConfigDict


class SourceDocument(BaseModel):
    model_config = ConfigDict(frozen=True)
    source_id: str
    provider: str
    canonical_id: str
    title: str
    authors: tuple[str, ...] = ()
    publication_date: str | None = None
    retrieval_query: str
    raw_artifact_ref: str


class EvidenceItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    evidence_id: str
    source_id: str
    locator: str
    statement: str
    relation: Literal["supports", "refutes", "context_only", "conflicts"]
```

- [ ] **Step 7: Run focused tests**

Run: `python3.11 -m pytest tests/unit/domain/test_hypothesis_models.py tests/unit/domain/test_review_policy.py tests/unit/domain/test_novelty_proximity_boundary.py -q`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/co_scientist/domain tests/unit/domain
git commit -m "feat: define immutable hypotheses and policy-driven reviews"
```

---

### Task 3: Run, Task, ExternalCall, and Finalization State Machines

**Files:**
- Create: `src/co_scientist/domain/states.py`
- Create: `src/co_scientist/domain/transitions.py`
- Create: `src/co_scientist/domain/task.py`
- Create: `src/co_scientist/domain/external_call.py`
- Create: `tests/unit/domain/test_run_transitions.py`
- Create: `tests/unit/domain/test_task_transitions.py`
- Create: `tests/unit/domain/test_external_call_transitions.py`

**Interfaces:**
- Consumes: no prior domain behavior
- Produces: `transition_run`, `transition_task`, `transition_external_call`, `RunState`, `TaskState`, `ExternalCallState`

- [ ] **Step 1: Write the failing Run finalization test**

```python
# tests/unit/domain/test_run_transitions.py
import pytest

from co_scientist.domain.states import RunState
from co_scientist.domain.transitions import InvalidTransition, transition_run


def test_running_cannot_complete_without_stopping() -> None:
    with pytest.raises(InvalidTransition):
        transition_run(RunState.RUNNING, RunState.COMPLETED)
    assert transition_run(RunState.RUNNING, RunState.STOPPING) is RunState.STOPPING
    assert transition_run(RunState.STOPPING, RunState.COMPLETED) is RunState.COMPLETED
```

- [ ] **Step 2: Write the failing ExternalCall order test**

```python
# tests/unit/domain/test_external_call_transitions.py
import pytest

from co_scientist.domain.states import ExternalCallState
from co_scientist.domain.transitions import InvalidTransition, transition_external_call


def test_raw_response_must_precede_validation() -> None:
    with pytest.raises(InvalidTransition):
        transition_external_call(ExternalCallState.STARTED, ExternalCallState.VALIDATED)
    state = ExternalCallState.PLANNED
    for target in (
        ExternalCallState.STARTED,
        ExternalCallState.RAW_RESPONSE_PERSISTED,
        ExternalCallState.VALIDATED,
        ExternalCallState.AGENT_RESULT_SUBMITTED,
        ExternalCallState.DOMAIN_RESULT_APPLIED,
    ):
        state = transition_external_call(state, target)
    assert state is ExternalCallState.DOMAIN_RESULT_APPLIED
```

- [ ] **Step 3: Run tests and confirm missing transition code**

Run: `python3.11 -m pytest tests/unit/domain/test_run_transitions.py tests/unit/domain/test_external_call_transitions.py -q`

Expected: FAIL on missing modules.

- [ ] **Step 4: Define enums and explicit transition tables**

```python
# src/co_scientist/domain/states.py
from enum import StrEnum


class RunState(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    PAUSING = "pausing"
    PAUSED = "paused"
    NEEDS_ATTENTION = "needs_attention"
    STOPPING = "stopping"
    COMPLETED = "completed"
    COMPLETED_PARTIAL = "completed_partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskState(StrEnum):
    PENDING = "pending"
    LEASED = "leased"
    RUNNING = "running"
    RESULT_RECEIVED = "result_received"
    SUCCEEDED = "succeeded"
    BLOCKED = "blocked"
    NEEDS_ATTENTION = "needs_attention"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExternalCallState(StrEnum):
    PLANNED = "planned"
    STARTED = "started"
    RAW_RESPONSE_PERSISTED = "raw_response_persisted"
    VALIDATED = "validated"
    AGENT_RESULT_SUBMITTED = "agent_result_submitted"
    DOMAIN_RESULT_APPLIED = "domain_result_applied"
    FAILED_BEFORE_RESPONSE = "failed_before_response"
    RAW_PERSIST_FAILED = "raw_persist_failed"
    VALIDATION_FAILED = "validation_failed"
    SUBMISSION_FAILED = "submission_failed"
    DOMAIN_APPLY_FAILED = "domain_apply_failed"
```

```python
# src/co_scientist/domain/transitions.py
from co_scientist.domain.states import ExternalCallState, RunState, TaskState


class InvalidTransition(ValueError):
    pass


def _transition(current, target, allowed):
    if target not in allowed[current]:
        raise InvalidTransition(f"{current} -> {target}")
    return target


RUN_TRANSITIONS = {
    RunState.CREATED: {RunState.RUNNING, RunState.CANCELLED},
    RunState.RUNNING: {
        RunState.PAUSING, RunState.NEEDS_ATTENTION, RunState.STOPPING,
        RunState.FAILED, RunState.CANCELLED,
    },
    RunState.PAUSING: {RunState.PAUSED, RunState.CANCELLED},
    RunState.PAUSED: {RunState.RUNNING, RunState.STOPPING, RunState.CANCELLED},
    RunState.NEEDS_ATTENTION: {
        RunState.RUNNING, RunState.FAILED, RunState.CANCELLED,
    },
    RunState.STOPPING: {RunState.COMPLETED, RunState.COMPLETED_PARTIAL},
    RunState.COMPLETED: set(),
    RunState.COMPLETED_PARTIAL: set(),
    RunState.FAILED: set(),
    RunState.CANCELLED: set(),
}

TASK_TRANSITIONS = {
    TaskState.PENDING: {TaskState.LEASED, TaskState.BLOCKED, TaskState.CANCELLED},
    TaskState.LEASED: {TaskState.RUNNING, TaskState.PENDING, TaskState.CANCELLED},
    TaskState.RUNNING: {
        TaskState.RESULT_RECEIVED, TaskState.PENDING, TaskState.NEEDS_ATTENTION,
        TaskState.FAILED,
    },
    TaskState.RESULT_RECEIVED: {TaskState.SUCCEEDED, TaskState.PENDING},
    TaskState.BLOCKED: {TaskState.PENDING, TaskState.CANCELLED},
    TaskState.NEEDS_ATTENTION: {TaskState.PENDING, TaskState.CANCELLED},
    TaskState.SUCCEEDED: set(),
    TaskState.FAILED: set(),
    TaskState.CANCELLED: set(),
}

EXTERNAL_CALL_TRANSITIONS = {
    ExternalCallState.PLANNED: {
        ExternalCallState.STARTED, ExternalCallState.FAILED_BEFORE_RESPONSE,
    },
    ExternalCallState.STARTED: {
        ExternalCallState.RAW_RESPONSE_PERSISTED,
        ExternalCallState.FAILED_BEFORE_RESPONSE,
        ExternalCallState.RAW_PERSIST_FAILED,
    },
    ExternalCallState.RAW_RESPONSE_PERSISTED: {
        ExternalCallState.VALIDATED, ExternalCallState.VALIDATION_FAILED,
    },
    ExternalCallState.VALIDATED: {
        ExternalCallState.AGENT_RESULT_SUBMITTED,
        ExternalCallState.SUBMISSION_FAILED,
    },
    ExternalCallState.AGENT_RESULT_SUBMITTED: {
        ExternalCallState.DOMAIN_RESULT_APPLIED,
        ExternalCallState.DOMAIN_APPLY_FAILED,
    },
    ExternalCallState.DOMAIN_RESULT_APPLIED: set(),
    ExternalCallState.FAILED_BEFORE_RESPONSE: set(),
    ExternalCallState.RAW_PERSIST_FAILED: set(),
    ExternalCallState.VALIDATION_FAILED: set(),
    ExternalCallState.SUBMISSION_FAILED: set(),
    ExternalCallState.DOMAIN_APPLY_FAILED: set(),
}


def transition_run(current: RunState, target: RunState) -> RunState:
    return _transition(current, target, RUN_TRANSITIONS)


def transition_task(current: TaskState, target: TaskState) -> TaskState:
    return _transition(current, target, TASK_TRANSITIONS)


def transition_external_call(
    current: ExternalCallState, target: ExternalCallState
) -> ExternalCallState:
    return _transition(current, target, EXTERNAL_CALL_TRANSITIONS)
```

```python
# src/co_scientist/domain/task.py
from typing import Literal

from pydantic import BaseModel, ConfigDict

from co_scientist.domain.states import TaskState


class NewTask(BaseModel):
    model_config = ConfigDict(frozen=True)
    task_id: str
    run_id: str
    idempotency_key: str
    intent_type: str
    payload: dict
    created_by: Literal["supervisor"] = "supervisor"


class TaskMutation(BaseModel):
    model_config = ConfigDict(frozen=True)
    task_id: str
    target_state: TaskState

    @classmethod
    def succeed(cls, task_id: str) -> "TaskMutation":
        return cls(task_id=task_id, target_state=TaskState.SUCCEEDED)
```

```python
# src/co_scientist/domain/external_call.py
from pydantic import BaseModel

from co_scientist.domain.states import ExternalCallState


class ExternalCall(BaseModel):
    external_call_id: str
    task_id: str
    attempt: int
    request_fingerprint: str
    provider: str
    model_or_tool: str
    state: ExternalCallState = ExternalCallState.PLANNED
    raw_artifact_ref: str | None = None
    validated_artifact_ref: str | None = None
    agent_result_id: str | None = None
    applied_domain_sequence: int | None = None
    parent_call_id: str | None = None
```

- [ ] **Step 5: Add task retry, lease-expiry, and terminal tests**

```python
# tests/unit/domain/test_task_transitions.py
import pytest

from co_scientist.domain.states import TaskState
from co_scientist.domain.transitions import InvalidTransition, transition_task


def test_expired_lease_returns_to_pending_but_success_is_terminal() -> None:
    assert transition_task(TaskState.LEASED, TaskState.PENDING) is TaskState.PENDING
    with pytest.raises(InvalidTransition):
        transition_task(TaskState.SUCCEEDED, TaskState.PENDING)
```

- [ ] **Step 6: Run all transition tests**

Run: `python3.11 -m pytest tests/unit/domain/test_run_transitions.py tests/unit/domain/test_task_transitions.py tests/unit/domain/test_external_call_transitions.py -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/co_scientist/domain/states.py src/co_scientist/domain/transitions.py src/co_scientist/domain/task.py src/co_scientist/domain/external_call.py tests/unit/domain
git commit -m "feat: enforce durable Core Preview state machines"
```

---

### Task 4: TournamentEpoch, Match Decisions, and Elo

**Files:**
- Create: `src/co_scientist/domain/tournament.py`
- Create: `src/co_scientist/domain/elo.py`
- Create: `tests/unit/domain/test_tournament_epoch.py`
- Create: `tests/unit/domain/test_match_decisions.py`
- Create: `tests/unit/domain/test_elo.py`

**Interfaces:**
- Consumes: `HypothesisContent`
- Produces: `TournamentEpoch`, `TournamentEntry`, `MatchResult`, `admit_entry`, `apply_match`

- [ ] **Step 1: Write failing epoch-comparability tests**

```python
# tests/unit/domain/test_tournament_epoch.py
import pytest

from co_scientist.domain.tournament import (
    EpochContractMismatch,
    TournamentEpoch,
    validate_match_contract,
)


def test_prompt_or_plan_mismatch_invalidates_match_contract() -> None:
    epoch = TournamentEpoch(
        epoch_id="epoch-1",
        research_plan_version=1,
        evaluation_rules_hash="rules-a",
        ranking_prompt_hash="prompt-a",
        judge_profile_hash="judge-a",
        rating_policy_version="elo-v1",
        admission_policy_version="admission-v1",
    )
    with pytest.raises(EpochContractMismatch):
        validate_match_contract(epoch, plan_version=2, prompt_hash="prompt-a",
                                judge_hash="judge-a", rating_policy="elo-v1")
```

- [ ] **Step 2: Write failing non-decisive Elo tests**

```python
# tests/unit/domain/test_match_decisions.py
import pytest

from co_scientist.domain.tournament import MatchDecision, MatchResult, apply_match


@pytest.mark.parametrize("decision", [
    MatchDecision.INCONCLUSIVE,
    MatchDecision.INVALID,
    MatchDecision.NEEDS_TIEBREAKER,
])
def test_non_decisive_match_does_not_update_rating(decision) -> None:
    result = MatchResult(
        match_id="m-1", epoch_id="e-1", left_id="h-1", right_id="h-2",
        decision=decision,
    )
    with pytest.raises(ValueError, match="decisive"):
        apply_match(1200.0, 1200.0, result)
```

- [ ] **Step 3: Run tests and confirm missing tournament code**

Run: `python3.11 -m pytest tests/unit/domain/test_tournament_epoch.py tests/unit/domain/test_match_decisions.py -q`

Expected: FAIL on missing module.

- [ ] **Step 4: Implement frozen epoch and match models**

```python
# src/co_scientist/domain/tournament.py
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, model_validator


class MatchDecision(StrEnum):
    DECISIVE = "decisive"
    INCONCLUSIVE = "inconclusive"
    INVALID = "invalid"
    NEEDS_TIEBREAKER = "needs_tiebreaker"


class TournamentEpoch(BaseModel):
    model_config = ConfigDict(frozen=True)
    epoch_id: str
    research_plan_version: int
    evaluation_rules_hash: str
    ranking_prompt_hash: str
    judge_profile_hash: str
    rating_policy_version: str
    admission_policy_version: str
    anchor_set_id: str | None = None


class TournamentEntry(BaseModel):
    model_config = ConfigDict(frozen=True)
    epoch_id: str
    hypothesis_id: str
    content_hash: str
    rating: float = 1200.0
    matches_played: int = 0


class MatchResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    match_id: str
    epoch_id: str
    left_id: str
    right_id: str
    decision: MatchDecision
    winner_id: str | None = None

    @model_validator(mode="after")
    def validate_winner(self) -> "MatchResult":
        decisive = self.decision is MatchDecision.DECISIVE
        if decisive and self.winner_id not in {self.left_id, self.right_id}:
            raise ValueError("decisive match requires a valid winner")
        if not decisive and self.winner_id is not None:
            raise ValueError("non-decisive match cannot have a winner")
        return self
```

```python
class EpochContractMismatch(ValueError):
    pass


def validate_match_contract(
    epoch: TournamentEpoch, *, plan_version: int, prompt_hash: str,
    judge_hash: str, rating_policy: str,
) -> None:
    actual = (plan_version, prompt_hash, judge_hash, rating_policy)
    expected = (
        epoch.research_plan_version,
        epoch.ranking_prompt_hash,
        epoch.judge_profile_hash,
        epoch.rating_policy_version,
    )
    if actual != expected:
        raise EpochContractMismatch(f"{actual} != {expected}")


def admit_entry(
    epoch: TournamentEpoch, hypothesis_id: str, content_hash: str,
    initial_rating: float = 1200.0,
) -> TournamentEntry:
    return TournamentEntry(
        epoch_id=epoch.epoch_id,
        hypothesis_id=hypothesis_id,
        content_hash=content_hash,
        rating=initial_rating,
    )
```

- [ ] **Step 5: Implement epoch admission and pure Elo update**

```python
# src/co_scientist/domain/elo.py
def expected_score(rating: float, opponent_rating: float) -> float:
    return 1.0 / (1.0 + 10.0 ** ((opponent_rating - rating) / 400.0))


def update_pair(winner: float, loser: float, k_factor: float = 32.0) -> tuple[float, float]:
    winner_expected = expected_score(winner, loser)
    loser_expected = expected_score(loser, winner)
    return (
        winner + k_factor * (1.0 - winner_expected),
        loser + k_factor * (0.0 - loser_expected),
    )
```

```python
# src/co_scientist/domain/tournament.py
from co_scientist.domain.elo import update_pair


def apply_match(
    left_rating: float, right_rating: float, result: MatchResult,
    *, k_factor: float = 32.0,
) -> tuple[float, float]:
    if result.decision is not MatchDecision.DECISIVE:
        raise ValueError("only decisive matches update rating")
    if result.winner_id == result.left_id:
        return update_pair(left_rating, right_rating, k_factor)
    winner, loser = update_pair(right_rating, left_rating, k_factor)
    return loser, winner
```

- [ ] **Step 6: Add exact Elo test**

```python
# tests/unit/domain/test_elo.py
from co_scientist.domain.elo import update_pair


def test_equal_ratings_move_by_half_k() -> None:
    winner, loser = update_pair(1200.0, 1200.0, k_factor=32.0)
    assert winner == 1216.0
    assert loser == 1184.0
```

- [ ] **Step 7: Run tournament tests**

Run: `python3.11 -m pytest tests/unit/domain/test_tournament_epoch.py tests/unit/domain/test_match_decisions.py tests/unit/domain/test_elo.py -q`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/co_scientist/domain/tournament.py src/co_scientist/domain/elo.py tests/unit/domain
git commit -m "feat: scope tournament ratings to frozen epochs"
```

---

### Task 5: Budget Ledger, Anchors, and Convergence Stop Policy

**Files:**
- Create: `src/co_scientist/domain/budget.py`
- Create: `src/co_scientist/domain/convergence.py`
- Create: `tests/unit/domain/test_budget.py`
- Create: `tests/unit/domain/test_convergence.py`

**Interfaces:**
- Consumes: epoch-scoped checkpoint metrics
- Produces: `BudgetPolicy`, `BudgetLedger`, `ConvergenceSnapshot`, `StopDecision`, `evaluate_stop`

- [ ] **Step 1: Write failing unlimited-budget and hard-limit tests**

```python
# tests/unit/domain/test_budget.py
from decimal import Decimal

from co_scientist.domain.budget import BudgetLedger, BudgetPolicy


def test_null_cost_limit_is_unlimited_but_usage_is_recorded() -> None:
    ledger = BudgetLedger(policy=BudgetPolicy(max_usd=None))
    updated = ledger.settle(cost_usd=Decimal("12.34"), model_calls=1)
    assert updated.cost_usd == Decimal("12.34")
    assert not updated.hard_limit_reached
```

- [ ] **Step 2: Write the failing Elo-only stop rejection test**

```python
# tests/unit/domain/test_convergence.py
from co_scientist.domain.convergence import ConvergenceSnapshot, evaluate_stop


def test_elo_plateau_cannot_stop_without_anchor_topk_cluster_and_budget() -> None:
    decision = evaluate_stop(
        ConvergenceSnapshot(
            epoch_id="e-1",
            elo_plateau=True,
            anchor_plateau=False,
            top_k_stable=False,
            cluster_diversity_plateau=False,
            minimum_budget_satisfied=False,
        ),
        hard_budget_reached=False,
        scientist_action=None,
    )
    assert not decision.should_stop
    assert decision.auxiliary_signals == ("elo_plateau",)
```

- [ ] **Step 3: Run tests and confirm missing policies**

Run: `python3.11 -m pytest tests/unit/domain/test_budget.py tests/unit/domain/test_convergence.py -q`

Expected: FAIL on missing modules.

- [ ] **Step 4: Implement immutable budget settlement**

```python
# src/co_scientist/domain/budget.py
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class BudgetPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)
    max_usd: Decimal | None = None
    max_model_calls: int | None = None
    max_hypotheses: int | None = None
    max_matches: int | None = None


class CostEntry(BaseModel):
    model_config = ConfigDict(frozen=True)
    cost_entry_id: str
    run_id: str
    external_call_id: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal("0")
    pricing_version: str


class BudgetLedger(BaseModel):
    model_config = ConfigDict(frozen=True)
    policy: BudgetPolicy
    cost_usd: Decimal = Decimal("0")
    model_calls: int = 0

    def settle(self, *, cost_usd: Decimal, model_calls: int) -> "BudgetLedger":
        return self.model_copy(update={
            "cost_usd": self.cost_usd + cost_usd,
            "model_calls": self.model_calls + model_calls,
        })

    @property
    def hard_limit_reached(self) -> bool:
        return (
            self.policy.max_usd is not None and self.cost_usd >= self.policy.max_usd
        ) or (
            self.policy.max_model_calls is not None
            and self.model_calls >= self.policy.max_model_calls
        )
```

- [ ] **Step 5: Implement convergence rules with frozen epoch IDs**

```python
# src/co_scientist/domain/convergence.py
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ConvergenceSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)
    epoch_id: str
    elo_plateau: bool
    anchor_plateau: bool
    top_k_stable: bool
    cluster_diversity_plateau: bool
    minimum_budget_satisfied: bool


class StopDecision(BaseModel):
    model_config = ConfigDict(frozen=True)
    action: Literal["continue", "stop", "cancel"]
    reason: str | None
    auxiliary_signals: tuple[str, ...] = ()

    @property
    def should_stop(self) -> bool:
        return self.action == "stop"


def evaluate_stop(
    snapshot: ConvergenceSnapshot,
    *,
    hard_budget_reached: bool,
    scientist_action: Literal["soft_stop", "hard_cancel"] | None,
) -> StopDecision:
    if scientist_action == "hard_cancel":
        return StopDecision(action="cancel", reason="scientist_cancel")
    if scientist_action == "soft_stop":
        return StopDecision(action="stop", reason="scientist_stop")
    if hard_budget_reached:
        return StopDecision(action="stop", reason="hard_budget_reached")
    primary = (
        snapshot.anchor_plateau
        and snapshot.top_k_stable
        and snapshot.cluster_diversity_plateau
        and snapshot.minimum_budget_satisfied
    )
    return StopDecision(
        action="stop" if primary else "continue",
        reason="quality_converged" if primary else None,
        auxiliary_signals=("elo_plateau",) if snapshot.elo_plateau else (),
    )
```

- [ ] **Step 6: Add tests for hard budget, scientist stop, and missing anchors**

```python
def convergence_snapshot(*, anchor_plateau: bool) -> ConvergenceSnapshot:
    return ConvergenceSnapshot(
        epoch_id="e-1",
        elo_plateau=True,
        anchor_plateau=anchor_plateau,
        top_k_stable=True,
        cluster_diversity_plateau=True,
        minimum_budget_satisfied=True,
    )


def test_missing_anchor_evidence_disables_quality_stop() -> None:
    snapshot = ConvergenceSnapshot(
        epoch_id="e-1",
        elo_plateau=True,
        anchor_plateau=False,
        top_k_stable=True,
        cluster_diversity_plateau=True,
        minimum_budget_satisfied=True,
    )
    assert not evaluate_stop(
        snapshot, hard_budget_reached=False, scientist_action=None
    ).should_stop


def test_hard_budget_and_scientist_actions_are_terminal() -> None:
    snapshot = convergence_snapshot(anchor_plateau=False)
    budget = evaluate_stop(
        snapshot, hard_budget_reached=True, scientist_action=None
    )
    soft = evaluate_stop(
        snapshot, hard_budget_reached=False, scientist_action="soft_stop"
    )
    hard = evaluate_stop(
        snapshot, hard_budget_reached=False, scientist_action="hard_cancel"
    )
    assert (budget.action, soft.action, hard.action) == ("stop", "stop", "cancel")
```

- [ ] **Step 7: Run focused tests**

Run: `python3.11 -m pytest tests/unit/domain/test_budget.py tests/unit/domain/test_convergence.py -q`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/co_scientist/domain/budget.py src/co_scientist/domain/convergence.py tests/unit/domain
git commit -m "feat: add budget and anchor-based convergence policies"
```

---

### Task 6: Domain Events and Deterministic Projection Replay

**Files:**
- Create: `src/co_scientist/events/__init__.py`
- Create: `src/co_scientist/events/models.py`
- Create: `src/co_scientist/events/reducers.py`
- Create: `src/co_scientist/ports/event_store.py`
- Create: `tests/unit/events/test_hypothesis_replay.py`
- Create: `tests/unit/events/test_epoch_replay.py`

**Interfaces:**
- Consumes: domain models from Tasks 2–5
- Produces: `DomainEvent`, `NewEvent`, `reduce_hypothesis`, `replay_hypothesis`, `EventStore`

- [ ] **Step 1: Write failing projection replay test**

```python
# tests/unit/events/test_hypothesis_replay.py
from co_scientist.events.models import DomainEvent
from co_scientist.events.reducers import replay_hypothesis


def test_replay_rebuilds_coverage_without_mutating_content() -> None:
    events = [
        DomainEvent(sequence=1, run_id="r-1", event_type="HypothesisContentCreated",
                    payload={"hypothesis_id": "h-1", "content_id": "c-1"}),
        DomainEvent(sequence=2, run_id="r-1", event_type="ReviewCompleted",
                    payload={"hypothesis_id": "h-1", "stage": "initial_review",
                             "review_id": "rev-1"}),
        DomainEvent(sequence=3, run_id="r-1", event_type="HypothesisTournamentReady",
                    payload={"hypothesis_id": "h-1"}),
    ]
    projection = replay_hypothesis("h-1", events)
    assert projection.review_coverage["initial_review"] == ("rev-1",)
    assert projection.lifecycle_state == "tournament_ready"
```

- [ ] **Step 2: Run the test and confirm missing event code**

Run: `python3.11 -m pytest tests/unit/events/test_hypothesis_replay.py -q`

Expected: FAIL on missing module.

- [ ] **Step 3: Implement versioned events and event-store protocol**

```python
# src/co_scientist/events/models.py
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DomainEvent(BaseModel):
    model_config = ConfigDict(frozen=True)
    sequence: int
    run_id: str
    event_type: str
    schema_version: int = 1
    payload: dict[str, Any]
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    causation_id: str | None = None
    correlation_id: str | None = None


class NewEvent(BaseModel):
    model_config = ConfigDict(frozen=True)
    event_type: str
    schema_version: int = 1
    payload: dict[str, Any]
    causation_id: str | None = None
    correlation_id: str | None = None
```

```python
# src/co_scientist/ports/event_store.py
from typing import Protocol, Sequence

from co_scientist.events.models import DomainEvent, NewEvent


class ConcurrencyConflict(RuntimeError):
    pass


class EventStore(Protocol):
    def load(self, run_id: str, after_sequence: int = 0) -> list[DomainEvent]: ...
    def append(self, run_id: str, expected_sequence: int,
               events: Sequence[NewEvent]) -> list[DomainEvent]: ...
```

- [ ] **Step 4: Implement pure reducers with exhaustive event matching**

```python
# src/co_scientist/events/reducers.py
from pydantic import BaseModel, Field

from co_scientist.domain.hypothesis import HypothesisProjection
from co_scientist.events.models import DomainEvent


def replay_hypothesis(hypothesis_id: str, events: list[DomainEvent]) -> HypothesisProjection:
    projection: HypothesisProjection | None = None
    for event in events:
        if event.event_type == "HypothesisContentCreated":
            if event.payload["hypothesis_id"] == hypothesis_id:
                projection = HypothesisProjection(
                    hypothesis_id=hypothesis_id,
                    content_id=event.payload["content_id"],
                )
        elif event.event_type == "ReviewCompleted" and projection is not None:
            if event.payload["hypothesis_id"] == hypothesis_id:
                coverage = dict(projection.review_coverage)
                stage = event.payload["stage"]
                coverage[stage] = (*coverage.get(stage, ()), event.payload["review_id"])
                projection = projection.model_copy(update={"review_coverage": coverage})
        elif event.event_type == "HypothesisTournamentReady" and projection is not None:
            projection = projection.model_copy(update={"lifecycle_state": "tournament_ready"})
    if projection is None:
        raise KeyError(hypothesis_id)
    return projection


class TournamentProjection(BaseModel):
    ratings: dict[str, dict[str, float]] = Field(default_factory=dict)
    epoch_plan_versions: dict[str, int] = Field(default_factory=dict)


def replay_tournament(events: list[DomainEvent]) -> TournamentProjection:
    projection = TournamentProjection()
    for event in events:
        if event.event_type == "TournamentEpochOpened":
            versions = dict(projection.epoch_plan_versions)
            versions[event.payload["epoch_id"]] = event.payload["research_plan_version"]
            projection = projection.model_copy(update={"epoch_plan_versions": versions})
        elif event.event_type in {"TournamentEntryCreated", "RatingUpdated"}:
            ratings = {epoch: dict(values) for epoch, values in projection.ratings.items()}
            epoch = event.payload["epoch_id"]
            ratings.setdefault(epoch, {})[event.payload["hypothesis_id"]] = event.payload["rating"]
            projection = projection.model_copy(update={"ratings": ratings})
    return projection
```

- [ ] **Step 5: Add epoch replay test**

```python
# tests/unit/events/test_epoch_replay.py
from co_scientist.events.models import DomainEvent
from co_scientist.events.reducers import replay_tournament


def test_new_epoch_restarts_rating_at_1200() -> None:
    projection = replay_tournament([
        DomainEvent(
            sequence=1, run_id="r-1", event_type="TournamentEpochOpened",
            payload={"epoch_id": "e-1", "research_plan_version": 1},
        ),
        DomainEvent(
            sequence=2, run_id="r-1", event_type="TournamentEntryCreated",
            payload={"epoch_id": "e-1", "hypothesis_id": "h-1", "rating": 1200.0},
        ),
        DomainEvent(
            sequence=3, run_id="r-1", event_type="RatingUpdated",
            payload={"epoch_id": "e-1", "hypothesis_id": "h-1", "rating": 1280.0},
        ),
        DomainEvent(
            sequence=4, run_id="r-1", event_type="TournamentEpochClosed",
            payload={"epoch_id": "e-1"},
        ),
        DomainEvent(
            sequence=5, run_id="r-1", event_type="TournamentEpochOpened",
            payload={"epoch_id": "e-2", "research_plan_version": 2},
        ),
        DomainEvent(
            sequence=6, run_id="r-1", event_type="TournamentEntryCreated",
            payload={"epoch_id": "e-2", "hypothesis_id": "h-1", "rating": 1200.0},
        ),
    ])
    assert projection.ratings["e-1"]["h-1"] == 1280.0
    assert projection.ratings["e-2"]["h-1"] == 1200.0
```

- [ ] **Step 6: Run event tests**

Run: `python3.11 -m pytest tests/unit/events -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/co_scientist/events src/co_scientist/ports/event_store.py tests/unit/events
git commit -m "feat: add event contracts and deterministic replay"
```

---

### Task 7: SQLite Unit of Work and Atomic Filesystem Artifacts

**Files:**
- Create: `src/co_scientist/ports/artifact_store.py`
- Create: `src/co_scientist/adapters/persistence/__init__.py`
- Create: `src/co_scientist/adapters/persistence/sqlite.py`
- Create: `src/co_scientist/adapters/artifacts/__init__.py`
- Create: `src/co_scientist/adapters/artifacts/filesystem.py`
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/versions/0001_core_tables.py`
- Create: `tests/contract/persistence/test_sqlite_event_store.py`
- Create: `tests/contract/persistence/test_sqlite_uow_atomic.py`
- Create: `tests/contract/persistence/test_filesystem_artifacts.py`

**Interfaces:**
- Consumes: `EventStore`, `DomainEvent`
- Produces: `SqliteUnitOfWork`, `FilesystemArtifactStore`, `ArtifactRef`, optimistic append

- [ ] **Step 1: Write failing optimistic-concurrency test**

```python
# tests/contract/persistence/test_sqlite_event_store.py
import pytest

from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork
from co_scientist.ports.event_store import ConcurrencyConflict


def test_append_rejects_stale_expected_sequence(tmp_path) -> None:
    store = SqliteUnitOfWork(f"sqlite:///{tmp_path / 'core.db'}")
    store.create_schema()
    store.append_new("r-1", expected_sequence=0, event_type="RunCreated", payload={})
    with pytest.raises(ConcurrencyConflict):
        store.append_new("r-1", expected_sequence=0, event_type="RunStarted", payload={})
```

- [ ] **Step 2: Write failing atomic artifact test**

```python
# tests/contract/persistence/test_filesystem_artifacts.py
from co_scientist.adapters.artifacts.filesystem import FilesystemArtifactStore


def test_raw_artifact_is_content_addressed_and_complete(tmp_path) -> None:
    store = FilesystemArtifactStore(tmp_path)
    ref = store.persist_raw("call-1", b'{"id":"response-1"}', "application/json")
    assert ref.sha256.startswith("sha256:")
    assert store.read(ref) == b'{"id":"response-1"}'
    assert not list(tmp_path.rglob("*.partial"))
```

- [ ] **Step 3: Run contract tests and confirm adapters are missing**

Run: `python3.11 -m pytest tests/contract/persistence -q`

Expected: FAIL on missing adapters.

- [ ] **Step 4: Implement filesystem write-to-temp, fsync, and atomic replace**

```python
# src/co_scientist/ports/artifact_store.py
from typing import Protocol

from pydantic import BaseModel, ConfigDict


class ArtifactRef(BaseModel):
    model_config = ConfigDict(frozen=True)
    path: str
    sha256: str
    mime_type: str
    byte_length: int


class ArtifactStore(Protocol):
    def persist_raw(self, call_id: str, data: bytes, mime_type: str) -> ArtifactRef: ...
    def read(self, ref: ArtifactRef) -> bytes: ...
```

```python
# src/co_scientist/adapters/artifacts/filesystem.py
import hashlib
import os
from pathlib import Path

from co_scientist.ports.artifact_store import ArtifactRef


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


class FilesystemArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def persist_raw(self, call_id: str, data: bytes, mime_type: str) -> ArtifactRef:
        digest = _sha256(data)
        destination = self.root / "raw" / call_id / digest.removeprefix("sha256:")
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_suffix(".partial")
        with partial.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(partial, destination)
        return ArtifactRef(path=str(destination), sha256=digest, mime_type=mime_type,
                           byte_length=len(data))
```

- [ ] **Step 5: Implement SQLite tables and append transaction**

Use this initial migration shape:

```python
# alembic/versions/0001_core_tables.py
def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("run_id", sa.String(), primary_key=True),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("current_sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("manifest_json", sa.Text(), nullable=False),
    )
    op.create_table(
        "events",
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("run_id", "sequence"),
    )
    op.create_table(
        "tasks",
        sa.Column("task_id", sa.String(), primary_key=True),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("intent_type", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("lease_owner", sa.String(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("run_id", "idempotency_key"),
    )
    op.create_table(
        "external_calls",
        sa.Column("external_call_id", sa.String(), primary_key=True),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("model_or_tool", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("raw_artifact_ref_json", sa.Text(), nullable=True),
        sa.Column("validated_artifact_ref_json", sa.Text(), nullable=True),
        sa.Column("agent_result_id", sa.String(), nullable=True),
        sa.Column("applied_domain_sequence", sa.Integer(), nullable=True),
        sa.Column("parent_call_id", sa.String(), nullable=True),
        sa.Column("provider_response_id", sa.String(), nullable=True),
        sa.Column("usage_json", sa.Text(), nullable=False, server_default="'{}'"),
    )
    op.create_table(
        "cost_entries",
        sa.Column("cost_entry_id", sa.String(), primary_key=True),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("external_call_id", sa.String(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.String(), nullable=False, server_default="'0'"),
        sa.Column("pricing_version", sa.String(), nullable=False),
    )
    op.create_table(
        "idempotency_commits",
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("last_sequence", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("run_id", "idempotency_key"),
    )
```

```python
def append_new(self, run_id: str, expected_sequence: int,
               event_type: str, payload: dict) -> DomainEvent:
    with self.session_factory.begin() as session:
        current = session.scalar(
            select(func.coalesce(func.max(EventRow.sequence), 0))
            .where(EventRow.run_id == run_id)
        )
        if current != expected_sequence:
            raise ConcurrencyConflict(f"expected {expected_sequence}, got {current}")
        event = EventRow(
            run_id=run_id,
            sequence=current + 1,
            event_type=event_type,
            schema_version=1,
            payload_json=json.dumps(payload, sort_keys=True),
        )
        session.add(event)
    return event.to_domain()
```

```python
# src/co_scientist/adapters/persistence/sqlite.py
from typing import Sequence

from pydantic import BaseModel, ConfigDict

from co_scientist.domain.budget import CostEntry
from co_scientist.domain.task import NewTask, TaskMutation
from co_scientist.events.models import DomainEvent
from co_scientist.events.models import NewEvent


class CommitResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    events: tuple[DomainEvent, ...]
    last_sequence: int


def commit_domain_batch(
    self,
    *,
    run_id: str,
    expected_sequence: int,
    events: Sequence[NewEvent],
    task_mutations: Sequence[TaskMutation],
    followup_tasks: Sequence[NewTask],
    idempotency_key: str,
    external_call_id: str | None = None,
    cost_entries: Sequence[CostEntry] = (),
) -> CommitResult:
    with self.session_factory.begin() as session:
        self._assert_sequence(session, run_id, expected_sequence)
        persisted = self._insert_events(session, run_id, expected_sequence, events)
        self._apply_task_mutations(session, task_mutations)
        self._insert_followup_tasks(session, followup_tasks)
        self._insert_cost_entries(session, cost_entries)
        self._insert_idempotency_commit(
            session, run_id, idempotency_key, persisted[-1].sequence
        )
        if external_call_id is not None:
            self._mark_external_call_domain_applied(
                session, external_call_id, persisted[-1].sequence
            )
        self._set_run_sequence(session, run_id, persisted[-1].sequence)
    return CommitResult(events=tuple(persisted), last_sequence=persisted[-1].sequence)
```

- [ ] **Step 6: Prove a duplicate follow-up rolls back the whole batch**

```python
# tests/contract/persistence/test_sqlite_uow_atomic.py
def test_failed_followup_insert_rolls_back_events_and_task_success(store) -> None:
    store.create_run("r-1", manifest={})
    store.enqueue_tasks([
        NewTask(task_id="task-1", run_id="r-1", idempotency_key="source",
                intent_type="reflect", payload={}),
        NewTask(task_id="existing", run_id="r-1", idempotency_key="followup",
                intent_type="rank", payload={}),
    ])
    store.transition_task("task-1", TaskState.RESULT_RECEIVED)
    with pytest.raises(IntegrityError):
        store.commit_domain_batch(
            run_id="r-1",
            expected_sequence=0,
            events=[NewEvent(event_type="ReviewCompleted", payload={"review_id": "rev-1"})],
            task_mutations=[TaskMutation.succeed("task-1")],
            followup_tasks=[
                NewTask(task_id="duplicate", run_id="r-1", idempotency_key="followup",
                        intent_type="rank", payload={})
            ],
            idempotency_key="source",
            external_call_id=None,
            cost_entries=(),
        )
    assert store.load("r-1") == []
    # The RESULT_RECEIVED transition committed before this failed batch and
    # therefore remains durable; only work attempted inside the batch rolls back.
    assert store.task_state("task-1") == "result_received"
```

- [ ] **Step 7: Run migrations and contract tests**

Run: `python3.11 -m alembic upgrade head && python3.11 -m pytest tests/contract/persistence -q`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/co_scientist/ports/artifact_store.py src/co_scientist/adapters alembic.ini alembic tests/contract/persistence
git commit -m "feat: persist events and raw artifacts atomically"
```

---

### Task 8: Raw-First ExternalCall Runner and Recovery

**Files:**
- Create: `src/co_scientist/ports/external_provider.py`
- Create: `src/co_scientist/agents/__init__.py`
- Create: `src/co_scientist/agents/result.py`
- Create: `src/co_scientist/runtime/__init__.py`
- Create: `src/co_scientist/runtime/external_calls.py`
- Create: `tests/scenario/test_external_call_raw_first.py`
- Create: `tests/scenario/test_external_call_recovery.py`

**Interfaces:**
- Consumes: `SqliteUnitOfWork`, `FilesystemArtifactStore`, ExternalCall transitions
- Produces: `ExternalCallRunner.execute(request, provider, validator) -> AgentResult`; `resume(call_id)`

- [ ] **Step 1: Write failing raw-before-validate test**

```python
# tests/scenario/test_external_call_raw_first.py
from types import SimpleNamespace

import pytest

from co_scientist.adapters.artifacts.filesystem import FilesystemArtifactStore
from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork
from co_scientist.agents.result import AgentExecutionContext
from co_scientist.ports.external_provider import RawExternalResponse
from co_scientist.runtime.external_calls import ExternalCallRunner


class StubProvider:
    async def invoke(self, request):
        return RawExternalResponse(
            body=b'{"hypotheses":[]}',
            mime_type="application/json",
            provider_response_id="stub-1",
        )


@pytest.mark.asyncio
async def test_validator_observes_persisted_raw_artifact(tmp_path) -> None:
    uow = SqliteUnitOfWork(f"sqlite:///{tmp_path / 'core.db'}")
    uow.create_schema()
    artifacts = FilesystemArtifactStore(tmp_path / "artifacts")
    runtime = SimpleNamespace(uow=uow, artifacts=artifacts)
    observed = []

    def validator(raw: bytes):
        observed.append(uow.external_call_state("call-1"))
        return {"hypotheses": []}

    context = AgentExecutionContext(
        task_id="task-1",
        idempotency_key="generation:r-1:1",
        skill_id="generation",
        skill_version="0.1.0",
        output_schema_version=1,
        input_snapshot_hash="sha256:input",
    )
    result = await ExternalCallRunner(runtime).execute(
        call_id="call-1",
        request={"prompt": "generate"},
        provider=StubProvider(),
        validator=validator,
        context=context,
    )
    assert observed == ["raw_response_persisted"]
    assert result.external_call_id == "call-1"
    assert uow.external_call_state("call-1") == "agent_result_submitted"
```

- [ ] **Step 2: Run scenario test and confirm missing runner**

Run: `python3.11 -m pytest tests/scenario/test_external_call_raw_first.py -q`

Expected: FAIL on missing runner.

- [ ] **Step 3: Define provider raw-response protocol**

```python
# src/co_scientist/ports/external_provider.py
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field


class RawExternalResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    body: bytes
    mime_type: str
    provider_response_id: str | None = None
    usage: dict[str, int] = Field(default_factory=dict)


class ExternalProvider(Protocol):
    async def invoke(self, request: dict[str, Any]) -> RawExternalResponse: ...
```

- [ ] **Step 4: Define the execution context and AgentResult envelope**

```python
# src/co_scientist/agents/result.py
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class AgentExecutionContext(BaseModel):
    model_config = ConfigDict(frozen=True)
    task_id: str
    idempotency_key: str
    skill_id: str
    skill_version: str
    output_schema_version: int
    input_snapshot_hash: str


class AgentResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    result_id: str
    external_call_id: str
    task_id: str
    idempotency_key: str
    skill_id: str
    skill_version: str
    output_schema_version: int
    input_snapshot_hash: str
    status: Literal["completed", "partial", "rejected", "failed"]
    payload: dict[str, Any]
    evidence_refs: tuple[str, ...] = ()
    recommended_actions: tuple[str, ...] = ()
    raw_artifact_ref: str
```

- [ ] **Step 5: Implement exact lifecycle ordering**

```python
# src/co_scientist/runtime/external_calls.py
import hashlib
import json
from typing import Any
from uuid import uuid4

from co_scientist.agents.result import AgentResult


def request_fingerprint(request: dict[str, Any]) -> str:
    canonical = json.dumps(request, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ExternalCallRunner:
    def __init__(self, runtime) -> None:
        self.uow = runtime.uow
        self.artifacts = runtime.artifacts

    def _validate_and_submit(self, call_id, ref, validator, context) -> AgentResult:
        try:
            payload = validator(self.artifacts.read(ref))
        except Exception:
            self.uow.transition_call(call_id, "validation_failed")
            raise
        self.uow.record_validated(call_id, payload)
        result = AgentResult(
            result_id=str(uuid4()),
            external_call_id=call_id,
            raw_artifact_ref=ref.path,
            status="completed",
            payload=payload,
            **context.model_dump(),
        )
        self.uow.record_submitted_result(call_id, result)
        return result

    async def execute(self, *, call_id, request, provider, validator, context) -> AgentResult:
        self.uow.plan_external_call(call_id, request_fingerprint(request))
        self.uow.transition_call(call_id, "started")
        try:
            raw = await provider.invoke(request)
        except Exception:
            self.uow.transition_call(call_id, "failed_before_response")
            raise
        try:
            ref = self.artifacts.persist_raw(call_id, raw.body, raw.mime_type)
        except Exception:
            self.uow.transition_call(call_id, "raw_persist_failed")
            raise
        self.uow.record_raw_and_transition(call_id, ref, "raw_response_persisted")
        return self._validate_and_submit(call_id, ref, validator, context)

    async def resume(self, call_id, *, provider, validator, context) -> AgentResult:
        call = self.uow.get_external_call(call_id)
        if call.state != "raw_response_persisted" or call.raw_artifact_ref is None:
            raise ValueError(f"call {call_id} has no resumable raw response")
        return self._validate_and_submit(
            call_id, call.raw_artifact_ref, validator, context
        )
```

`execute` must not mark `domain_result_applied`; only Supervisor does that after applying domain events.

- [ ] **Step 6: Add recovery test from persisted raw**

```python
# tests/scenario/test_external_call_recovery.py
import json
from types import SimpleNamespace

import pytest

from co_scientist.adapters.artifacts.filesystem import FilesystemArtifactStore
from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork
from co_scientist.agents.result import AgentExecutionContext
from co_scientist.runtime.external_calls import ExternalCallRunner


class FailingProvider:
    call_count = 0

    async def invoke(self, request):
        self.call_count += 1
        raise AssertionError("provider must not be called")


@pytest.mark.asyncio
async def test_resume_validates_existing_raw_without_provider_recall(tmp_path) -> None:
    uow = SqliteUnitOfWork(f"sqlite:///{tmp_path / 'core.db'}")
    uow.create_schema()
    artifacts = FilesystemArtifactStore(tmp_path / "artifacts")
    runtime = SimpleNamespace(uow=uow, artifacts=artifacts)
    uow.plan_external_call("call-1", "sha256:request")
    uow.transition_call("call-1", "started")
    ref = artifacts.persist_raw("call-1", b'{"hypotheses":[]}', "application/json")
    uow.record_raw_and_transition("call-1", ref, "raw_response_persisted")
    provider = FailingProvider()
    context = AgentExecutionContext(
        task_id="task-1",
        idempotency_key="generation:r-1:1",
        skill_id="generation",
        skill_version="0.1.0",
        output_schema_version=1,
        input_snapshot_hash="sha256:input",
    )
    result = await ExternalCallRunner(runtime).resume(
        "call-1",
        provider=provider,
        validator=lambda raw: json.loads(raw),
        context=context,
    )
    assert result.payload == {"hypotheses": []}
    assert provider.call_count == 0
```

- [ ] **Step 7: Run both scenario tests**

Run: `python3.11 -m pytest tests/scenario/test_external_call_raw_first.py tests/scenario/test_external_call_recovery.py -q`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/co_scientist/ports/external_provider.py src/co_scientist/agents src/co_scientist/runtime tests/scenario/test_external_call_raw_first.py tests/scenario/test_external_call_recovery.py
git commit -m "feat: enforce raw-first external call recovery"
```

---

### Task 9: Supervisor Authority, Admission, Epoch Changes, and Finalization

**Files:**
- Create: `src/co_scientist/supervisor/__init__.py`
- Create: `src/co_scientist/supervisor/followups.py`
- Create: `src/co_scientist/supervisor/orchestrator.py`
- Create: `src/co_scientist/domain/research_plan.py`
- Create: `tests/unit/supervisor/test_followups.py`
- Create: `tests/unit/supervisor/test_admission.py`
- Create: `tests/scenario/test_epoch_rollover.py`
- Create: `tests/scenario/test_finalization_path.py`

**Interfaces:**
- Consumes: events, state machines, review policy, tournament, budget, convergence, submitted AgentResult
- Produces: `Supervisor.handle_result`, `Supervisor.tick`, `derive_followup_intents`, `AdmissionDecision`

- [ ] **Step 1: Write failing single-authority follow-up test**

```python
# tests/unit/supervisor/test_followups.py
from co_scientist.supervisor.followups import derive_followup_intents
from co_scientist.domain.review import ReviewPolicy, ReviewStage


def test_generation_result_yields_supervisor_owned_initial_review_intent() -> None:
    intents = derive_followup_intents(
        event_type="HypothesisContentCreated",
        payload={"hypothesis_id": "h-1"},
        review_policy=ReviewPolicy(
            profile_id="minimal",
            required_before_admission=(ReviewStage.INITIAL,),
        ),
    )
    assert [intent.intent_type for intent in intents] == ["run_initial_review"]
    assert all(intent.created_by == "supervisor" for intent in intents)
```

- [ ] **Step 2: Write failing policy-driven admission test**

```python
# tests/unit/supervisor/test_admission.py
def test_minimal_policy_admits_without_deep_review() -> None:
    decision = evaluate_admission(
        safety_passed=True,
        required_stages={"initial_review"},
        completed_stages={"initial_review"},
        novelty_required=False,
        novelty_assessment=None,
        proximity_complete=True,
        duplicate=False,
    )
    assert decision.admitted
```

- [ ] **Step 3: Run tests and confirm Supervisor is missing**

Run: `python3.11 -m pytest tests/unit/supervisor -q`

Expected: FAIL on missing modules.

- [ ] **Step 4: Implement ResearchPlan and typed follow-up intents**

```python
# src/co_scientist/domain/research_plan.py
from typing import Literal

from pydantic import BaseModel, ConfigDict

from co_scientist.domain.review import ReviewPolicy


class ResearchPlan(BaseModel):
    model_config = ConfigDict(frozen=True)
    run_id: str
    version: int
    scientific_scope_hash: str
    evaluation_rules_hash: str
    ranking_prompt_hash: str
    judge_profile_hash: str
    rating_policy_version: str
    admission_policy_version: str
    review_policy: ReviewPolicy
    literature_novelty_required: bool
```

```python
# src/co_scientist/supervisor/followups.py
from typing import Literal

from pydantic import BaseModel, ConfigDict

from co_scientist.domain.review import ReviewPolicy


class FollowupIntent(BaseModel):
    model_config = ConfigDict(frozen=True)
    intent_type: str
    target_id: str
    created_by: Literal["supervisor"] = "supervisor"


def derive_followup_intents(
    *, event_type: str, payload: dict, review_policy: ReviewPolicy,
) -> tuple[FollowupIntent, ...]:
    if event_type == "HypothesisContentCreated":
        return (
            FollowupIntent(
                intent_type="run_initial_review",
                target_id=payload["hypothesis_id"],
            ),
        )
    return ()
```

`derive_followup_intents` is pure over committed event plus current projection. AgentResult `recommended_actions` may inform priority but never bypass this function.

- [ ] **Step 5: Implement result application and admission**

```python
# src/co_scientist/supervisor/orchestrator.py
from pydantic import BaseModel, ConfigDict

from co_scientist.agents.result import AgentResult
from co_scientist.domain.review import NoveltyAssessment


class AdmissionDecision(BaseModel):
    model_config = ConfigDict(frozen=True)
    admitted: bool
    missing_requirements: tuple[str, ...] = ()


def evaluate_admission(
    *,
    safety_passed: bool,
    required_stages: set[str],
    completed_stages: set[str],
    novelty_required: bool,
    novelty_assessment: NoveltyAssessment | None,
    proximity_complete: bool,
    duplicate: bool,
) -> AdmissionDecision:
    missing = []
    if not safety_passed:
        missing.append("safety")
    missing.extend(sorted(required_stages - completed_stages))
    if novelty_required and novelty_assessment is None:
        missing.append("novelty_assessment")
    if not proximity_complete:
        missing.append("proximity")
    if duplicate:
        missing.append("candidate_duplicate")
    return AdmissionDecision(admitted=not missing, missing_requirements=tuple(missing))
```

```python
class Supervisor:
    def handle_result(self, run_id: str, task_id: str,
                      result: AgentResult, expected_sequence: int) -> CommitResult:
        validated = self.result_registry.validate(task_id, result)
        events = self.domain_policy.events_for(validated)
        followups = derive_followup_intents_from_events(events, self.read_model)
        commit = self.uow.commit_domain_batch(
            run_id=run_id,
            expected_sequence=expected_sequence,
            events=events,
            followup_tasks=followups,
            idempotency_key=result.idempotency_key,
            external_call_id=result.external_call_id,
        )
        return commit
```

The batch must atomically write domain events, projection changes, task success, cost settlement, and follow-up tasks.

- [ ] **Step 6: Implement epoch rollover rules**

```python
def plan_revision_action(old: ResearchPlan, new: ResearchPlan) -> Literal["new_epoch", "fork_run"]:
    if new.version <= old.version:
        raise ValueError("ResearchPlan version must increase")
    scientific_scope_changed = old.scientific_scope_hash != new.scientific_scope_hash
    return "fork_run" if scientific_scope_changed else "new_epoch"
```

Any accepted ResearchPlan version increment closes the open epoch. New epoch entries start at 1200; old ratings remain historical.

- [ ] **Step 7: Implement mandatory stopping/finalization**

```python
def request_normal_completion(self, run_id: str) -> None:
    self.uow.append_run_event(run_id, "RunStopping", {"reason": "work_complete"})
    self.enqueue_finalization(run_id)

def apply_finalization(self, run_id: str, completeness: str) -> None:
    terminal = "RunCompleted" if completeness == "complete" else "RunCompletedPartial"
    self.uow.append_run_event(run_id, terminal, {"completeness": completeness})
```

- [ ] **Step 8: Run Supervisor and scenario tests**

Run: `python3.11 -m pytest tests/unit/supervisor tests/scenario/test_epoch_rollover.py tests/scenario/test_finalization_path.py -q`

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/co_scientist/supervisor src/co_scientist/domain/research_plan.py tests/unit/supervisor tests/scenario/test_epoch_rollover.py tests/scenario/test_finalization_path.py
git commit -m "feat: make Supervisor the sole orchestration authority"
```

---

### Task 10: Six Core Skills, Fake Provider, and Replay Provider

**Files:**
- Create: `src/co_scientist/skills/__init__.py`
- Create: `src/co_scientist/skills/loader.py`
- Modify: `src/co_scientist/agents/result.py`
- Create: `src/co_scientist/agents/executor.py`
- Create: `src/co_scientist/adapters/llm/fake.py`
- Create: `src/co_scientist/adapters/llm/replay.py`
- Create: `skills/generation/manifest.yaml`
- Create: `skills/generation/prompts/system.md`
- Create: `skills/reflection/manifest.yaml`
- Create: `skills/reflection/prompts/system.md`
- Create: `skills/ranking/manifest.yaml`
- Create: `skills/ranking/prompts/system.md`
- Create: `skills/proximity/manifest.yaml`
- Create: `skills/proximity/prompts/system.md`
- Create: `skills/evolution/manifest.yaml`
- Create: `skills/evolution/prompts/system.md`
- Create: `skills/meta_review/manifest.yaml`
- Create: `skills/meta_review/prompts/system.md`
- Create: `tests/contract/skills/test_skill_manifests.py`
- Create: `tests/scenario/test_fake_core_loop.py`
- Create: `tests/scenario/fixtures/core_loop_trace.json`

**Interfaces:**
- Consumes: `ExternalCallRunner`, domain AgentResult payloads
- Produces: `SkillManifest`, `load_skill`, `SkillExecutor`, `FakeLLMProvider`, `ReplayLLMProvider`

- [ ] **Step 1: Write failing manifest contract test**

```python
# tests/contract/skills/test_skill_manifests.py
from pathlib import Path

from co_scientist.skills.loader import load_skill


def test_all_six_core_skills_are_versioned_and_forbid_task_creation() -> None:
    names = ("generation", "reflection", "ranking", "proximity", "evolution", "meta_review")
    manifests = [load_skill(Path("skills") / name) for name in names]
    assert {manifest.agent_type for manifest in manifests} == set(names)
    assert all(manifest.version == "0.1.0" for manifest in manifests)
    assert all("create_task" not in manifest.allowed_capabilities for manifest in manifests)
```

- [ ] **Step 2: Run the test and confirm loader is missing**

Run: `python3.11 -m pytest tests/contract/skills/test_skill_manifests.py -q`

Expected: FAIL on missing loader.

- [ ] **Step 3: Implement the manifest contract using the existing AgentResult envelope**

```python
# src/co_scientist/skills/loader.py
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict


class SkillManifest(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    agent_type: Literal[
        "generation", "reflection", "ranking",
        "proximity", "evolution", "meta_review",
    ]
    version: str
    prompt_path: str
    input_schema: str
    output_schema: str
    allowed_tools: tuple[str, ...] = ()
    allowed_capabilities: tuple[Literal["return_agent_result"], ...]
```

```python
def load_skill(directory: Path) -> SkillManifest:
    manifest = SkillManifest.model_validate(
        yaml.safe_load((directory / "manifest.yaml").read_text(encoding="utf-8"))
    )
    prompt = directory / manifest.prompt_path
    if not prompt.is_file():
        raise FileNotFoundError(prompt)
    if manifest.allowed_capabilities != ("return_agent_result",):
        raise ValueError("skills may only return AgentResult")
    return manifest
```

- [ ] **Step 4: Create exact Core Preview manifest matrix**

```yaml
# skills/generation/manifest.yaml
id: generation
agent_type: generation
version: 0.1.0
prompt_path: prompts/system.md
input_schema: GenerationInputV1
output_schema: GenerationResultV1
allowed_tools: []
allowed_capabilities: [return_agent_result]
---
# skills/reflection/manifest.yaml
id: reflection
agent_type: reflection
version: 0.1.0
prompt_path: prompts/system.md
input_schema: ReflectionInputV1
output_schema: ReflectionResultV1
allowed_tools: [literature_search]
allowed_capabilities: [return_agent_result]
---
# skills/ranking/manifest.yaml
id: ranking
agent_type: ranking
version: 0.1.0
prompt_path: prompts/system.md
input_schema: RankingInputV1
output_schema: RankingResultV1
allowed_tools: []
allowed_capabilities: [return_agent_result]
---
# skills/proximity/manifest.yaml
id: proximity
agent_type: proximity
version: 0.1.0
prompt_path: prompts/system.md
input_schema: ProximityInputV1
output_schema: ProximityResultV1
allowed_tools: []
allowed_capabilities: [return_agent_result]
---
# skills/evolution/manifest.yaml
id: evolution
agent_type: evolution
version: 0.1.0
prompt_path: prompts/system.md
input_schema: EvolutionInputV1
output_schema: EvolutionResultV1
allowed_tools: []
allowed_capabilities: [return_agent_result]
---
# skills/meta_review/manifest.yaml
id: meta_review
agent_type: meta_review
version: 0.1.0
prompt_path: prompts/system.md
input_schema: MetaReviewInputV1
output_schema: MetaReviewResultV1
allowed_tools: []
allowed_capabilities: [return_agent_result]
```

- [ ] **Step 5: Create concrete system prompt contracts**

```text
# generation
Return JSON hypotheses containing title, claim, mechanism_chain, assumptions,
predictions, falsifiers, and generation_strategy. Do not create tasks.

# reflection
Execute only the requested review_stage. Return scores, critical_flaws,
evidence_refs, recommendation, and a NoveltyAssessment only for a literature
novelty/full review. Do not infer literature novelty from Proximity.

# ranking
Return decision_status from decisive, inconclusive, invalid, needs_tiebreaker.
Return winner_slot only for decisive. Never calculate or return Elo.

# proximity
Compare candidate content only. Return 1-5 similarity, mechanism overlap,
duplicate likelihood, and cluster suggestion. Do not assess literature novelty.

# evolution
Return new child content with parent_content_ids and an explicit change rationale.
Do not copy parent rating, review coverage, or lifecycle state.

# meta_review
Return cross-candidate feedback and coverage gaps. Do not rescore one hypothesis,
create tasks, or update model parameters.
```

- [ ] **Step 6: Implement fake and replay raw-response providers**

```python
from collections import deque
from typing import Any

from co_scientist.ports.external_provider import RawExternalResponse
from co_scientist.runtime.external_calls import request_fingerprint


class FakeLLMProvider:
    def __init__(self, responses: list[bytes]) -> None:
        self.responses = deque(responses)
        self.call_count = 0

    async def invoke(self, request: dict[str, Any]) -> RawExternalResponse:
        self.call_count += 1
        return RawExternalResponse(
            body=self.responses.popleft(),
            mime_type="application/json",
            provider_response_id=f"fake-{self.call_count}",
        )


class ReplayMiss(KeyError):
    pass


class ReplayLLMProvider:
    def __init__(self, responses_by_fingerprint: dict[str, bytes]) -> None:
        self.responses = responses_by_fingerprint

    async def invoke(self, request: dict[str, Any]) -> RawExternalResponse:
        fingerprint = request_fingerprint(request)
        if fingerprint not in self.responses:
            raise ReplayMiss(fingerprint)
        return RawExternalResponse(
            body=self.responses[fingerprint],
            mime_type="application/json",
            provider_response_id=f"replay-{fingerprint[:12]}",
        )
```

- [ ] **Step 7: Add deterministic full-loop scenario**

```json
{
  "trace_version": 1,
  "responses": [
    {"skill": "generation", "payload": {"hypotheses": [
      {"content_id": "c-1", "title": "Mechanical gate", "claim": "Capsule strain precedes EMT commitment"},
      {"content_id": "c-2", "title": "Inflammatory gate", "claim": "Early cytokine duration precedes fibrosis"}
    ]}},
    {"skill": "reflection", "stage": "initial_review", "hypothesis_id": "h-1",
     "payload": {"recommendation": "pass", "critical_flaws": []}},
    {"skill": "reflection", "stage": "initial_review", "hypothesis_id": "h-2",
     "payload": {"recommendation": "pass", "critical_flaws": []}},
    {"skill": "reflection", "stage": "full_review", "hypothesis_id": "h-1",
     "payload": {"recommendation": "pass", "novelty_assessment_id": "n-1"}},
    {"skill": "reflection", "stage": "full_review", "hypothesis_id": "h-2",
     "payload": {"recommendation": "pass", "novelty_assessment_id": "n-2"}},
    {"skill": "proximity", "payload": {"left_id": "h-1", "right_id": "h-2",
     "similarity": 2, "duplicate_likelihood": 0.05}},
    {"skill": "ranking", "payload": {"decision_status": "decisive", "winner_slot": 1}},
    {"skill": "evolution", "payload": {"child_content_id": "c-3",
     "parent_content_ids": ["c-1"], "change_rationale": "adds an early perturbation readout"}},
    {"skill": "reflection", "stage": "initial_review", "hypothesis_id": "h-3",
     "payload": {"recommendation": "pass", "critical_flaws": []}},
    {"skill": "reflection", "stage": "full_review", "hypothesis_id": "h-3",
     "payload": {"recommendation": "pass", "novelty_assessment_id": "n-3"}},
    {"skill": "proximity", "payload": {"left_id": "h-3", "right_id": "h-1",
     "similarity": 4, "duplicate_likelihood": 0.20}},
    {"skill": "meta_review", "payload": {"feedback": ["separate age from surgical geometry"]}}
  ]
}
```

```python
def test_fake_trace_reaches_finalization_without_agent_created_tasks(core_harness) -> None:
    result = core_harness.run_trace("tests/scenario/fixtures/core_loop_trace.json")
    assert result.final_state == "completed"
    assert result.state_history[-2:] == ["stopping", "completed"]
    assert all(task.created_by == "supervisor" for task in result.tasks)
    assert result.child.initial_rating == 1200.0
```

- [ ] **Step 8: Run manifest and fake-loop tests**

Run: `python3.11 -m pytest tests/contract/skills/test_skill_manifests.py tests/scenario/test_fake_core_loop.py -q`

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/co_scientist/skills src/co_scientist/agents src/co_scientist/adapters/llm skills tests/contract/skills tests/scenario
git commit -m "feat: add six typed skills and deterministic providers"
```

---

### Task 11: One Real LLM Provider — OpenAI Responses Adapter

**Files:**
- Create: `src/co_scientist/adapters/llm/openai_responses.py`
- Create: `tests/contract/llm/test_openai_responses_adapter.py`
- Create: `tests/contract/llm/test_openai_raw_persistence.py`
- Create: `tests/contract/llm/test_openai_online.py`

**Interfaces:**
- Consumes: `ExternalProvider`, `RawExternalResponse`, `ExternalCallRunner`
- Produces: `OpenAIResponsesProvider.invoke(request) -> RawExternalResponse`

- [ ] **Step 1: Write the failing mocked adapter test**

```python
# tests/contract/llm/test_openai_responses_adapter.py
import pytest
from pydantic import BaseModel

from co_scientist.adapters.llm.openai_responses import OpenAIResponsesProvider


class FakeUsage(BaseModel):
    input_tokens: int = 10
    output_tokens: int = 5


class FakeResponse(BaseModel):
    id: str = "resp-1"
    usage: FakeUsage = FakeUsage()


class FakeResponses:
    async def create(self, **kwargs):
        return FakeResponse()


class FakeClient:
    responses = FakeResponses()


@pytest.mark.asyncio
async def test_adapter_returns_unparsed_raw_json() -> None:
    provider = OpenAIResponsesProvider(FakeClient())
    raw = await provider.invoke({
        "model": "configured-model",
        "system_prompt": "Return JSON.",
        "user_prompt": "Generate one hypothesis.",
        "json_schema": {"type": "object"},
    })
    assert raw.mime_type == "application/json"
    assert b'"id":"resp-1"' in raw.body
    assert raw.provider_response_id == "resp-1"
```

- [ ] **Step 2: Run the test and confirm adapter is missing**

Run: `python3.11 -m pytest tests/contract/llm/test_openai_responses_adapter.py -q`

Expected: FAIL on missing adapter.

- [ ] **Step 3: Implement the adapter without validation side effects**

```python
# src/co_scientist/adapters/llm/openai_responses.py
from typing import Any

from openai import AsyncOpenAI

from co_scientist.ports.external_provider import RawExternalResponse


class OpenAIResponsesProvider:
    def __init__(self, client: AsyncOpenAI) -> None:
        self.client = client

    async def invoke(self, request: dict[str, Any]) -> RawExternalResponse:
        response = await self.client.responses.create(
            model=request["model"],
            instructions=request["system_prompt"],
            input=request["user_prompt"],
            text={
                "format": {
                    "type": "json_schema",
                    "name": request.get("schema_name", "agent_result"),
                    "schema": request["json_schema"],
                    "strict": True,
                }
            },
        )
        return RawExternalResponse(
            body=response.model_dump_json().encode("utf-8"),
            mime_type="application/json",
            provider_response_id=response.id,
            usage={
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
        )
```

No model name is hardcoded. `CO_SCIENTIST_OPENAI_MODEL` supplies the model for online use.

- [ ] **Step 4: Prove raw persistence occurs before output parsing**

```python
# tests/contract/llm/test_openai_raw_persistence.py
@pytest.mark.asyncio
async def test_malformed_structured_output_is_still_durably_saved(runtime) -> None:
    runtime.openai_client.returns_raw('{"id":"resp-1","output_text":"not-json"}')
    with pytest.raises(OutputValidationError):
        await runtime.run_generation()
    call = runtime.calls.latest()
    assert call.state == "validation_failed"
    assert runtime.artifacts.read(call.raw_artifact_ref).startswith(b'{"id":"resp-1"')
```

- [ ] **Step 5: Add opt-in online contract test**

```python
# tests/contract/llm/test_openai_online.py
import os

import pytest
from openai import AsyncOpenAI

from co_scientist.adapters.llm.openai_responses import OpenAIResponsesProvider


def live_provider() -> OpenAIResponsesProvider:
    if not os.getenv("OPENAI_API_KEY") or not os.getenv("CO_SCIENTIST_OPENAI_MODEL"):
        pytest.skip("online OpenAI credentials are not configured")
    return OpenAIResponsesProvider(AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"]))


@pytest.mark.online
@pytest.mark.asyncio
async def test_live_provider_returns_schema_valid_payload() -> None:
    raw = await live_provider().invoke({
        "model": os.environ["CO_SCIENTIST_OPENAI_MODEL"],
        "system_prompt": "Return JSON matching the schema.",
        "user_prompt": "Return one object with status equal to ok.",
        "json_schema": {
            "type": "object",
            "properties": {"status": {"type": "string", "enum": ["ok"]}},
            "required": ["status"],
            "additionalProperties": False,
        },
    })
    assert raw.provider_response_id
    assert raw.usage["output_tokens"] > 0
```

The fixture skips unless both `OPENAI_API_KEY` and `CO_SCIENTIST_OPENAI_MODEL` are set.

- [ ] **Step 6: Run mocked contracts**

Run: `python3.11 -m pytest tests/contract/llm -q -m 'not online'`

Expected: PASS.

- [ ] **Step 7: Run the opt-in online contract when credentials are available**

Run: `test -n "$OPENAI_API_KEY" && test -n "$CO_SCIENTIST_OPENAI_MODEL" && python3.11 -m pytest tests/contract/llm/test_openai_online.py -q -m online`

Expected: PASS with one provider response ID and non-zero usage.

- [ ] **Step 8: Commit**

```bash
git add src/co_scientist/adapters/llm/openai_responses.py tests/contract/llm
git commit -m "feat: add raw-first OpenAI Responses adapter"
```

---

### Task 12: One Literature Provider — PubMed Search and Novelty Evidence

**Files:**
- Create: `src/co_scientist/ports/literature.py`
- Create: `src/co_scientist/adapters/literature/__init__.py`
- Create: `src/co_scientist/adapters/literature/pubmed.py`
- Create: `src/co_scientist/adapters/literature/replay.py`
- Create: `tests/contract/literature/test_pubmed_adapter.py`
- Create: `tests/contract/literature/test_pubmed_access_issue.py`
- Create: `tests/contract/literature/test_pubmed_online.py`
- Create: `tests/scenario/fixtures/pubmed_search_lens.json`
- Create: `tests/scenario/fixtures/pubmed_summary_lens.json`

**Interfaces:**
- Consumes: `ExternalCallRunner`, provenance models
- Produces: `PubMedProvider.search(query, limit) -> RawExternalResponse`; `PubMedProvider.fetch_summaries(pmids) -> RawExternalResponse`; `parse_pubmed_records(raw) -> tuple[SourceDocument, ...]`; `ReplayLiteratureProvider`

- [ ] **Step 1: Write failing mocked PubMed test**

```python
# tests/contract/literature/test_pubmed_adapter.py
import httpx
import pytest

from co_scientist.adapters.literature.pubmed import PubMedProvider


@pytest.mark.asyncio
async def test_pubmed_search_returns_raw_before_record_parsing(respx_mock) -> None:
    respx_mock.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi").respond(
        200, json={"esearchresult": {"idlist": ["123"]}}
    )
    async with httpx.AsyncClient() as client:
        provider = PubMedProvider(client, tool="co-scientist-core", email=None)
        raw = await provider.search("lens epithelial fibrosis", limit=5)
        assert raw.mime_type.startswith("application/json")
        assert b'"123"' in raw.body
```

- [ ] **Step 2: Run the test and confirm adapter is missing**

Run: `python3.11 -m pytest tests/contract/literature/test_pubmed_adapter.py -q`

Expected: FAIL on missing adapter.

- [ ] **Step 3: Implement bounded NCBI E-utilities requests**

```python
# src/co_scientist/ports/literature.py
from typing import Protocol

from co_scientist.ports.external_provider import RawExternalResponse


class LiteratureProvider(Protocol):
    async def search(self, query: str, limit: int = 10) -> RawExternalResponse: ...
    async def fetch_summaries(self, pmids: tuple[str, ...]) -> RawExternalResponse: ...
```

```python
# src/co_scientist/adapters/literature/pubmed.py
import json

import httpx

from co_scientist.domain.provenance import SourceDocument
from co_scientist.ports.external_provider import RawExternalResponse


class LiteratureAccessIssue(RuntimeError):
    def __init__(self, status_code: int, retryable: bool) -> None:
        super().__init__(f"PubMed HTTP {status_code}")
        self.status_code = status_code
        self.retryable = retryable


class PubMedProvider:
    SEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    SUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"

    def __init__(self, client: httpx.AsyncClient, *, tool: str, email: str | None) -> None:
        self.client = client
        self.tool = tool
        self.email = email

    async def search(self, query: str, limit: int = 10) -> RawExternalResponse:
        response = await self.client.get(
            self.SEARCH_URL,
            params={
                "db": "pubmed",
                "term": query,
                "retmode": "json",
                "retmax": min(limit, 50),
                "tool": self.tool,
                **({"email": self.email} if self.email else {}),
            },
            timeout=20.0,
        )
        if response.status_code >= 400:
            raise LiteratureAccessIssue(
                response.status_code,
                retryable=response.status_code == 429 or response.status_code >= 500,
            )
        return RawExternalResponse(
            body=response.content,
            mime_type=response.headers.get("content-type", "application/json"),
            provider_response_id=response.headers.get("ncbi-phid"),
        )

    async def fetch_summaries(self, pmids: tuple[str, ...]) -> RawExternalResponse:
        response = await self.client.get(
            self.SUMMARY_URL,
            params={
                "db": "pubmed",
                "id": ",".join(pmids[:50]),
                "retmode": "json",
                "tool": self.tool,
                **({"email": self.email} if self.email else {}),
            },
            timeout=20.0,
        )
        if response.status_code >= 400:
            raise LiteratureAccessIssue(
                response.status_code,
                retryable=response.status_code == 429 or response.status_code >= 500,
            )
        return RawExternalResponse(
            body=response.content,
            mime_type=response.headers.get("content-type", "application/json"),
            provider_response_id=response.headers.get("ncbi-phid"),
        )
```

- [ ] **Step 4: Parse records into provenance without deriving Proximity**

```python
def parse_pubmed_records(
    raw: bytes, *, query: str, raw_artifact_ref: str,
) -> tuple[SourceDocument, ...]:
    payload = json.loads(raw)
    records = []
    for pmid in payload["result"]["uids"]:
        item = payload["result"][pmid]
        records.append(SourceDocument(
            source_id=f"pubmed:{pmid}",
            provider="pubmed",
            canonical_id=f"PMID:{pmid}",
            title=item["title"],
            authors=tuple(author["name"] for author in item.get("authors", [])),
            publication_date=item.get("pubdate"),
            retrieval_query=query,
            raw_artifact_ref=raw_artifact_ref,
        ))
    return tuple(records)
```

Reflection creates NoveltyAssessment from these records; no ProximityEdge is created in this adapter.

```python
def test_pubmed_parser_never_returns_proximity_edge() -> None:
    raw = b'{"result":{"uids":["123"],"123":{"title":"Lens study","authors":[]}}}'
    records = parse_pubmed_records(
        raw, query="lens regeneration", raw_artifact_ref="artifact:summary"
    )
    assert records
    assert all(record.__class__.__name__ == "SourceDocument" for record in records)
```

- [ ] **Step 5: Add access-issue and online tests**

```python
# tests/contract/literature/test_pubmed_access_issue.py
import httpx
import pytest

from co_scientist.adapters.literature.pubmed import (
    LiteratureAccessIssue,
    PubMedProvider,
)


@pytest.mark.asyncio
async def test_429_is_classified_as_transient_access_issue(respx_mock) -> None:
    respx_mock.get(PubMedProvider.SEARCH_URL).respond(429)
    async with httpx.AsyncClient() as client:
        provider = PubMedProvider(client, tool="co-scientist-core", email=None)
        with pytest.raises(LiteratureAccessIssue) as error:
            await provider.search("lens regeneration")
        assert error.value.retryable
```

```python
# tests/contract/literature/test_pubmed_online.py
import json

import httpx
import pytest

from co_scientist.adapters.literature.pubmed import PubMedProvider


@pytest.mark.online
@pytest.mark.asyncio
async def test_live_pubmed_returns_at_least_one_pmid() -> None:
    async with httpx.AsyncClient() as client:
        provider = PubMedProvider(client, tool="co-scientist-core", email=None)
        raw = await provider.search("lens epithelial cell regeneration fibrosis", limit=5)
    assert json.loads(raw.body)["esearchresult"]["idlist"]
```

- [ ] **Step 6: Add replay literature provider for offline smoke**

```python
# src/co_scientist/adapters/literature/replay.py
from pathlib import Path

from co_scientist.ports.external_provider import RawExternalResponse


class ReplayLiteratureProvider:
    def __init__(self, search_path: Path, summary_path: Path) -> None:
        self.search_payload = search_path.read_bytes()
        self.summary_payload = summary_path.read_bytes()

    async def search(self, query: str, limit: int = 10) -> RawExternalResponse:
        return RawExternalResponse(
            body=self.search_payload,
            mime_type="application/json",
            provider_response_id="replay-pubmed-search-lens",
        )

    async def fetch_summaries(self, pmids: tuple[str, ...]) -> RawExternalResponse:
        return RawExternalResponse(
            body=self.summary_payload,
            mime_type="application/json",
            provider_response_id="replay-pubmed-summary-lens",
        )
```

`tests/scenario/fixtures/pubmed_search_lens.json`:

```json
{
  "esearchresult": {
    "idlist": ["1001", "1002"]
  }
}
```

`tests/scenario/fixtures/pubmed_summary_lens.json`:

```json
{
  "result": {
    "uids": ["1001", "1002"],
    "1001": {
      "uid": "1001",
      "title": "Lens epithelial cell state after minimally invasive surgery",
      "authors": [{"name": "Replay A"}],
      "pubdate": "2020"
    },
    "1002": {
      "uid": "1002",
      "title": "Fibrotic versus transparent lens regeneration",
      "authors": [{"name": "Replay B"}],
      "pubdate": "2021"
    }
  }
}
```

- [ ] **Step 7: Run offline contracts**

Run: `python3.11 -m pytest tests/contract/literature -q -m 'not online'`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/co_scientist/ports/literature.py src/co_scientist/adapters/literature tests/contract/literature tests/scenario/fixtures/pubmed_search_lens.json tests/scenario/fixtures/pubmed_summary_lens.json
git commit -m "feat: add PubMed evidence provider"
```

---

### Task 13: Application Service and CLI

**Files:**
- Create: `src/co_scientist/application/__init__.py`
- Create: `src/co_scientist/application/commands.py`
- Create: `src/co_scientist/application/queries.py`
- Create: `src/co_scientist/application/service.py`
- Create: `src/co_scientist/cli/__init__.py`
- Create: `src/co_scientist/cli/app.py`
- Create: `tests/unit/application/test_service_boundary.py`
- Create: `tests/contract/cli/test_cli_run.py`
- Create: `tests/contract/cli/test_cli_stop.py`

**Interfaces:**
- Consumes: Supervisor and read projections
- Produces: `ApplicationService.execute(command)`, `ApplicationService.query(query)`, `co-scientist` CLI

- [ ] **Step 1: Write failing boundary test**

```python
# tests/unit/application/test_service_boundary.py
def test_service_sends_commands_to_supervisor_without_exposing_repository(fake_supervisor) -> None:
    service = ApplicationService(supervisor=fake_supervisor, read_model=FakeReadModel())
    result = service.execute(CreateRun(goal_file="goal.yaml", profile_file="core.yaml"))
    assert result.run_id == "r-1"
    assert fake_supervisor.received_commands == ["CreateRun"]
    assert not hasattr(service, "database")
```

- [ ] **Step 2: Write failing CLI replay test**

```python
# tests/contract/cli/test_cli_run.py
from typer.testing import CliRunner

from co_scientist.cli.app import app


def test_cli_runs_a_replay_fixture(tmp_path) -> None:
    result = CliRunner().invoke(app, [
        "run", "start",
        "--goal", "examples/lens_regeneration_goal.yaml",
        "--profile", "configs/profiles/core_preview.yaml",
        "--provider", "replay",
        "--data-dir", str(tmp_path),
    ])
    assert result.exit_code == 0
    assert "run_id=" in result.stdout
```

- [ ] **Step 3: Run tests and confirm application code is missing**

Run: `python3.11 -m pytest tests/unit/application/test_service_boundary.py tests/contract/cli/test_cli_run.py -q`

Expected: FAIL on missing modules.

- [ ] **Step 4: Implement typed commands and service**

```python
class CreateRun(BaseModel):
    goal_file: Path
    profile_file: Path


class RunCommand(BaseModel):
    run_id: str
    expected_run_sequence: int
    command: Literal["start", "pause", "resume", "stop", "cancel"]


class ApplicationService:
    def execute(self, command):
        return self.supervisor.handle_command(command)

    def query(self, query):
        return self.read_model.execute(query)
```

- [ ] **Step 5: Implement CLI commands**

Provide:

```text
co-scientist config check
co-scientist run start --goal PATH --profile PATH --provider fake|replay|openai
co-scientist run status RUN_ID
co-scientist run pause RUN_ID --expected-sequence N
co-scientist run resume RUN_ID --expected-sequence N
co-scientist run stop RUN_ID --expected-sequence N
co-scientist run cancel RUN_ID --expected-sequence N
co-scientist run export RUN_ID --output PATH
co-scientist replay RUN_ID
```

Each command constructs an Application Service command/query. No CLI function imports `SqliteUnitOfWork` directly.

- [ ] **Step 6: Prove stop uses finalization**

```python
# tests/contract/cli/test_cli_stop.py
def test_cli_soft_stop_finishes_through_stopping(cli_harness) -> None:
    run_id = cli_harness.start_replay()
    cli_harness.stop(run_id)
    assert cli_harness.state_history(run_id)[-2:] == ["stopping", "completed_partial"]
```

- [ ] **Step 7: Run CLI tests**

Run: `python3.11 -m pytest tests/unit/application tests/contract/cli -q`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/co_scientist/application src/co_scientist/cli tests/unit/application tests/contract/cli
git commit -m "feat: expose Core Preview through application service and CLI"
```

---

### Task 14: Lens-Regeneration Smoke Run, Export, and Core Release Gate

**Files:**
- Create: `configs/profiles/core_preview.yaml`
- Create: `examples/lens_regeneration_goal.yaml`
- Create: `src/co_scientist/export/__init__.py`
- Create: `src/co_scientist/export/run_export.py`
- Create: `tests/smoke/test_lens_replay_smoke.py`
- Create: `tests/smoke/test_lens_online_smoke.py`
- Create: `tests/scenario/test_crash_boundaries.py`
- Create: `tests/scenario/test_core_release_invariants.py`
- Create: `docs/core-preview.md`

**Interfaces:**
- Consumes: all Core Preview interfaces
- Produces: reproducible smoke command, `export_run(run_id, output_dir) -> Path`, release verification command

- [ ] **Step 1: Create the exact Core Preview profile**

```yaml
# configs/profiles/core_preview.yaml
profile_id: core_preview
review_policy:
  required_before_admission: [initial_review, full_review]
  trigger_rules:
    deep_verification: [critical_assumption_low_confidence]
    observation_review: [scientist_request]
    simulation_review: [high_rank_low_testability]
    recurrent_review: [needs_tiebreaker]
literature_novelty_required: true
tournament:
  initial_rating: 1200
  k_factor: 32
  match_mode: research
  anchor_count: 2
stop:
  minimum_matches: 6
  require_anchor_plateau: true
  require_top_k_stability: true
  require_cluster_diversity_plateau: true
budget:
  max_usd: null
  max_model_calls: 40
  max_hypotheses: 6
  max_matches: 12
providers:
  llm: replay
  literature: replay_pubmed
```

- [ ] **Step 2: Create the lens research goal fixture**

```yaml
# examples/lens_regeneration_goal.yaml
title: Mechanistic determinants of transparent versus fibrotic lens regeneration after minimally invasive lens surgery
goal: >
  Develop and rank mechanistically explicit, falsifiable hypotheses explaining
  how surgical configuration, host age, early postoperative cell state,
  tissue organization, and morphogenesis determine transparent versus fibrotic
  lens regeneration.
required_causal_chain:
  - surgical_configuration
  - host_age_or_development
  - early_postoperative_cell_state
  - tissue_organization_and_morphogenesis
  - final_morphology_and_transparency
required_outputs:
  - earliest_causal_determinant
  - falsifiers
  - discriminating_experiments
```

- [ ] **Step 3: Write the failing replay smoke test**

```python
# tests/smoke/test_lens_replay_smoke.py
def test_lens_replay_exports_a_traceable_ranked_result(core_cli, tmp_path) -> None:
    run_id = core_cli.start_lens(provider="replay", data_dir=tmp_path)
    bundle = core_cli.export(run_id, tmp_path / "export")
    assert bundle.manifest["final_state"] == "completed"
    assert bundle.manifest["state_history"][-2:] == ["stopping", "completed"]
    assert bundle.manifest["tournament_epochs"][0]["research_plan_version"] == 1
    assert bundle.hypotheses[0]["mechanism_chain"] == [
        "surgical_configuration",
        "host_age_or_development",
        "early_postoperative_cell_state",
        "tissue_organization_and_morphogenesis",
        "final_morphology_and_transparency",
    ]
```

- [ ] **Step 4: Implement deterministic export**

```python
def export_run(run_id: str, output_dir: Path, read_model: ReadModel,
               artifacts: ArtifactStore) -> Path:
    output_dir.mkdir(parents=True, exist_ok=False)
    write_json(output_dir / "manifest.json", read_model.run_manifest(run_id))
    write_jsonl(output_dir / "events.jsonl", read_model.events(run_id))
    write_json(output_dir / "hypotheses.json", read_model.hypotheses(run_id))
    write_json(output_dir / "reviews.json", read_model.reviews(run_id))
    write_json(output_dir / "novelty_assessments.json",
               read_model.novelty_assessments(run_id))
    write_json(output_dir / "tournament_epochs.json", read_model.epochs(run_id))
    write_json(output_dir / "costs.json", read_model.costs(run_id))
    return output_dir
```

The export records skill/prompt hashes, provider/model, PubMed query cutoff, epoch contracts, anchors, ExternalCall states, access issues, cost, stop reason, and completeness.

- [ ] **Step 5: Add four crash-boundary assertions**

```python
# tests/scenario/test_crash_boundaries.py
@pytest.mark.parametrize("boundary", [
    "provider_returned_before_raw_persist",
    "raw_persisted_before_validation",
    "agent_result_submitted_before_domain_apply",
    "domain_applied_before_worker_ack",
])
def test_restart_resumes_without_duplicate_domain_result(boundary, crash_harness) -> None:
    recovered = crash_harness.run_and_recover(boundary)
    assert recovered.domain_result_count == 1
    assert recovered.logical_cost_count == 1
    if boundary != "provider_returned_before_raw_persist":
        assert recovered.provider_recall_count == 0
```

- [ ] **Step 6: Add aggregate Core release invariant test**

```python
# tests/scenario/test_core_release_invariants.py
def test_core_release_invariants(release_harness) -> None:
    report = release_harness.verify()
    assert report.agent_created_task_count == 0
    assert report.cross_epoch_elo_comparison_count == 0
    assert report.non_decisive_rating_update_count == 0
    assert report.proximity_derived_novelty_count == 0
    assert report.run_completed_without_finalization_count == 0
    assert report.raw_parsed_before_persist_count == 0
```

- [ ] **Step 7: Add opt-in online lens smoke**

```python
# tests/smoke/test_lens_online_smoke.py
@pytest.mark.online
def test_lens_smoke_with_openai_and_pubmed(online_core_cli, tmp_path) -> None:
    run_id = online_core_cli.start_lens(
        provider="openai", literature_provider="pubmed", data_dir=tmp_path
    )
    summary = online_core_cli.status(run_id)
    assert summary.hypothesis_count >= 2
    assert summary.pubmed_source_count >= 1
    assert summary.raw_artifact_count == summary.completed_external_call_count
```

The fixture requires `OPENAI_API_KEY`, `CO_SCIENTIST_OPENAI_MODEL`, and network access.

- [ ] **Step 8: Write Core Preview operator documentation**

`docs/core-preview.md` must contain:

```text
1. Python 3.11 environment and editable installation
2. Replay smoke command with no credentials
3. OPENAI_API_KEY and CO_SCIENTIST_OPENAI_MODEL setup
4. Optional NCBI tool/email configuration
5. Online smoke command and expected artifacts
6. Pause, resume, stop, cancel, status, replay, and export commands
7. Cost-is-unlimited warning plus model-call/hypothesis/match guards
8. Core Preview scope exclusions
9. Reproduction-level disclaimer
```

- [ ] **Step 9: Run the complete offline release gate**

Run:

```bash
python3.11 -m pytest tests/unit tests/contract tests/scenario tests/smoke -q -m 'not online'
python3.11 -m ruff check src tests
python3.11 -m mypy src/co_scientist
git diff --check
```

Expected: all pytest tests PASS, Ruff reports no errors, mypy reports success, and `git diff --check` prints nothing.

- [ ] **Step 10: Run the opt-in online gate when credentials are available**

Run:

```bash
test -n "$OPENAI_API_KEY" \
  && test -n "$CO_SCIENTIST_OPENAI_MODEL" \
  && \
python3.11 -m pytest tests/contract/llm/test_openai_online.py \
  tests/contract/literature/test_pubmed_online.py \
  tests/smoke/test_lens_online_smoke.py -q -m online
```

Expected: one real LLM adapter, one PubMed adapter, and the lens smoke test PASS with raw artifacts and provider response IDs recorded.

- [ ] **Step 11: Commit**

```bash
git add configs examples src/co_scientist/export tests/smoke tests/scenario docs/core-preview.md
git commit -m "test: verify Co-Scientist Core Preview vertical slice"
```

---

## Completion Evidence

The Core Preview plan is complete only when:

1. all Task 1–14 commits exist in order;
2. the offline release command passes from a clean checkout;
3. the optional online gate passes in an environment with the declared OpenAI and PubMed access;
4. the exported lens run includes raw artifacts, events, content/projection separation, NoveltyAssessments, Proximity edges, TournamentEpoch contracts, decisive/non-decisive matches, ratings, costs, stop evidence, and finalization history;
5. no FastAPI, SSE, React, four additional LLM provider adapters, GPQA, or full benchmark package was added.
