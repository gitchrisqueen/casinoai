"""Leaderboard aggregation tests."""

from casinoai.backtest.runner import BacktestSummary
from casinoai.reports.leaderboard import build_leaderboard, render_markdown


def _summary(name, ev, game="roulette"):
    return BacktestSummary(
        strategy=name,
        spec_version=2,
        game=game,
        git_sha="abc1234",
        seeds=[0, 1],
        max_rounds_per_session=100,
        n_sessions=2,
        total_rounds=200,
        total_staked_units=1000.0,
        total_net_units=ev * 1000.0,
        ev_per_unit_staked=ev,
        session_win_rate=0.5,
        mean_session_net=-1.0,
        stdev_session_net=10.0,
        worst_drawdown_units=20.0,
        risk_of_ruin=0.1,
        sessions=[],
    )


def test_leaderboard_ranks_by_ev_descending():
    summaries = [
        _summary("Worst", -0.03),
        _summary("Best", -0.009),
        _summary("Middle", -0.015),
    ]
    rows = build_leaderboard(summaries)
    assert [r.strategy for r in rows] == ["Best", "Middle", "Worst"]
    assert rows[0].ev_per_unit_staked == -0.009


def test_render_markdown_has_all_strategies_and_totals():
    rows = build_leaderboard([_summary("Alpha", -0.01), _summary("Beta", -0.02)])
    md = render_markdown(rows)
    assert "Alpha v2" in md
    assert "Beta v2" in md
    assert "400 total simulated rounds" in md
    assert "-1.00%" in md  # Alpha EV
