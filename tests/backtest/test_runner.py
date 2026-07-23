"""Backtester: reproducibility, accounting, and EV vs. house edge."""

import pytest

from casinoai.backtest.runner import backtest, run_session
from tests.rules.test_oracle import martingale_spec


def test_same_seeds_reproduce_exactly():
    spec = martingale_spec()
    a = backtest(spec, seeds=list(range(10)), max_rounds=200)
    b = backtest(spec, seeds=list(range(10)), max_rounds=200)
    assert a.sessions == b.sessions
    assert a.total_net_units == b.total_net_units


def test_session_accounting_consistent():
    s = run_session(martingale_spec(), seed=5, max_rounds=500)
    assert s.rounds_played <= 500
    assert s.max_drawdown_units >= 0
    assert s.total_staked_units > 0


def test_sessions_respect_stops():
    spec = martingale_spec(bankroll={"stop_loss_units": 15, "stop_win_units": 10})
    result = backtest(spec, seeds=list(range(50)), max_rounds=10_000)
    for s in result.sessions:
        assert s.stop_reason is not None  # tight stops always trigger eventually
        if "stop-loss" in s.stop_reason:
            assert s.net_units <= -15
        if "stop-win" in s.stop_reason:
            assert s.net_units >= 10


def test_flat_betting_ev_matches_house_edge():
    """EV per unit staked ≈ -1/37. Flat stakes, because unbounded martingale
    staking is heavy-tailed and converges far too slowly to assert on."""
    spec = martingale_spec(progression={"kind": "flat", "units": 1.0}, bankroll={})
    result = backtest(spec, seeds=list(range(30)), max_rounds=5_000)
    assert result.total_rounds == 30 * 5_000
    assert result.total_staked_units == 30 * 5_000
    assert result.ev_per_unit_staked == pytest.approx(-1 / 37, abs=0.01)


def test_risk_of_ruin_counts_stop_losses():
    spec = martingale_spec(bankroll={"stop_loss_units": 7, "stop_win_units": 1000})
    result = backtest(spec, seeds=list(range(20)), max_rounds=5_000)
    assert result.risk_of_ruin > 0.5  # 7-unit stop-loss with martingale dies fast
