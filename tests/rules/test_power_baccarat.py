"""Power Baccarat machines, verified against the book's worked table
(Power Baccarat, LaMarca 2015, pp. 62-65) and Target Betting rules (pp. 48-50)."""

import pytest

from casinoai.engines.baccarat import BaccaratOutcome, BaccaratWinner
from casinoai.rules.library import PowerBaccaratProgression, TrackerSelection
from casinoai.rules.oracle import compile_spec
from casinoai.strategies.spec import StrategySpec


def test_book_worked_table_pp62_65():
    """Rounds 1-14: strike -> counterstrike -> strike -> trend -> strike."""
    m = PowerBaccaratProgression()
    # (mode, stake_units, won) — dollar amounts from the book divided by $5 base
    table = [
        ("strike", 1.0, False),
        ("strike", 2.0, False),
        ("counter", 0.6, False),
        ("counter", 1.0, False),
        ("counter", 2.0, False),
        ("counter", 4.0, True),
        ("strike", 3.0, True),
        ("strike", 2.0, True),
        ("strike", 1.0, True),
        ("trend", 1.2, True),
        ("trend", 1.0, True),
        ("trend", 1.6, True),
        ("trend", 2.0, False),
        ("strike", 3.0, True),
    ]
    for i, (mode, stake, won) in enumerate(table, 1):
        assert m.mode == mode, f"round {i}: expected {mode}, got {m.mode}"
        assert m.stake() == pytest.approx(stake), f"round {i}"
        m.advance(won)


def test_trend_extends_by_increments_of_three_dollars():
    m = PowerBaccaratProgression()
    m.advance(True)  # L1 strike win -> trend
    for _ in range(7):  # win the whole printed trend series
        m.advance(True)
    assert m.stake() == pytest.approx(3.8)  # $16 + $3 = $19 -> 3.8u
    m.advance(True)
    assert m.stake() == pytest.approx(4.4)  # $22


def test_counterstrike_exhaustion_busts():
    m = PowerBaccaratProgression()
    m.advance(False)
    m.advance(False)  # two strike losses -> counterstrike
    assert m.mode == "counter"
    for _ in range(7):
        m.advance(False)
    assert m.busted


def bk(winner):
    return BaccaratOutcome(
        winner=winner,
        player_total=1,
        banker_total=5,
        player_cards=[1, 0],
        banker_cards=[2, 3],
        natural=False,
    )


BANKER, PLAYER, TIE = BaccaratWinner.BANKER, BaccaratWinner.PLAYER, BaccaratWinner.TIE


def test_tracker_alternates_s_o_regardless_of_results():
    sel = TrackerSelection()
    assert sel.select() is None
    sel.observe(bk(BANKER), None)  # observe a decision
    assert sel.select() == "banker"  # S
    sel.observe(bk(BANKER), True)
    assert sel.select() == "player"  # O — alternates even after a win
    sel.observe(bk(BANKER), False)
    assert sel.select() == "banker"  # S again


def test_tracker_two_losses_repeat_then_restart_at_s():
    sel = TrackerSelection()
    sel.observe(bk(BANKER), None)
    # S bet on banker loses (player wins), O bet loses -> pattern SO lost
    sel.observe(bk(PLAYER), False)  # S lost; last decision now player
    assert sel.select() == "banker"  # O = opposite of player
    sel.observe(bk(PLAYER), False)  # O lost -> two consecutive losses
    # repeat the last letter (O) for exactly one bet
    assert sel.select() == "banker"  # O repeated
    sel.observe(bk(PLAYER), False)  # even if the repeat loses...
    assert sel.select() == "player"  # ...next restarts alternation at S
    sel.observe(bk(PLAYER), True)
    assert sel.select() == "banker"  # O


def test_tracker_tie_changes_nothing():
    sel = TrackerSelection()
    sel.observe(bk(BANKER), None)
    before = sel.select()
    sel.observe(bk(TIE), None)  # tie: bet pushed, nothing advances
    assert sel.select() == before
    assert sel.pos == 0 and not sel.repeating


def pb_spec() -> StrategySpec:
    return StrategySpec.model_validate(
        {
            "name": "Power Baccarat",
            "game": "baccarat",
            "summary": "Tracker selection with three-mode Strike/Counterstrike/Trend sizing.",
            "bets": [{"bet_type": "player"}, {"bet_type": "banker"}],
            "bet_selection": {"kind": "registered", "name": "tracker", "description": "SOS"},
            "progression": {
                "kind": "registered",
                "name": "power_baccarat",
                "description": "3-mode",
            },
            "bankroll": {
                "unit_size": 5.0,
                "session_bankroll_units": 87.0,
                "stop_loss_units": 87.0,
                "stop_win_units": 8.0,
                "max_bet_units": 34.0,
            },
        }
    )


def test_oracle_sessions_end_cleanly():
    from casinoai.engines.baccarat import BaccaratEngine

    reasons = []
    for seed in range(30):
        oracle = compile_spec(pb_spec())
        engine = BaccaratEngine(seed=seed)
        total = 0.0
        for _ in range(2000):
            action = oracle.next_action()
            if action.stop:
                reasons.append(action.reason)
                break
            total += oracle.observe(engine.deal())
        assert total == pytest.approx(oracle.net_units)
    assert reasons
    assert any("stop-win" in r for r in reasons)
