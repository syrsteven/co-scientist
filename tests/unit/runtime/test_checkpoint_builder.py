import json

import pytest
from sqlalchemy import select

from co_scientist.adapters.persistence.sqlite import EventRow, SqliteUnitOfWork
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
            event_type="TournamentEntryCreated",
            payload={
                "epoch_id": "epoch-1",
                "hypothesis_id": "anchor-a",
                "rating": 1200.0,
            },
        ),
        NewEvent(
            event_type="TournamentEntryCreated",
            payload={
                "epoch_id": "epoch-1",
                "hypothesis_id": "anchor-b",
                "rating": 1200.0,
            },
        ),
        NewEvent(
            event_type="NoveltyAssessmentRecorded",
            payload={
                "assessment_id": "novelty-h-1",
                "hypothesis_id": "h-1",
                "verdict": "partially_novel",
                "epoch_id": "epoch-1",
                "research_plan_version": 1,
            },
        ),
        NewEvent(
            event_type="NoveltyAssessmentRecorded",
            payload={
                "assessment_id": "novelty-h-2",
                "hypothesis_id": "h-2",
                "verdict": "not_novel",
                "epoch_id": "epoch-1",
                "research_plan_version": 1,
            },
        ),
        NewEvent(
            event_type="ProximityAssessed",
            schema_version=2,
            payload={
                "edge_id": "edge-1",
                "left_id": "h-1",
                "right_id": "h-2",
                "cluster_suggestion": "cluster-a",
                "epoch_id": "epoch-1",
                "research_plan_version": 1,
            },
        ),
        NewEvent(
            event_type="ProximityAssessed",
            schema_version=2,
            payload={
                "edge_id": "edge-2",
                "left_id": "h-2",
                "right_id": "h-1",
                "cluster_suggestion": "cluster-b",
                "epoch_id": "epoch-1",
                "research_plan_version": 1,
            },
        ),
        NewEvent(
            event_type="MatchEvaluated",
            schema_version=2,
            payload={
                **epoch.model_dump(mode="json"),
                "match_id": "match-a",
                "left_id": "h-1",
                "right_id": "anchor-a",
                "right_content_hash": "sha256:" + "a" * 64,
                "anchor_set_id": "anchors-1",
                "comparison_kind": "fixed_anchor",
                "decision": "decisive",
                "winner_id": "anchor-a",
                "source_result_id": "result-match-a",
                "source_task_id": "task-match-a",
                "status": "completed",
            },
            causation_id="result-match-a",
            correlation_id="run-1",
        ),
        NewEvent(
            event_type="RatingUpdated",
            payload={
                "match_id": "match-a",
                "epoch_id": "epoch-1",
                "hypothesis_id": "h-1",
                "before_rating": 1210.0,
                "rating": 1193.539610106688,
                "rating_policy_version": "elo-32-v1",
            },
            causation_id="result-match-a",
            correlation_id="run-1",
        ),
        NewEvent(
            event_type="RatingUpdated",
            payload={
                "match_id": "match-a",
                "epoch_id": "epoch-1",
                "hypothesis_id": "anchor-a",
                "before_rating": 1200.0,
                "rating": 1216.460389893312,
                "rating_policy_version": "elo-32-v1",
            },
            causation_id="result-match-a",
            correlation_id="run-1",
        ),
        NewEvent(
            event_type="MatchEvaluated",
            schema_version=2,
            payload={
                **epoch.model_dump(mode="json"),
                "match_id": "match-b",
                "left_id": "h-2",
                "right_id": "anchor-b",
                "right_content_hash": "sha256:" + "b" * 64,
                "anchor_set_id": "anchors-1",
                "comparison_kind": "fixed_anchor",
                "decision": "decisive",
                "winner_id": "h-2",
                "source_result_id": "result-match-b",
                "source_task_id": "task-match-b",
                "status": "completed",
            },
            causation_id="result-match-b",
            correlation_id="run-1",
        ),
        NewEvent(
            event_type="RatingUpdated",
            payload={
                "match_id": "match-b",
                "epoch_id": "epoch-1",
                "hypothesis_id": "h-2",
                "before_rating": 1200.0,
                "rating": 1216.0,
                "rating_policy_version": "elo-32-v1",
            },
            causation_id="result-match-b",
            correlation_id="run-1",
        ),
        NewEvent(
            event_type="RatingUpdated",
            payload={
                "match_id": "match-b",
                "epoch_id": "epoch-1",
                "hypothesis_id": "anchor-b",
                "before_rating": 1200.0,
                "rating": 1184.0,
                "rating_policy_version": "elo-32-v1",
            },
            causation_id="result-match-b",
            correlation_id="run-1",
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
    assert checkpoint.top_k_ids == ("h-2", "h-1")
    assert checkpoint.top_k_window_match_ids == ("match-a", "match-b")
    assert checkpoint.top_k_window_sequences == (15, 18)
    assert checkpoint.top_k_stable
    assert checkpoint.cluster_ids == ("cluster-a", "cluster-b")
    assert checkpoint.cluster_membership_ids == ("edge-1", "edge-2")
    assert checkpoint.quality_converged
    assert checkpoint.evidence_source_sequences == tuple(range(2, sequence + 1))
    assert recorded.commit.events[0].event_type == "ConvergenceCheckpointRecorded"


@pytest.mark.parametrize(
    ("provenance_field", "forged_value"),
    [
        ("causation_id", "jointly-forged-result"),
        ("correlation_id", "foreign-run"),
    ],
)
def test_builder_rejects_jointly_forged_match_and_rating_provenance(
    tmp_path, provenance_field: str, forged_value: str
) -> None:
    uow, sequence = _seed(tmp_path)
    with uow.session_factory.begin() as session:
        rows = [
            row
            for row in session.scalars(
                select(EventRow)
                .where(EventRow.run_id == "run-1")
                .order_by(EventRow.sequence)
            )
            if json.loads(row.payload_json).get("match_id") == "match-a"
        ]
        assert [row.event_type for row in rows] == [
            "MatchEvaluated",
            "RatingUpdated",
            "RatingUpdated",
        ]
        for row in rows:
            setattr(row, provenance_field, forged_value)

    with pytest.raises(ValueError, match="provenance|causation|correlation|Run"):
        ConvergenceCheckpointBuilder(uow).build_and_record(
            run_id="run-1", expected_sequence=sequence
        )


@pytest.mark.parametrize("decision", ["inconclusive", "invalid", "needs_tiebreaker"])
def test_builder_rejects_ratings_from_non_decisive_match(tmp_path, decision: str) -> None:
    uow, sequence = _seed(tmp_path)
    with uow.session_factory.begin() as session:
        row = next(
            row
            for row in session.scalars(
                select(EventRow).where(
                    EventRow.run_id == "run-1",
                    EventRow.event_type == "MatchEvaluated",
                )
            )
            if json.loads(row.payload_json).get("match_id") == "match-a"
        )
        payload = json.loads(row.payload_json)
        payload.update(decision=decision, winner_id=None)
        row.payload_json = json.dumps(payload)

    with pytest.raises(ValueError, match="decisive|rating"):
        ConvergenceCheckpointBuilder(uow).build_and_record(
            run_id="run-1", expected_sequence=sequence
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "incomplete",
        "duplicate_participant",
        "foreign_participant",
        "wrong_rating_policy",
        "stale_epoch",
        "forged_provenance",
        "forged_rating_value",
    ],
)
def test_builder_rejects_incomplete_or_forged_rating_application(
    tmp_path, mutation: str
) -> None:
    uow, sequence = _seed(tmp_path)
    with uow.session_factory.begin() as session:
        rating_rows = [
            row
            for row in session.scalars(
                select(EventRow)
                .where(
                    EventRow.run_id == "run-1",
                    EventRow.event_type == "RatingUpdated",
                )
                .order_by(EventRow.sequence)
            )
            if json.loads(row.payload_json).get("match_id") == "match-a"
        ]
        assert len(rating_rows) == 2
        candidate_row, anchor_row = rating_rows
        if mutation == "incomplete":
            session.delete(anchor_row)
        elif mutation == "forged_provenance":
            anchor_row.causation_id = "foreign-result"
        else:
            payload = json.loads(anchor_row.payload_json)
            if mutation == "duplicate_participant":
                payload["hypothesis_id"] = json.loads(candidate_row.payload_json)[
                    "hypothesis_id"
                ]
            elif mutation == "foreign_participant":
                payload["hypothesis_id"] = "outsider"
            elif mutation == "wrong_rating_policy":
                payload["rating_policy_version"] = "forged-rating-policy"
            elif mutation == "forged_rating_value":
                payload["rating"] = 9999.0
            else:
                payload["epoch_id"] = "stale-epoch"
            anchor_row.payload_json = json.dumps(payload)

    with pytest.raises(ValueError, match="rating|participant|provenance|contract"):
        ConvergenceCheckpointBuilder(uow).build_and_record(
            run_id="run-1", expected_sequence=sequence
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_anchor_hash",
        "missing_fixed_provenance",
        "candidate_not_top_k",
        "duplicate_comparison_id",
        "unbound_cluster",
        "unbound_novelty",
    ],
)
def test_builder_rejects_invalid_or_ambiguous_bound_evidence(tmp_path, mutation: str) -> None:
    uow, sequence = _seed(tmp_path)
    from co_scientist.adapters.persistence.sqlite import EventRow

    with uow.session_factory.begin() as session:
        rows = session.scalars(
            select(EventRow)
            .where(EventRow.run_id == "run-1")
            .order_by(EventRow.sequence)
        ).all()
        payloads = [(row, json.loads(row.payload_json)) for row in rows]
        if mutation in {
            "wrong_anchor_hash",
            "missing_fixed_provenance",
            "candidate_not_top_k",
        }:
            row, payload = next(
                item
                for item in payloads
                if item[1].get("match_id") == "match-a"
                and item[0].event_type == "MatchEvaluated"
            )
            if mutation == "wrong_anchor_hash":
                payload["right_content_hash"] = "sha256:" + "f" * 64
            elif mutation == "missing_fixed_provenance":
                payload["comparison_kind"] = "opportunistic"
            else:
                payload["left_id"] = "outsider"
            row.payload_json = json.dumps(payload)
        elif mutation == "duplicate_comparison_id":
            row, payload = next(
                item
                for item in payloads
                if item[1].get("match_id") == "match-b"
                and item[0].event_type == "MatchEvaluated"
            )
            payload["match_id"] = "match-a"
            row.payload_json = json.dumps(payload)
        elif mutation == "unbound_cluster":
            row, payload = next(
                item for item in payloads if item[1].get("edge_id") == "edge-2"
            )
            payload["right_id"] = "outsider"
            row.payload_json = json.dumps(payload)
        else:
            row, payload = next(
                item for item in payloads if item[1].get("assessment_id") == "novelty-h-2"
            )
            payload["hypothesis_id"] = "outsider"
            row.payload_json = json.dumps(payload)

    with pytest.raises(
        ValueError, match="anchor|comparison|cluster|novelty|cohort|rating|participant"
    ):
        ConvergenceCheckpointBuilder(uow).build_and_record(
            run_id="run-1", expected_sequence=sequence
        )


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
            row.manifest_json = json.dumps(manifest)
    elif mutation == "missing_anchor_comparison":
        with uow.session_factory.begin() as session:
            from co_scientist.adapters.persistence.sqlite import EventRow

            rows = session.scalars(
                select(EventRow).where(
                    EventRow.run_id == "run-1",
                    EventRow.payload_json.contains('"match_id":"match-b"'),
                )
            ).all()
            for row in rows:
                session.delete(row)
            sequence = max(
                row.sequence
                for row in session.scalars(
                    select(EventRow).where(EventRow.run_id == "run-1")
                ).all()
            )

    with pytest.raises(ValueError, match="anchor|model call|coverage"):
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
