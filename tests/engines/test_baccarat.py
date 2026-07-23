"""Baccarat engine: determinism, tableau rules, and house edge vs. theory."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from casinoai.engines.baccarat import (
    BaccaratEngine,
    BaccaratOutcome,
    BaccaratWinner,
    _banker_draws,
)


def test_same_seed_same_sequence():
    a = BaccaratEngine(seed=9)
    b = BaccaratEngine(seed=9)
    for _ in range(1000):
        assert a.deal() == b.deal()


@given(st.integers(min_value=0, max_value=7), st.one_of(st.none(), st.integers(0, 9)))
def test_banker_tableau_matches_standard(banker_total, player_third):
    """Cross-check the tableau against its textbook definition."""
    draws = _banker_draws(banker_total, player_third)
    if player_third is None:
        assert draws == (banker_total <= 5)
    else:
        expected = {
            0: True,
            1: True,
            2: True,
            3: player_third != 8,
            4: 2 <= player_third <= 7,
            5: 4 <= player_third <= 7,
            6: player_third in (6, 7),
            7: False,
        }[banker_total]
        assert draws == expected


def test_totals_are_mod_10_and_winner_consistent():
    engine = BaccaratEngine(seed=3)
    for _ in range(5000):
        o = engine.deal()
        assert 0 <= o.player_total <= 9
        assert 0 <= o.banker_total <= 9
        assert o.player_total == sum(o.player_cards) % 10
        assert o.banker_total == sum(o.banker_cards) % 10
        if o.winner == BaccaratWinner.TIE:
            assert o.player_total == o.banker_total
        elif o.winner == BaccaratWinner.PLAYER:
            assert o.player_total > o.banker_total
        else:
            assert o.banker_total > o.player_total
        assert 2 <= len(o.player_cards) <= 3
        assert 2 <= len(o.banker_cards) <= 3
        if o.natural:
            assert len(o.player_cards) == 2 and len(o.banker_cards) == 2


def test_settle_rules():
    win_b = BaccaratOutcome(
        winner=BaccaratWinner.BANKER,
        player_total=3,
        banker_total=7,
        player_cards=[1, 2],
        banker_cards=[3, 4],
        natural=False,
    )
    tie = win_b.model_copy(update={"winner": BaccaratWinner.TIE, "player_total": 7})
    assert BaccaratEngine.settle("banker", 100, win_b) == pytest.approx(95)
    assert BaccaratEngine.settle("player", 100, win_b) == -100
    assert BaccaratEngine.settle("tie", 100, win_b) == -100
    assert BaccaratEngine.settle("player", 100, tie) == 0.0
    assert BaccaratEngine.settle("banker", 100, tie) == 0.0
    assert BaccaratEngine.settle("tie", 100, tie) == 800


@pytest.mark.parametrize(
    ("bet", "theoretical_edge", "tol"),
    [
        ("banker", -0.0106, 0.004),
        ("player", -0.0124, 0.004),
        ("tie", -0.1436, 0.02),
    ],
)
def test_simulated_edges_match_theory(bet, theoretical_edge, tol):
    """500k seeded hands per bet; observed EV within tolerance of theory."""
    engine = BaccaratEngine(seed=77)
    n = 500_000
    net = sum(BaccaratEngine.settle(bet, 1, engine.deal()) for _ in range(n))
    assert net / n == pytest.approx(theoretical_edge, abs=tol)
