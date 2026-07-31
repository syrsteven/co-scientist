from co_scientist.domain.convergence import ConvergenceSnapshot, evaluate_stop


def convergence_snapshot(*, anchor_plateau: bool) -> ConvergenceSnapshot:
    return ConvergenceSnapshot(
        epoch_id="e-1",
        elo_plateau=True,
        anchor_plateau=anchor_plateau,
        top_k_stable=True,
        cluster_diversity_plateau=True,
        minimum_budget_satisfied=True,
    )


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


def test_missing_anchor_evidence_disables_quality_stop() -> None:
    snapshot = convergence_snapshot(anchor_plateau=False)

    assert not evaluate_stop(
        snapshot, hard_budget_reached=False, scientist_action=None
    ).should_stop


def test_hard_budget_and_scientist_actions_are_terminal() -> None:
    snapshot = convergence_snapshot(anchor_plateau=False)

    budget = evaluate_stop(snapshot, hard_budget_reached=True, scientist_action=None)
    soft = evaluate_stop(snapshot, hard_budget_reached=False, scientist_action="soft_stop")
    hard = evaluate_stop(snapshot, hard_budget_reached=False, scientist_action="hard_cancel")

    assert (budget.action, soft.action, hard.action) == ("stop", "stop", "cancel")
