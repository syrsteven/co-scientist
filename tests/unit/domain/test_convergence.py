from co_scientist.domain.budget import BudgetEstimate, BudgetUsage, DurableBudgetSnapshot
from co_scientist.domain.convergence import (
    ConvergenceCheckpoint,
    evaluate_stop,
)


def _checkpoint(**updates) -> ConvergenceCheckpoint:
    values = {
        "checkpoint_id": "checkpoint-1",
        "run_id": "run-1",
        "source_sequence": 30,
        "policy_version": "sha256:stop-policy",
        "epoch_id": "epoch-1",
        "research_plan_version": 1,
        "evaluation_rules_hash": "sha256:rules",
        "ranking_prompt_hash": "sha256:ranking",
        "judge_profile_hash": "sha256:judge",
        "rating_policy_version": "elo-32-v1",
        "admission_policy_version": "admission-v1",
        "anchor_set_id": "anchors-1",
        "anchor_member_ids": ("anchor-a", "anchor-b"),
        "anchor_member_content_hashes": ("sha256:anchor-a", "sha256:anchor-b"),
        "anchor_comparison_ids": ("match-a", "match-b"),
        "top_k": 2,
        "top_k_stability_window": 2,
        "top_k_ids": ("h-1", "h-2"),
        "top_k_window_sequences": (20, 24),
        "top_k_stable": True,
        "cluster_ids": ("cluster-a", "cluster-b"),
        "cluster_membership_ids": ("edge-a", "edge-b"),
        "cluster_diversity_window": 2,
        "cluster_window_sequences": (12, 13),
        "cluster_diversity_satisfied": True,
        "novelty_window_sequences": (14, 15),
        "novelty_plateau": True,
        "minimum_hypotheses": 2,
        "hypothesis_count": 2,
        "minimum_model_calls": 1,
        "model_call_count": 1,
        "minimum_matches": 2,
        "match_count": 2,
        "minimum_coverage": 2,
        "coverage_count": 2,
        "elo_plateau_window": 2,
        "elo_window_sequences": (21, 22),
        "elo_plateau": False,
        "budget_snapshot": DurableBudgetSnapshot(
            run_id="run-1",
            policy_version="sha256:budget",
            settled=BudgetUsage(model_calls=1),
            actively_reserved=BudgetEstimate(),
            hard_limit_reached=False,
            source_reservation_ids=("reservation-1",),
            source_cost_entry_ids=("cost-1",),
        ),
        "unresolved_task_ids": (),
        "evidence_source_sequences": tuple(range(2, 25)),
    }
    values.update(updates)
    return ConvergenceCheckpoint.model_validate(values)


# Mutation caught: treating the auxiliary Elo signal as a primary convergence condition.
def test_checkpoint_quality_convergence_requires_every_primary_durable_gate() -> None:
    assert _checkpoint().quality_converged
    assert not _checkpoint(top_k_stable=False, elo_plateau=True).quality_converged
    assert not _checkpoint(novelty_plateau=False, elo_plateau=True).quality_converged
    assert not _checkpoint(coverage_count=1, elo_plateau=True).quality_converged


def test_elo_plateau_is_only_auxiliary_to_durable_quality_gates() -> None:
    decision = evaluate_stop(
        _checkpoint(top_k_stable=False, elo_plateau=True),
        scientist_action=None,
    )

    assert not decision.should_stop
    assert decision.auxiliary_signals == ("elo_plateau",)


def test_scientist_actions_override_checkpoint_quality() -> None:
    checkpoint = _checkpoint(top_k_stable=False)

    soft = evaluate_stop(checkpoint, scientist_action="soft_stop")
    hard = evaluate_stop(checkpoint, scientist_action="hard_cancel")

    assert (soft.action, hard.action) == ("stop", "cancel")


def test_checkpoint_budget_limit_has_terminal_precedence() -> None:
    exhausted = _checkpoint(
        budget_snapshot=_checkpoint().budget_snapshot.model_copy(
            update={"settled": BudgetUsage(model_calls=10), "hard_limit_reached": True}
        )
    )

    decision = evaluate_stop(exhausted, scientist_action=None)

    assert (decision.action, decision.reason) == ("stop", "hard_budget_reached")
