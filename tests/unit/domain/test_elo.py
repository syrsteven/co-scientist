from co_scientist.domain.elo import update_pair


def test_equal_ratings_move_by_half_k() -> None:
    winner, loser = update_pair(1200.0, 1200.0, k_factor=32.0)

    assert winner == 1216.0
    assert loser == 1184.0
