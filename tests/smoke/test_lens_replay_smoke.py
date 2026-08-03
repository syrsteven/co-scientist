import asyncio
import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from co_scientist.adapters.artifacts.filesystem import FilesystemArtifactStore
from co_scientist.adapters.literature.pubmed import parse_pubmed_records
from co_scientist.adapters.literature.replay import ReplayLiteratureProvider
from co_scientist.adapters.llm.replay import ReplayLLMProvider
from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork
from co_scientist.agents.executor import SkillExecutor
from co_scientist.agents.result import AgentExecutionContext, AgentResult
from co_scientist.domain.convergence import ConvergenceSnapshot
from co_scientist.domain.hypothesis import HypothesisContent
from co_scientist.domain.review import (
    NoveltyAssessment,
    ReviewPolicy,
    ReviewStage,
    required_review_stages,
)
from co_scientist.domain.states import TaskState
from co_scientist.domain.task import NewTask
from co_scientist.domain.tournament import TournamentEpoch
from co_scientist.events.models import NewEvent
from co_scientist.export.run_export import SqliteRunReadModel, export_run
from co_scientist.ports.external_provider import RawExternalResponse
from co_scientist.runtime.external_calls import (
    ExternalCallRunner,
    request_fingerprint,
)
from co_scientist.skills.loader import load_skill
from co_scientist.supervisor.orchestrator import Supervisor

MECHANISM_CHAIN = [
    "surgical_configuration",
    "host_age_or_development",
    "early_postoperative_cell_state",
    "tissue_organization_and_morphogenesis",
    "final_morphology_and_transparency",
]


def _sha256_json(value: object) -> str:
    canonical = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _skill_request(skill_id: str, inputs: dict[str, Any]) -> dict[str, Any]:
    skill_directory = Path("skills") / skill_id
    manifest = load_skill(skill_directory)
    return {
        "skill_id": manifest.id,
        "skill_version": manifest.version,
        "system_prompt": (skill_directory / manifest.prompt_path).read_text(encoding="utf-8"),
        "input_schema": manifest.input_schema,
        "output_schema": manifest.output_schema,
        "allowed_tools": list(manifest.allowed_tools),
        "input": inputs,
    }


class _LiteratureOperation:
    def __init__(self, provider: ReplayLiteratureProvider, operation: str) -> None:
        self.provider = provider
        self.operation = operation

    async def invoke(self, request: dict[str, Any]) -> RawExternalResponse:
        if self.operation == "search":
            return await self.provider.search(request["query"], request["limit"])
        return await self.provider.fetch_summaries(tuple(request["pmids"]))


class LensRun:
    def __init__(
        self,
        *,
        run_id: str,
        uow: SqliteUnitOfWork,
        artifacts: FilesystemArtifactStore,
    ) -> None:
        self.run_id = run_id
        self.uow = uow
        self.artifacts = artifacts


class ExportBundle:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.manifest = self._json("manifest.json")
        self.hypotheses = self._json("hypotheses.json")
        self.reviews = self._json("reviews.json")
        self.novelty_assessments = self._json("novelty_assessments.json")
        self.proximity = self._json("proximity.json")
        self.matches = self._json("matches.json")
        self.ratings = self._json("ratings.json")
        self.external_calls = self._json("external_calls.json")
        self.costs = self._json("costs.json")
        self.literature = self._json("literature.json")
        self.artifacts = self._json("artifacts.json")

    def _json(self, filename: str) -> Any:
        return json.loads((self.root / filename).read_text(encoding="utf-8"))


class LensReplayHarness:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.run: LensRun | None = None
        self._expected_sequence = 0

    def start_lens(
        self,
        *,
        provider: str,
        data_dir: Path,
        literature_provider: str = "replay_pubmed",
    ) -> str:
        assert provider == "replay"
        assert literature_provider == "replay_pubmed"
        assert data_dir == self.data_dir
        return asyncio.run(self._start_lens())

    def export(self, run_id: str, output_dir: Path) -> ExportBundle:
        assert self.run is not None and run_id == self.run.run_id
        root = export_run(
            run_id,
            output_dir,
            SqliteRunReadModel(self.run.uow),
            self.run.artifacts,
        )
        return ExportBundle(root)

    @staticmethod
    def _profile() -> dict[str, Any]:
        return yaml.safe_load(Path("configs/profiles/core_preview.yaml").read_text())

    @staticmethod
    def _goal() -> dict[str, Any]:
        return yaml.safe_load(Path("examples/lens_regeneration_goal.yaml").read_text())

    async def _start_lens(self) -> str:
        profile = self._profile()
        goal = self._goal()
        run_id = "lens-replay-run"
        uow = SqliteUnitOfWork(f"sqlite:///{self.data_dir / 'lens.db'}")
        uow.create_schema()
        artifacts = FilesystemArtifactStore(self.data_dir / "artifacts")
        supervisor = Supervisor(
            uow=uow,
            review_policy=ReviewPolicy.model_validate(
                {"profile_id": profile["profile_id"], **profile["review_policy"]}
            ),
        )
        started = supervisor.create_and_start_run(
            run_id,
            manifest={
                "profile_id": profile["profile_id"],
                "profile": profile,
                "goal": goal,
                "provider": provider_name(profile),
                "literature_provider": profile["providers"]["literature"],
                "reproduction_level": "deterministic_offline_replay",
            },
            start_payload={
                "profile_id": profile["profile_id"],
                "goal_title": goal["title"],
                "provider": profile["providers"]["llm"],
            },
        )
        epoch = TournamentEpoch(
            epoch_id="epoch-1",
            research_plan_version=1,
            evaluation_rules_hash="sha256:lens-rules-v1",
            ranking_prompt_hash=_sha256_json(
                Path("skills/ranking/prompts/system.md").read_text(encoding="utf-8")
            ),
            judge_profile_hash="sha256:replay-judge-v1",
            rating_policy_version="elo-32-v1",
            admission_policy_version="core-preview-v1",
            anchor_set_id="lens-anchors-v1",
        )
        opened = uow.commit_domain_batch(
            run_id=run_id,
            expected_sequence=started.last_sequence,
            events=(
                NewEvent(event_type="TournamentEpochOpened", payload=epoch.model_dump(mode="json")),
            ),
            idempotency_key="epoch-open:lens-replay-run:epoch-1",
        )
        self._expected_sequence = opened.last_sequence
        self.run = LensRun(run_id=run_id, uow=uow, artifacts=artifacts)
        runtime = SimpleNamespace(uow=uow, artifacts=artifacts)
        runner = ExternalCallRunner(runtime)

        contents = self._hypothesis_contents()
        generation_payload = {
            "hypotheses": [
                {
                    "hypothesis_id": hypothesis_id,
                    **content.model_dump(mode="json"),
                    "content_hash": content.content_hash,
                    "generation_strategy": "causal-chain contrast",
                }
                for hypothesis_id, content in contents.items()
            ]
        }
        await self._run_skill(
            supervisor,
            runner,
            task_id="generate:lens:1",
            skill_id="generation",
            inputs={"research_goal": goal["goal"], "required_causal_chain": MECHANISM_CHAIN},
            payload=generation_payload,
        )

        pubmed = ReplayLiteratureProvider(
            Path("tests/scenario/fixtures/pubmed_search_lens.json"),
            Path("tests/scenario/fixtures/pubmed_summary_lens.json"),
        )
        query = "lens epithelial regeneration fibrosis transparent surgery"
        search_result = await self._run_external(
            supervisor,
            runner,
            task_id="literature:pubmed-search:lens",
            skill_id="meta_review",
            call_id="call-pubmed-search",
            request={"query": query, "limit": 10},
            provider=_LiteratureOperation(pubmed, "search"),
            provider_name="replay_pubmed",
            model_or_tool="esearch",
            validator=lambda raw: {
                "pubmed_query": query,
                "pubmed_query_cutoff": "2026-07-30",
                "pmids": json.loads(raw)["esearchresult"]["idlist"],
                "access_issues": [],
            },
        )
        pmids = tuple(search_result.payload["pmids"])
        await self._run_external(
            supervisor,
            runner,
            task_id="literature:pubmed-summary:lens",
            skill_id="meta_review",
            call_id="call-pubmed-summary",
            request={"pmids": list(pmids), "query": query},
            provider=_LiteratureOperation(pubmed, "summary"),
            provider_name="replay_pubmed",
            model_or_tool="esummary",
            validator=lambda raw: {
                "pubmed_query": query,
                "pubmed_query_cutoff": "2026-07-30",
                "source_documents": [
                    document.model_dump(mode="json")
                    for document in parse_pubmed_records(
                        raw,
                        query=query,
                        raw_artifact_ref="external-call:call-pubmed-summary",
                    )
                ],
                "access_issues": [],
            },
        )

        assessments: dict[str, NoveltyAssessment] = {}
        for hypothesis_id, content in contents.items():
            await self._run_skill(
                supervisor,
                runner,
                task_id=f"review:initial_review:{hypothesis_id}",
                skill_id="reflection",
                inputs={"hypothesis_id": hypothesis_id, "review_stage": "initial_review"},
                payload={
                    "review_id": f"review-initial-{hypothesis_id}",
                    "hypothesis_id": hypothesis_id,
                    "content_hash": content.content_hash,
                    "stage": "initial_review",
                    "recommendation": "pass",
                    "dimension_scores": {"mechanistic_specificity": 0.9},
                    "critical_flaws": [],
                    "evidence_ids": [],
                    "safety_passed": True,
                },
            )
            assessment = NoveltyAssessment(
                assessment_id=f"novelty-{hypothesis_id}",
                hypothesis_id=hypothesis_id,
                content_hash=content.content_hash,
                research_plan_version=1,
                verdict="novel" if hypothesis_id == "h-1" else "partially_novel",
                closest_prior_work_ids=("pubmed:1001", "pubmed:1002"),
                evidence_ids=("pubmed:1001",),
            )
            assessments[hypothesis_id] = assessment
            await self._run_skill(
                supervisor,
                runner,
                task_id=f"review:full_review:{hypothesis_id}",
                skill_id="reflection",
                inputs={
                    "hypothesis_id": hypothesis_id,
                    "review_stage": "full_review",
                    "source_ids": ["pubmed:1001", "pubmed:1002"],
                },
                payload={
                    "review_id": f"review-full-{hypothesis_id}",
                    "hypothesis_id": hypothesis_id,
                    "content_hash": content.content_hash,
                    "stage": "full_review",
                    "recommendation": "pass",
                    "dimension_scores": {"novelty": 0.8, "testability": 0.9},
                    "critical_flaws": [],
                    "evidence_ids": ["pubmed:1001", "pubmed:1002"],
                    "novelty_assessment": assessment.model_dump(mode="json"),
                },
            )

        await self._run_skill(
            supervisor,
            runner,
            task_id="proximity:h-1:h-2",
            skill_id="proximity",
            inputs={"left_id": "h-1", "right_id": "h-2"},
            payload={
                "left_id": "h-1",
                "right_id": "h-2",
                "similarity": 2,
                "mechanism_overlap": ["early_postoperative_cell_state"],
                "duplicate_likelihood": 0.05,
                "cluster_suggestion": "distinct_mechanisms",
            },
        )

        completed_stages = {ReviewStage.INITIAL, ReviewStage.FULL}
        for hypothesis_id, content in contents.items():
            admission = supervisor.admit_hypothesis(
                run_id=run_id,
                expected_sequence=self._expected_sequence,
                hypothesis_id=hypothesis_id,
                content_hash=content.content_hash,
                safety_passed=True,
                required_stages=required_review_stages(supervisor.review_policy),
                completed_stages=completed_stages,
                novelty_required=profile["literature_novelty_required"],
                novelty_assessment=assessments[hypothesis_id],
                proximity_complete=True,
                duplicate=False,
            )
            assert admission.commit is not None
            self._expected_sequence = admission.commit.last_sequence

        decisions = [
            ("decisive", "h-1"),
            ("decisive", "h-2"),
            ("inconclusive", None),
            ("decisive", "h-1"),
            ("needs_tiebreaker", None),
            ("decisive", "h-2"),
        ]
        for index, (decision, winner_id) in enumerate(decisions, start=1):
            await self._run_skill(
                supervisor,
                runner,
                task_id=f"ranking:match-{index}",
                skill_id="ranking",
                inputs={
                    "match_id": f"match-{index}",
                    "epoch_id": epoch.epoch_id,
                    "left_id": "h-1",
                    "right_id": "h-2",
                },
                payload={
                    "match_id": f"match-{index}",
                    "epoch_id": epoch.epoch_id,
                    "left_id": "h-1",
                    "right_id": "h-2",
                    "decision": decision,
                    "winner_id": winner_id,
                    "research_plan_version": epoch.research_plan_version,
                    "evaluation_rules_hash": epoch.evaluation_rules_hash,
                    "ranking_prompt_hash": epoch.ranking_prompt_hash,
                    "judge_profile_hash": epoch.judge_profile_hash,
                    "rating_policy_version": epoch.rating_policy_version,
                    "admission_policy_version": epoch.admission_policy_version,
                },
            )

        stopped = supervisor.tick(
            run_id=run_id,
            expected_sequence=self._expected_sequence,
            convergence=ConvergenceSnapshot(
                epoch_id=epoch.epoch_id,
                anchor_set_id=epoch.anchor_set_id,
                elo_plateau=True,
                anchor_plateau=True,
                top_k_stable=True,
                cluster_diversity_plateau=True,
                minimum_budget_satisfied=True,
            ),
            hard_budget_reached=False,
        )
        assert stopped.commit is not None
        for state in (TaskState.LEASED, TaskState.RUNNING, TaskState.RESULT_RECEIVED):
            uow.transition_task(f"finalize:{run_id}", state)
        supervisor.apply_finalization(
            run_id,
            expected_sequence=stopped.commit.last_sequence,
            completeness="complete",
        )
        return run_id

    @staticmethod
    def _hypothesis_contents() -> dict[str, HypothesisContent]:
        return {
            "h-1": HypothesisContent(
                content_id="content-h-1-v1",
                title="Early epithelial-state commitment gates transparent regeneration",
                claim=(
                    "Age-dependent postoperative epithelial state is the earliest causal gate "
                    "between capsular geometry and ordered transparent morphogenesis."
                ),
                mechanism_chain=tuple(MECHANISM_CHAIN),
                assumptions=("capsule mechanics alter early cell-state trajectories",),
                predictions=("early anti-EMT intervention rescues transparency",),
                falsifiers=("late-only intervention fully rescues transparency",),
            ),
            "h-2": HypothesisContent(
                content_id="content-h-2-v1",
                title="Capsule geometry gates tissue organization independently of inflammation",
                claim=(
                    "Surgical configuration and host age jointly set a geometric organization "
                    "threshold that determines ordered fiber morphogenesis versus fibrosis."
                ),
                mechanism_chain=tuple(MECHANISM_CHAIN),
                assumptions=("capsular geometry persists through early healing",),
                predictions=("geometry correction restores radial organization",),
                falsifiers=("matched geometry leaves morphology unchanged across ages",),
            ),
        }

    def _ensure_task(
        self,
        supervisor: Supervisor,
        *,
        task_id: str,
        skill_id: str,
    ) -> None:
        assert self.run is not None
        try:
            self.run.uow.task_state(task_id)
        except KeyError:
            scheduled = supervisor.enqueue_task(
                task=NewTask(
                    task_id=task_id,
                    run_id=self.run.run_id,
                    idempotency_key=task_id,
                    intent_type=f"run_{skill_id}",
                    payload={"skill_id": skill_id},
                ),
                expected_sequence=self._expected_sequence,
            )
            self._expected_sequence = scheduled.last_sequence
        self.run.uow.transition_task(task_id, TaskState.LEASED)
        self.run.uow.transition_task(task_id, TaskState.RUNNING)

    async def _run_skill(
        self,
        supervisor: Supervisor,
        runner: ExternalCallRunner,
        *,
        task_id: str,
        skill_id: str,
        inputs: dict[str, Any],
        payload: dict[str, Any],
    ) -> AgentResult:
        assert self.run is not None
        self._ensure_task(supervisor, task_id=task_id, skill_id=skill_id)
        call_id = f"call-{task_id.replace(':', '-')}"
        request = _skill_request(skill_id, inputs)
        context = AgentExecutionContext(
            run_id=self.run.run_id,
            task_id=task_id,
            idempotency_key=task_id,
            skill_id=skill_id,
            skill_version="0.1.0",
            output_schema_version=1,
            input_snapshot_hash=_sha256_json(inputs),
        )
        self.run.uow.plan_external_call(
            call_id,
            request_fingerprint(request),
            run_id=self.run.run_id,
            task_id=task_id,
            execution_context=context.model_dump(mode="json"),
            provider="replay",
            model_or_tool="core-preview-fixture-v1",
        )
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
        result = await SkillExecutor(
            runner,
            ReplayLLMProvider({request_fingerprint(request): raw}),
        ).execute(
            call_id=call_id,
            skill_directory=Path("skills") / skill_id,
            inputs=inputs,
            context=context,
        )
        self.run.uow.transition_task(task_id, TaskState.RESULT_RECEIVED)
        committed = supervisor.handle_result(
            self.run.run_id,
            task_id,
            result,
            expected_sequence=self._expected_sequence,
        )
        self._expected_sequence = committed.last_sequence
        return result

    async def _run_external(
        self,
        supervisor: Supervisor,
        runner: ExternalCallRunner,
        *,
        task_id: str,
        skill_id: str,
        call_id: str,
        request: dict[str, Any],
        provider: _LiteratureOperation,
        provider_name: str,
        model_or_tool: str,
        validator: Callable[[bytes], dict[str, Any]],
    ) -> AgentResult:
        assert self.run is not None
        self._ensure_task(supervisor, task_id=task_id, skill_id=skill_id)
        context = AgentExecutionContext(
            run_id=self.run.run_id,
            task_id=task_id,
            idempotency_key=task_id,
            skill_id=skill_id,
            skill_version="0.1.0",
            output_schema_version=1,
            input_snapshot_hash=_sha256_json(request),
        )
        self.run.uow.plan_external_call(
            call_id,
            request_fingerprint(request),
            run_id=self.run.run_id,
            task_id=task_id,
            execution_context=context.model_dump(mode="json"),
            provider=provider_name,
            model_or_tool=model_or_tool,
        )
        result = await runner.execute(
            call_id=call_id,
            request=request,
            provider=provider,
            validator=validator,
            context=context,
        )
        self.run.uow.transition_task(task_id, TaskState.RESULT_RECEIVED)
        committed = supervisor.handle_result(
            self.run.run_id,
            task_id,
            result,
            expected_sequence=self._expected_sequence,
        )
        self._expected_sequence = committed.last_sequence
        return result


def provider_name(profile: dict[str, Any]) -> str:
    return str(profile["providers"]["llm"])


@pytest.fixture
def core_cli(tmp_path: Path) -> LensReplayHarness:
    return LensReplayHarness(tmp_path)


# Mutations caught: bypassing raw-first/Supervisor paths, exporting fixture expectations
# instead of persisted read models, omitting finalization, or losing scientific provenance.
def test_lens_replay_exports_a_traceable_ranked_result(
    core_cli: LensReplayHarness,
    tmp_path: Path,
) -> None:
    run_id = core_cli.start_lens(provider="replay", data_dir=tmp_path)
    bundle = core_cli.export(run_id, tmp_path / "export")

    assert bundle.manifest["final_state"] == "completed"
    assert bundle.manifest["state_history"][-2:] == ["stopping", "completed"]
    assert bundle.manifest["stop_reason"] == "quality_converged"
    assert bundle.manifest["completeness"] == "complete"
    assert bundle.manifest["finalization_state"] == "completed"
    assert bundle.manifest["tournament_epochs"][0]["research_plan_version"] == 1
    assert bundle.hypotheses[0]["mechanism_chain"] == MECHANISM_CHAIN
    assert bundle.hypotheses[0]["projection"]["lifecycle_state"] == "tournament_ready"
    assert {review["stage"] for review in bundle.reviews} == {
        "initial_review",
        "full_review",
    }
    assert {item["assessment_id"] for item in bundle.novelty_assessments} == {
        "novelty-h-1",
        "novelty-h-2",
    }
    assert bundle.proximity == [
        {
            "duplicate_likelihood": 0.05,
            "left_id": "h-1",
            "mechanism_overlap": ["early_postoperative_cell_state"],
            "right_id": "h-2",
            "similarity": 2,
        }
    ]
    assert len(bundle.matches) == 6
    assert {match["decision"] for match in bundle.matches} >= {
        "decisive",
        "inconclusive",
    }
    assert all(
        not match["rating_updated"]
        for match in bundle.matches
        if match["decision"] != "decisive"
    )
    assert bundle.ratings["epoch-1"]["h-1"] != 1200.0
    assert all(call["state"] == "domain_result_applied" for call in bundle.external_calls)
    assert len(bundle.artifacts) == len(bundle.external_calls) == len(bundle.costs)
    assert all((bundle.root / item["exported_path"]).is_file() for item in bundle.artifacts)
    assert bundle.literature["pubmed_query_cutoffs"] == ["2026-07-30"]
    assert bundle.literature["access_issues"] == []
    assert {source["canonical_id"] for source in bundle.literature["source_documents"]} == {
        "PMID:1001",
        "PMID:1002",
    }
    event_types = [
        json.loads(line)["event_type"]
        for line in (bundle.root / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert event_types[-3:] == [
        "TaskEnqueued",
        "FinalizationCompleted",
        "RunCompleted",
    ]


# Mutations caught: including export time/path, random output ordering, or rewriting raw bytes.
def test_export_is_byte_deterministic_for_one_persisted_run(
    core_cli: LensReplayHarness,
    tmp_path: Path,
) -> None:
    run_id = core_cli.start_lens(provider="replay", data_dir=tmp_path)
    first = core_cli.export(run_id, tmp_path / "export-a").root
    second = core_cli.export(run_id, tmp_path / "export-b").root

    first_files = {
        path.relative_to(first).as_posix(): path.read_bytes()
        for path in first.rglob("*")
        if path.is_file()
    }
    second_files = {
        path.relative_to(second).as_posix(): path.read_bytes()
        for path in second.rglob("*")
        if path.is_file()
    }
    assert first_files == second_files


# Mutation caught: truncating or merging into a pre-existing export directory.
def test_export_fails_without_touching_an_existing_output_directory(
    core_cli: LensReplayHarness,
    tmp_path: Path,
) -> None:
    run_id = core_cli.start_lens(provider="replay", data_dir=tmp_path)
    destination = tmp_path / "existing-export"
    destination.mkdir()
    sentinel = destination / "keep.txt"
    sentinel.write_text("preserve me\n", encoding="utf-8")

    with pytest.raises(FileExistsError):
        core_cli.export(run_id, destination)

    assert sentinel.read_text(encoding="utf-8") == "preserve me\n"
    assert list(destination.iterdir()) == [sentinel]
