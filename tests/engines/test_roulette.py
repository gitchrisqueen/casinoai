"""Roulette engine: determinism, payout math, and house edge vs. theory."""

from fractions import Fraction

import pytest
from hypothesis import given
from hypothesis import strategies as st

from casinoai.engines.roulette import (
    PAYOUTS,
    RED_NUMBERS,
    Color,
    RouletteEngine,
    RouletteOutcome,
    Wheel,
)

ALL_POCKETS_EU = [*map(str, range(37))]
ALL_POCKETS_US = [*ALL_POCKETS_EU, "00"]


def test_same_seed_same_sequence():
    a = RouletteEngine(seed=42)
    b = RouletteEngine(seed=42)
    assert [a.spin().pocket for _ in range(500)] == [b.spin().pocket for _ in range(500)]


def test_different_seed_different_sequence():
    a = RouletteEngine(seed=1)
    b = RouletteEngine(seed=2)
    assert [a.spin().pocket for _ in range(100)] != [b.spin().pocket for _ in range(100)]


def test_american_wheel_has_double_zero():
    engine = RouletteEngine(wheel=Wheel.AMERICAN, seed=7)
    seen = {engine.spin().pocket for _ in range(5000)}
    assert seen == set(ALL_POCKETS_US)
    seen_eu = {RouletteEngine(seed=7).spin().pocket for _ in range(5000)}
    assert "00" not in seen_eu


@given(st.sampled_from(ALL_POCKETS_US))
def test_outcome_fields_consistent(pocket):
    o = RouletteOutcome.from_pocket(pocket)
    if pocket in ("0", "00"):
        assert o.color == Color.GREEN
        assert o.parity is o.dozen is o.column is o.half is None
    else:
        n = int(pocket)
        assert (o.color == Color.RED) == (n in RED_NUMBERS)
        assert o.parity == ("even" if n % 2 == 0 else "odd")
        assert o.dozen == (n - 1) // 12 + 1
        assert o.column == (n - 1) % 3 + 1
        assert o.half == ("low" if n <= 18 else "high")


@given(st.sampled_from(sorted(PAYOUTS)), st.floats(min_value=0.01, max_value=1000))
def test_settle_is_win_or_full_loss(bet_type, stake):
    o = RouletteOutcome.from_pocket("17")
    net = RouletteEngine.settle(bet_type, stake, o)
    assert net == -stake or net > 0


def test_straight_pays_35_to_1():
    o = RouletteOutcome.from_pocket("17")
    assert RouletteEngine.settle("straight_17", 10, o) == 350
    assert RouletteEngine.settle("straight_18", 10, o) == -10


def test_zeros_lose_all_outside_bets():
    for pocket in ("0", "00"):
        o = RouletteOutcome.from_pocket(pocket)
        for bet in ("red", "black", "even", "odd", "low", "high", "dozen_1", "column_3"):
            assert RouletteEngine.settle(bet, 5, o) == -5


@pytest.mark.parametrize(
    ("wheel", "expected_edge"),
    [(Wheel.EUROPEAN, Fraction(1, 37)), (Wheel.AMERICAN, Fraction(2, 38))],
)
@pytest.mark.parametrize("bet_type", ["red", "even", "dozen_2", "straight_17"])
def test_exact_house_edge_over_all_pockets(wheel, expected_edge, bet_type):
    """EV computed exactly over every pocket must equal the theoretical edge."""
    pockets = ALL_POCKETS_US if wheel == Wheel.AMERICAN else ALL_POCKETS_EU
    wins, odds = PAYOUTS[bet_type]
    total = sum((odds if wins(RouletteOutcome.from_pocket(p)) else Fraction(-1)) for p in pockets)
    assert Fraction(total, len(pockets)) == -expected_edge


def test_simulated_edge_matches_theory():
    """1M seeded spins betting red: observed edge within 0.5% of -2.70%."""
    engine = RouletteEngine(seed=123)
    net = sum(RouletteEngine.settle("red", 1, engine.spin()) for _ in range(1_000_000))
    assert abs(net / 1_000_000 - (-1 / 37)) < 0.005
