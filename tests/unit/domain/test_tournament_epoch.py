import pytest
from pydantic import ValidationError

from co_scientist.domain.tournament import (
    EpochContractMismatch,
    TournamentEpoch,
    admit_entry,
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


def test_prompt_or_plan_mismatch_invalidates_match_contract() -> None:
    with pytest.raises(EpochContractMismatch):
        validate_match_contract(
            _epoch(),
            plan_version=2,
            prompt_hash="prompt-a",
            judge_hash="judge-a",
            rating_policy="elo-v1",
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
