import pytest
from pydantic import ValidationError

from co_scientist.domain.tournament import (
    EpochContractMismatch,
    MatchResult,
    TournamentEpoch,
    admit_entry,
    get_rating_policy,
    validate_match_contract,
)


def _epoch() -> TournamentEpoch:
    return TournamentEpoch(
        epoch_id="epoch-1",
        research_plan_version=1,
        evaluation_rules_hash="rules-a",
        ranking_prompt_hash="prompt-a",
        judge_profile_hash="judge-a",
        rating_policy_version="elo-v1",
        admission_policy_version="admission-v1",
    )


@pytest.mark.parametrize(
    "contract_override",
    [
        {"plan_version": 2},
        {"rules_hash": "rules-b"},
        {"prompt_hash": "prompt-b"},
        {"judge_hash": "judge-b"},
        {"rating_policy": "elo-v2"},
        {"admission_policy": "admission-v2"},
    ],
)
def test_each_contract_dimension_mismatch_invalidates_match(
    contract_override: dict[str, int | str],
) -> None:
    contract = {
        "plan_version": 1,
        "rules_hash": "rules-a",
        "prompt_hash": "prompt-a",
        "judge_hash": "judge-a",
        "rating_policy": "elo-v1",
        "admission_policy": "admission-v1",
    }
    contract.update(contract_override)

    with pytest.raises(EpochContractMismatch):
        validate_match_contract(_epoch(), **contract)


def test_complete_matching_contract_is_accepted() -> None:
    assert (
        validate_match_contract(
            _epoch(),
            plan_version=1,
            rules_hash="rules-a",
            prompt_hash="prompt-a",
            judge_hash="judge-a",
            rating_policy="elo-v1",
            admission_policy="admission-v1",
        )
        is None
    )


def test_admission_scopes_entry_to_epoch_at_default_rating() -> None:
    entry = admit_entry(_epoch(), hypothesis_id="h-1", content_hash="sha256:content")

    assert entry.epoch_id == "epoch-1"
    assert entry.hypothesis_id == "h-1"
    assert entry.content_hash == "sha256:content"
    assert entry.rating == 1200.0
    assert entry.matches_played == 0


def test_epoch_contract_is_frozen() -> None:
    epoch = _epoch()

    with pytest.raises(ValidationError):
        epoch.ranking_prompt_hash = "prompt-b"


# Mutation caught: silently remapping a persisted policy version to current defaults.
def test_rating_policy_version_resolves_frozen_elo_parameters() -> None:
    policy = get_rating_policy("elo-32-v1")

    assert policy.version == "elo-32-v1"
    assert policy.initial_rating == 1200.0
    assert policy.k_factor == 32.0


def test_unknown_rating_policy_version_fails_closed() -> None:
    with pytest.raises(ValueError, match="unknown rating policy"):
        get_rating_policy("elo-current-default")


# Mutation caught: treating one hypothesis as both tournament participants.
def test_match_result_rejects_identical_participants() -> None:
    with pytest.raises(ValidationError, match="distinct participants"):
        MatchResult(
            match_id="self-match",
            epoch_id="epoch-1",
            left_id="h-1",
            right_id="h-1",
            decision="decisive",
            winner_id="h-1",
        )
