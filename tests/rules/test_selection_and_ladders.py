"""New oracle primitives: follow-lag bet selection, win-retreat ladders, bust-out."""

import pytest

from casinoai.engines.roulette import RouletteOutcome
from casinoai.rules.oracle import CompileError, compile_spec
from casinoai.strategies.spec import StrategySpec

POWER_PRO_LADDER = {
    "kind": "ladder",
    "steps": [{"stake_units": u} for u in (1.0, 1.2, 1.6, 2.4, 4.0, 6.0, 9.0, 13.0, 20.0)],
    "advance_on": "loss",
    "win_retreat_map": [
        {"from_step": 1, "to_step": 6, "go_to": 1},
        {"from_step": 7, "to_step": 8, "go_to": 2},
        {"from_step": 9, "to_step": 9, "go_to": 3},
    ],
    "bust_at_end": True,
}


def dozens_spec(**overrides) -> StrategySpec:
    base = {
        "name": "Follow Dozens",
        "game": "roulette",
        "summary": "Bet the dozen from two non-zero spins back.",
        "bets": [{"bet_type": "dozen_1"}, {"bet_type": "dozen_2"}, {"bet_type": "dozen_3"}],
        "bet_selection": {"kind": "follow_lag", "attribute": "dozen", "lag": 2},
        "progression": POWER_PRO_LADDER,
    }
    base.update(overrides)
    return StrategySpec.model_validate(base)


def o(pocket: str) -> RouletteOutcome:
    return RouletteOutcome.from_pocket(pocket)


def test_no_bet_until_two_qualifying_outcomes():
    oracle = compile_spec(dozens_spec())
    assert oracle.next_action().bets == []
    oracle.observe(o("5"))  # dozen 1
    assert oracle.next_action().bets == []
    oracle.observe(o("0"))  # zero: skipped in history
    assert oracle.next_action().bets == []
    oracle.observe(o("20"))  # dozen 2
    action = oracle.next_action()
    assert [b.bet_type for b in action.bets] == ["dozen_1"]  # 2 qualifying back = pocket 5


def test_selection_tracks_lagged_dozen():
    oracle = compile_spec(dozens_spec())
    for pocket in ("5", "20"):
        oracle.next_action()
        oracle.observe(o(pocket))
    oracle.next_action()
    oracle.observe(o("30"))  # dozen 3; history now [1, 2, 3]
    action = oracle.next_action()
    assert [b.bet_type for b in action.bets] == ["dozen_2"]  # lag 2 → the 20


def test_win_retreat_map():
    spec = dozens_spec(bet_selection={"kind": "fixed"}, bets=[{"bet_type": "dozen_1"}])
    oracle = compile_spec(spec)
    stakes = []
    # six losses climb to step 7 (stake 9), then a win at step 7 → go_to 2
    for pocket in ("13", "13", "13", "13", "13", "13"):  # dozen_2: our dozen_1 loses
        stakes.append(oracle.next_action().bets[0].stake_units)
        oracle.observe(o(pocket))
    stakes.append(oracle.next_action().bets[0].stake_units)
    oracle.observe(o("5"))  # dozen_1 wins at step 7
    stakes.append(oracle.next_action().bets[0].stake_units)
    assert stakes == [1.0, 1.2, 1.6, 2.4, 4.0, 6.0, 9.0, 1.2]  # ends at step 2


def test_bust_at_end_stops_session():
    spec = dozens_spec(bet_selection={"kind": "fixed"}, bets=[{"bet_type": "dozen_1"}])
    oracle = compile_spec(spec)
    for _ in range(9):  # lose all nine steps
        assert not oracle.next_action().stop
        oracle.observe(o("13"))
    action = oracle.next_action()
    assert action.stop
    assert "series lost" in action.reason


def test_max_rounds_stops_session():
    spec = dozens_spec(
        bet_selection={"kind": "fixed"},
        bets=[{"bet_type": "dozen_1"}],
        progression={"kind": "flat", "units": 1.0},
        bankroll={"max_rounds": 3},
    )
    oracle = compile_spec(spec)
    for _ in range(3):
        assert not oracle.next_action().stop
        oracle.observe(o("13"))
    action = oracle.next_action()
    assert action.stop
    assert "max rounds" in action.reason


def test_custom_selection_refuses_to_compile():
    spec = dozens_spec(bet_selection={"kind": "custom", "description": "follow gut feeling"})
    with pytest.raises(CompileError, match="custom bet selection"):
        compile_spec(spec)
