from enum import StrEnum

from pydantic import BaseModel, ConfigDict, model_validator

from co_scientist.domain.elo import update_pair


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


class EpochContractMismatch(ValueError):
    pass


def validate_match_contract(
    epoch: TournamentEpoch,
    *,
    plan_version: int,
    rules_hash: str,
    prompt_hash: str,
    judge_hash: str,
    rating_policy: str,
    admission_policy: str,
) -> None:
    actual = (
        plan_version,
        rules_hash,
        prompt_hash,
        judge_hash,
        rating_policy,
        admission_policy,
    )
    expected = (
        epoch.research_plan_version,
        epoch.evaluation_rules_hash,
        epoch.ranking_prompt_hash,
        epoch.judge_profile_hash,
        epoch.rating_policy_version,
        epoch.admission_policy_version,
    )
    if actual != expected:
        raise EpochContractMismatch(f"{actual} != {expected}")


def admit_entry(
    epoch: TournamentEpoch,
    hypothesis_id: str,
    content_hash: str,
    initial_rating: float = 1200.0,
) -> TournamentEntry:
    return TournamentEntry(
        epoch_id=epoch.epoch_id,
        hypothesis_id=hypothesis_id,
        content_hash=content_hash,
        rating=initial_rating,
    )


def apply_match(
    left_rating: float,
    right_rating: float,
    result: MatchResult,
    *,
    k_factor: float = 32.0,
) -> tuple[float, float]:
    if result.decision is not MatchDecision.DECISIVE:
        raise ValueError("only decisive matches update rating")
    if result.winner_id == result.left_id:
        return update_pair(left_rating, right_rating, k_factor)
    winner, loser = update_pair(right_rating, left_rating, k_factor)
    return loser, winner
