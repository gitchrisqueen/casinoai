"""Craps engine: determinism, coup resolution, and house edge vs. theory."""

from fractions import Fraction

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from casinoai.engines.craps import CrapsEngine, CrapsOutcome, LineResult


def test_same_seed_same_sequence():
    a = CrapsEngine(seed=9)
    b = CrapsEngine(seed=9)
    assert [a.play_coup().rolls for _ in range(500)] == [b.play_coup().rolls for _ in range(500)]


def test_different_seed_diverges():
    a = [CrapsEngine(seed=1).play_coup().rolls for _ in range(50)]
    b = [CrapsEngine(seed=2).play_coup().rolls for _ in range(50)]
    assert a != b


@settings(max_examples=50)
@given(seed=st.integers(min_value=0, max_value=10_000))
def test_coup_invariants(seed):
    engine = CrapsEngine(seed=seed)
    for _ in range(200):
        o = engine.play_coup()
        assert 2 <= o.come_out <= 12
        assert o.rolls[0] == o.come_out
        assert all(2 <= r <= 12 for r in o.rolls)
        if o.point is None:
            # resolved on come-out
            assert len(o.rolls) == 1
            assert o.come_out in (2, 3, 7, 11, 12)
            assert not o.seven_out
        else:
            assert o.come_out in (4, 5, 6, 8, 9, 10)
            last = o.rolls[-1]
            assert last == o.point or last == 7
            assert o.seven_out == (last == 7)
        if o.result == LineResult.DONT_PUSH:
            assert o.come_out == 12


def test_come_out_resolutions():
    def outcome_for(come_out, point=None, rolls=None):
        return CrapsOutcome(
            result=LineResult.PASS_WIN,
            come_out=come_out,
            point=point,
            rolls=rolls or [come_out],
            seven_out=False,
        )

    # settle logic on synthetic outcomes
    win = outcome_for(7)
    lose = CrapsOutcome(
        result=LineResult.PASS_LOSE, come_out=3, point=None, rolls=[3], seven_out=False
    )
    push = CrapsOutcome(
        result=LineResult.DONT_PUSH, come_out=12, point=None, rolls=[12], seven_out=False
    )
    assert CrapsEngine.settle("pass_line", 10, win) == 10
    assert CrapsEngine.settle("pass_line", 10, lose) == -10
    assert CrapsEngine.settle("pass_line", 10, push) == -10  # pass loses on 12
    assert CrapsEngine.settle("dont_pass", 10, win) == -10
    assert CrapsEngine.settle("dont_pass", 10, lose) == 10
    assert CrapsEngine.settle("dont_pass", 10, push) == 0  # bar 12: push


def test_unknown_bet_raises():
    o = CrapsOutcome(result=LineResult.PASS_WIN, come_out=7, point=None, rolls=[7], seven_out=False)
    with pytest.raises(ValueError):
        CrapsEngine.settle("hardway", 5, o)


def test_pass_line_house_edge_matches_theory():
    """Pass line EV = -7/495 ≈ -1.414% per unit. 2M coups."""
    engine = CrapsEngine(seed=123)
    n = 2_000_000
    net = sum(CrapsEngine.settle("pass_line", 1, engine.play_coup()) for _ in range(n))
    assert net / n == pytest.approx(float(Fraction(-7, 495)), abs=0.003)


def test_dont_pass_house_edge_matches_theory():
    """Don't pass (bar 12) EV = -3/220 ≈ -1.364% per unit. 2M coups."""
    engine = CrapsEngine(seed=321)
    n = 2_000_000
    net = sum(CrapsEngine.settle("dont_pass", 1, engine.play_coup()) for _ in range(n))
    assert net / n == pytest.approx(float(Fraction(-3, 220)), abs=0.003)
