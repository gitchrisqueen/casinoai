"""Blackjack engine: determinism, hand math, strategy spot-checks, house edge."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from casinoai.engines.blackjack import (
    BlackjackEngine,
    _basic_strategy,
    hand_value,
)


def test_same_seed_same_sequence():
    a = BlackjackEngine(seed=5)
    b = BlackjackEngine(seed=5)
    for _ in range(2000):
        assert a.deal() == b.deal()


@given(st.lists(st.sampled_from([2, 3, 4, 5, 6, 7, 8, 9, 10, 11]), min_size=2, max_size=8))
def test_hand_value_bounds(cards):
    total, soft = hand_value(cards)
    hard_min = sum(1 if c == 11 else c for c in cards)
    assert total >= hard_min
    assert total <= sum(cards)
    if soft:
        assert 11 in cards and total <= 21


def test_basic_strategy_spot_checks():
    # canonical chart entries, 6-deck S17 DAS
    assert _basic_strategy([8, 8], 10, True, True) == "split"
    assert _basic_strategy([10, 10], 6, True, True) == "stand"
    assert _basic_strategy([9, 9], 7, True, True) == "stand"
    assert _basic_strategy([5, 6], 10, True, True) == "double"  # 11 vs 10
    assert _basic_strategy([5, 6], 11, True, True) == "hit"  # 11 vs A (S17)
    assert _basic_strategy([11, 7], 6, True, True) == "double"  # soft 18 vs 6
    assert _basic_strategy([11, 7], 9, True, True) == "hit"  # soft 18 vs 9
    assert _basic_strategy([10, 6], 10, True, True) == "hit"  # 16 vs 10
    assert _basic_strategy([10, 6], 6, True, True) == "stand"  # 16 vs 6
    assert _basic_strategy([10, 2], 4, True, True) == "stand"  # 12 vs 4
    assert _basic_strategy([10, 2], 2, True, True) == "hit"  # 12 vs 2


def test_naturals_pay_three_to_two():
    engine = BlackjackEngine(seed=0)
    seen_bj = 0
    for _ in range(20_000):
        o = engine.deal()
        if o.player_blackjack and not o.dealer_blackjack:
            assert o.net_multiplier == 1.5
            seen_bj += 1
        if o.player_blackjack and o.dealer_blackjack:
            assert o.net_multiplier == 0.0
    assert seen_bj > 0


def test_blackjack_frequency_matches_theory():
    """Player natural ≈ 4.75% of hands."""
    engine = BlackjackEngine(seed=42)
    n = 100_000
    bj = sum(engine.deal().player_blackjack for _ in range(n))
    assert bj / n == pytest.approx(0.0475, abs=0.004)


def test_settle_scales_stake():
    engine = BlackjackEngine(seed=1)
    o = engine.deal()
    assert BlackjackEngine.settle("hand", 10, o) == pytest.approx(10 * o.net_multiplier)
    with pytest.raises(ValueError):
        BlackjackEngine.settle("red", 10, o)


def test_house_edge_matches_basic_strategy_theory():
    """6-deck S17 DAS no-surrender basic strategy ≈ -0.5% per base unit
    (split-to-two-hands-only costs a few hundredths). 400k hands."""
    engine = BlackjackEngine(seed=7)
    n = 400_000
    net = sum(engine.deal().net_multiplier for _ in range(n))
    assert net / n == pytest.approx(-0.005, abs=0.006)
