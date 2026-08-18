import pytest

from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork
from co_scientist.domain.review import ReviewPolicy
from co_scientist.domain.tournament import TournamentEpoch
from co_scientist.events.models import NewEvent
from co_scientist.runtime.checkpoints import ConvergenceCheckpointBuilder
from co_scientist.supervisor.orchestrator import Supervisor


def _manifest(*, minimum_model_calls: int = 0) -> dict[str, object]:
    return {
        "execution_contract_version": 3,
        "budget": {},
        "profile": {
            "stop": {
                "minimum_matches": 2,
                "minimum_hypotheses": 2,
                "minimum_model_calls": minimum_model_calls,
                "top_k": 2,
                "top_k_stability_window": 2,
                "cluster_diversity_window": 2,
                "elo_plateau_window": 2,
            }
        },
        "anchor_sets": [
            {
                "anchor_set_id": "anchors-1",
                "members": [
                    {"anchor_id": "anchor-a", "content_hash": "sha256:" + "a" * 64},
                    {"anchor_id": "anchor-b", "content_hash": "sha256:" + "b" * 64},
                ],
            }
        ],
    }


def _seed(tmp_path, *, minimum_model_calls: int = 0):
    uow = SqliteUnitOfWork(f"sqlite:///{tmp_path / 'checkpoint.db'}")
    uow.create_schema()
    supervisor = Supervisor(uow=uow, review_policy=ReviewPolicy(profile_id="minimal"))
    started = supervisor.create_and_start_run(
        "run-1",
        manifest=_manifest(minimum_model_calls=minimum_model_calls),
        start_payload={},
    )
    epoch = TournamentEpoch(
        epoch_id="epoch-1",
        research_plan_version=1,
        evaluation_rules_hash="sha256:rules",
        ranking_prompt_hash="sha256:ranking",
        judge_profile_hash="sha256:judge",
        rating_policy_version="elo-32-v1",
        admission_policy_version="admission-v1",
        anchor_set_id="anchors-1",
    )
    evidence = (
        NewEvent(event_type="TournamentEpochOpened", payload=epoch.model_dump(mode="json")),
        NewEvent(
            event_type="HypothesisContentCreated",
            schema_version=2,
            payload={"hypothesis_id": "h-1", "research_plan_version": 1},
        ),
        NewEvent(
            event_type="HypothesisContentCreated",
            schema_version=2,
            payload={"hypothesis_id": "h-2", "research_plan_version": 1},
        ),
        NewEvent(
            event_type="TournamentEntryCreated",
            payload={"epoch_id": "epoch-1", "hypothesis_id": "h-1", "rating": 1210.0},
        ),
        NewEvent(
            event_type="TournamentEntryCreated",
            payload={"epoch_id": "epoch-1", "hypothesis_id": "h-2", "rating": 1200.0},
        ),
        NewEvent(
            event_type="NoveltyAssessmentRecorded",
            payload={"hypothesis_id": "h-1", "verdict": "partially_novel"},
        ),
        NewEvent(
            event_type="NoveltyAssessmentRecorded",
            payload={"hypothesis_id": "h-2", "verdict": "not_novel"},
        ),
        NewEvent(
            event_type="ProximityAssessed",
            schema_version=2,
            payload={"edge_id": "edge-1", "cluster_suggestion": "cluster-a"},
        ),
        NewEvent(
            event_type="ProximityAssessed",
            schema_version=2,
            payload={"edge_id": "edge-2", "cluster_suggestion": "cluster-b"},
        ),
        NewEvent(
            event_type="MatchEvaluated",
            schema_version=2,
            payload={
                **epoch.model_dump(mode="json"),
                "match_id": "match-a",
                "left_id": "h-1",
                "right_id": "anchor-a",
                "decision": "inconclusive",
                "winner_id": None,
            },
        ),
        NewEvent(
            event_type="MatchEvaluated",
            schema_version=2,
            payload={
                **epoch.model_dump(mode="json"),
                "match_id": "match-b",
                "left_id": "h-2",
                "right_id": "anchor-b",
                "decision": "inconclusive",
                "winner_id": None,
            },
        ),
    )
    committed = uow.commit_domain_batch(
        run_id="run-1",
        expected_sequence=started.last_sequence,
        events=evidence,
        idempotency_key="seed-checkpoint-evidence",
    )
    return uow, committed.last_sequence


def test_builder_records_all_frozen_evidence_and_exact_source_sequences(tmp_path) -> None:
    uow, sequence = _seed(tmp_path)

    builder = ConvergenceCheckpointBuilder(uow)
    recorded = builder.build_and_record(
        run_id="run-1", expected_sequence=sequence
    )

    checkpoint = builder.load_recorded(
        run_id="run-1",
        checkpoint_id=recorded.checkpoint_id,
        expected_sequence=recorded.commit.last_sequence,
    )
    assert checkpoint.source_sequence == sequence
    assert checkpoint.anchor_member_ids == ("anchor-a", "anchor-b")
    assert checkpoint.anchor_member_content_hashes == (
        "sha256:" + "a" * 64,
        "sha256:" + "b" * 64,
    )
    assert checkpoint.anchor_comparison_ids == ("match-a", "match-b")
    assert checkpoint.top_k_ids == ("h-1", "h-2")
    assert checkpoint.cluster_ids == ("cluster-a", "cluster-b")
    assert checkpoint.cluster_membership_ids == ("edge-1", "edge-2")
    assert checkpoint.quality_converged
    assert checkpoint.evidence_source_sequences == tuple(range(2, sequence + 1))
    assert recorded.commit.events[0].event_type == "ConvergenceCheckpointRecorded"


@pytest.mark.parametrize(
    "mutation",
    ["missing_anchor_members", "missing_anchor_comparison", "minimum_calls"],
)
def test_builder_fails_closed_for_missing_or_insufficient_evidence(tmp_path, mutation: str) -> None:
    uow, sequence = _seed(tmp_path, minimum_model_calls=1 if mutation == "minimum_calls" else 0)
    if mutation == "missing_anchor_members":
        manifest = uow.run_manifest("run-1")
        manifest["anchor_sets"] = []
        with uow.session_factory.begin() as session:
            from co_scientist.adapters.persistence.sqlite import RunRow

            row = session.get(RunRow, "run-1")
            assert row is not None
            import json

            row.manifest_json = json.dumps(manifest)
    elif mutation == "missing_anchor_comparison":
        with uow.session_factory.begin() as session:
            from co_scientist.adapters.persistence.sqlite import EventRow

            session.delete(session.get(EventRow, ("run-1", sequence)))
            sequence -= 1

    with pytest.raises(ValueError, match="anchor|model call"):
        ConvergenceCheckpointBuilder(uow).build_and_record(
            run_id="run-1", expected_sequence=sequence
        )


def test_loading_checkpoint_recomputes_sources_and_rejects_forged_budget(tmp_path) -> None:
    uow, sequence = _seed(tmp_path)
    builder = ConvergenceCheckpointBuilder(uow)
    recorded = builder.build_and_record(run_id="run-1", expected_sequence=sequence)
    with uow.session_factory.begin() as session:
        from co_scientist.adapters.persistence.sqlite import EventRow

        row = session.get(EventRow, ("run-1", recorded.commit.last_sequence))
        assert row is not None
        import json

        payload = json.loads(row.payload_json)
        payload["budget_snapshot"]["settled"]["model_calls"] = 999
        row.payload_json = json.dumps(payload)

    with pytest.raises(ValueError, match="forged|stale"):
        builder.load_recorded(
            run_id="run-1",
            checkpoint_id=recorded.checkpoint_id,
            expected_sequence=recorded.commit.last_sequence,
        )
