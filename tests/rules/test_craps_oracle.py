"""Oracle drives the craps engine end-to-end for a simple pass-line system."""

import pytest

from casinoai.engines.craps import CrapsEngine
from casinoai.rules.oracle import compile_spec
from casinoai.strategies.spec import StrategySpec


def passline_martingale() -> StrategySpec:
    return StrategySpec.model_validate(
        {
            "name": "Pass Line Martingale",
            "game": "craps",
            "summary": "Flat pass-line bet, double on loss.",
            "bets": [{"bet_type": "pass_line"}],
            "progression": {"kind": "multiplier", "factor": 2.0, "on": "loss"},
            "bankroll": {"stop_loss_units": 63, "stop_win_units": 20},
        }
    )


def test_oracle_plays_craps_session():
    oracle = compile_spec(passline_martingale())
    engine = CrapsEngine(seed=3)
    total = 0.0
    for _ in range(500):
        action = oracle.next_action()
        if action.stop:
            break
        total += oracle.observe(engine.play_coup())
    assert total == pytest.approx(oracle.net_units)
    if oracle.stopped and "stop-loss" in oracle.stopped:
        assert oracle.net_units <= -63


def test_dont_pass_flat_ev_matches_theory():
    """Flat don't-pass EV per unit staked ≈ -1.36% over many seeds."""
    from casinoai.backtest.runner import backtest

    spec = StrategySpec.model_validate(
        {
            "name": "Dont Pass Flat",
            "game": "craps",
            "summary": "Flat don't-pass bet every coup.",
            "bets": [{"bet_type": "dont_pass"}],
            "progression": {"kind": "flat", "units": 1.0},
            "bankroll": {},
        }
    )
    result = backtest(spec, seeds=list(range(20)), max_rounds=5_000)
    assert result.ev_per_unit_staked == pytest.approx(-3 / 220, abs=0.01)
