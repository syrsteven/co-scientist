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
