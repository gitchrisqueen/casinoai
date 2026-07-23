"""Live/demo adapter tests — driven by a recorded tape, no browser needed."""

import pytest

from casinoai.backtest.runner import backtest
from casinoai.live import (
    GuardViolation,
    NullBetPlacer,
    RecordedTableReader,
    SessionGuard,
    SessionLimits,
    compare,
    run_live_session,
)
from casinoai.live.playwright_adapter import assert_demo_mode, default_result_parser
from casinoai.live.session import load_sessions, save_session
from tests.rules.test_oracle import martingale_spec

# -- guard -----------------------------------------------------------------------


def test_guard_refuses_non_demo():
    with pytest.raises(GuardViolation, match="demo"):
        SessionGuard(SessionLimits(demo_only=True), is_demo=False)


def test_guard_blocks_oversized_bet():
    guard = SessionGuard(SessionLimits(max_bet_units=4), is_demo=True)

    class B:
        def __init__(self, s):
            self.stake_units = s
            self.bet_type = "red"

    guard.check_bets([B(4)])  # ok
    with pytest.raises(GuardViolation, match="max_bet"):
        guard.check_bets([B(8)])


def test_guard_caps_total_stake():
    guard = SessionGuard(SessionLimits(max_bet_units=10, max_total_stake_units=5), is_demo=True)

    class B:
        def __init__(self, s):
            self.stake_units = s
            self.bet_type = "red"

    with pytest.raises(GuardViolation, match="max_total_stake"):
        guard.check_bets([B(3), B(3)])


def test_guard_session_stops():
    guard = SessionGuard(
        SessionLimits(stop_loss_units=10, stop_win_units=10, max_rounds=5), is_demo=True
    )
    assert guard.check_session(-10, 1) is not None
    assert "stop-loss" in guard.check_session(-11, 1)
    assert "stop-win" in guard.check_session(10, 1)
    assert "max-rounds" in guard.check_session(0, 5)
    assert guard.check_session(-3, 2) is None


# -- session loop ----------------------------------------------------------------


def test_live_session_matches_engine_on_same_tape():
    """The live loop over a fixed pocket tape must reproduce exactly what the
    oracle+engine would compute for that same sequence — sim/live parity."""
    # black=2, red=1 pockets; martingale on red
    pockets = ["2", "2", "2", "1", "2"]  # L L L W L
    spec = martingale_spec(bankroll={"stop_loss_units": 1000, "stop_win_units": 1000})
    reader = RecordedTableReader(pockets)
    placer = NullBetPlacer()
    session = run_live_session(
        spec,
        reader,
        placer,
        SessionLimits(max_bet_units=100, stop_loss_units=1000, max_rounds=100),
        table_url="demo://tape",
        now="2026-07-23T00:00:00Z",
    )
    stakes = [r.bets[0]["stake_units"] for r in session.rounds]
    assert stakes == [1, 2, 4, 8, 1]
    # net: -1-2-4+8-1 = 0
    assert session.net_units == pytest.approx(0.0)
    assert len(session.rounds) == 5  # 5 resolved rounds
    # a 6th bet is placed (martingale after the round-5 loss) but the tape ends
    # before it resolves — realistic: an unresolved demo bet is simply not recorded
    assert [p[0].stake_units for p in placer.placed][:5] == [1, 2, 4, 8, 1]


def test_live_session_guard_stop_loss_overrides_spec():
    """Even with a huge spec stop-loss, the guard halts the session."""
    spec = martingale_spec(bankroll={"stop_loss_units": 100000})
    reader = RecordedTableReader(["2"] * 50)  # all losses
    session = run_live_session(
        spec,
        reader,
        NullBetPlacer(),
        SessionLimits(max_bet_units=100000, max_total_stake_units=100000, stop_loss_units=7),
        now="2026-07-23T00:00:00Z",
    )
    assert "guard stop-loss" in session.stop_reason
    assert session.net_units <= -7


def test_live_session_ends_when_table_unavailable():
    spec = martingale_spec(bankroll={"stop_loss_units": 1000})
    reader = RecordedTableReader(["2", "2"])  # tape runs out
    session = run_live_session(
        spec,
        reader,
        NullBetPlacer(),
        SessionLimits(stop_loss_units=1000, max_bet_units=1000),
        now="2026-07-23T00:00:00Z",
    )
    assert session.stop_reason == "table unavailable"


def test_session_save_and_load(tmp_path):
    spec = martingale_spec()
    session = run_live_session(
        spec,
        RecordedTableReader(["1", "2"]),
        NullBetPlacer(),
        SessionLimits(max_bet_units=100, stop_loss_units=1000),
        now="2026-07-23T00:00:00Z",
    )
    save_session(session, sessions_dir=tmp_path)
    loaded = load_sessions(tmp_path)
    assert len(loaded) == 1
    assert loaded[0].strategy == session.strategy


# -- compare ---------------------------------------------------------------------


def test_compare_live_to_sim():
    spec = martingale_spec(bankroll={"stop_loss_units": 20, "stop_win_units": 10})
    bt = backtest(spec, seeds=list(range(50)), max_rounds=500)
    sessions = [
        run_live_session(
            spec,
            RecordedTableReader([str(p) for p in ([2] * 3 + [1] * 3) * 20]),
            NullBetPlacer(),
            SessionLimits(
                max_bet_units=1000,
                max_total_stake_units=1000,
                stop_loss_units=20,
                stop_win_units=10,
            ),
            now="2026-07-23T00:00:00Z",
        )
    ]
    cmp = compare(sessions, bt)
    assert cmp.live_sessions == 1
    assert cmp.strategy == bt.strategy
    assert "directional" in cmp.note  # < 10 sessions
    assert cmp.sim_ev_per_unit_staked == bt.ev_per_unit_staked


# -- demo-mode safety ------------------------------------------------------------


def test_assert_demo_mode_accepts_demo_and_refuses_real():
    assert_demo_mode("https://x.com/GameLauncher?realMode=0&game=roulette")  # ok
    with pytest.raises(RuntimeError, match="real-money"):
        assert_demo_mode("https://x.com/GameLauncher?realMode=1")
    with pytest.raises(RuntimeError, match="could not confirm"):
        assert_demo_mode("https://x.com/game?foo=bar")


def test_default_result_parser():
    assert default_result_parser({"winningNumber": 17}) == "17"
    assert default_result_parser({"result": "0"}) == "0"
    assert default_result_parser({"chat": "hello"}) is None
    assert default_result_parser({"number": 99}) is None  # out of range


# -- manual observer reader ------------------------------------------------------


def test_manual_reader_reads_pockets_and_ends():
    from casinoai.live.reader import ManualTableReader

    tape = iter(["17", "0", "q"])
    reader = ManualTableReader(read_fn=lambda _prompt: next(tape))
    assert reader.read_next_spin().pocket == "17"
    assert reader.read_next_spin().pocket == "0"
    assert reader.read_next_spin() is None  # 'q' ends


def test_manual_reader_drives_full_session():
    tape = iter(["2", "2", "1", ""])  # L L W, then end
    from casinoai.live.reader import ManualTableReader

    spec = martingale_spec(bankroll={"stop_loss_units": 1000})
    session = run_live_session(
        spec,
        ManualTableReader(read_fn=lambda _p: next(tape)),
        NullBetPlacer(),
        SessionLimits(max_bet_units=100, max_total_stake_units=100, stop_loss_units=1000),
        now="2026-07-23T00:00:00Z",
    )
    assert [r.pocket for r in session.rounds] == ["2", "2", "1"]
    assert session.stop_reason == "table unavailable"


# -- CLI safety gate -------------------------------------------------------------


def test_cli_live_refuses_without_confirmation(tmp_path, capsys):
    from casinoai.cli import main
    from casinoai.strategies import load_spec, save_spec

    spec = load_spec("strategies/approved/power-pro-roulette-v2.yaml")
    spec_path = save_spec(spec, spec_dir=tmp_path)
    # without the confirmation flag, it must refuse and not start a session
    rc = main(["live", str(spec_path)])
    assert rc == 1
    assert "Refusing to start" in capsys.readouterr().out
