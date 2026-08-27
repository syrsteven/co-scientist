def expected_score(rating: float, opponent_rating: float) -> float:
    return 1.0 / (1.0 + 10.0 ** ((opponent_rating - rating) / 400.0))


def update_pair(
    winner: float, loser: float, k_factor: float = 32.0
) -> tuple[float, float]:
    winner_expected = expected_score(winner, loser)
    loser_expected = expected_score(loser, winner)
    return (
        winner + k_factor * (1.0 - winner_expected),
        loser + k_factor * (0.0 - loser_expected),
    )
