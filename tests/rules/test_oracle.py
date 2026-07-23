"""Oracle tests: progression math, entry conditions, stops, and invariants."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from casinoai.engines.roulette import RouletteEngine, RouletteOutcome
from casinoai.rules.oracle import CompileError, compile_spec
from casinoai.strategies.spec import StrategySpec


def martingale_spec(**overrides) -> StrategySpec:
    base = {
        "name": "Martingale Red",
        "game": "roulette",
        "summary": "Bet red, double on loss.",
        "bets": [{"bet_type": "red"}],
        "progression": {"kind": "multiplier", "factor": 2.0, "on": "loss"},
        "bankroll": {"stop_loss_units": 63, "stop_win_units": 20},
    }
    base.update(overrides)
    return StrategySpec.model_validate(base)


def outcome(pocket: str) -> RouletteOutcome:
    return RouletteOutcome.from_pocket(pocket)


RED, BLACK = "1", "2"  # pocket 1 is red, pocket 2 is black


def test_martingale_doubles_on_loss_resets_on_win():
    oracle = compile_spec(martingale_spec())
    stakes = []
    for pocket in (BLACK, BLACK, BLACK, RED, BLACK):
        action = oracle.next_action()
        stakes.append(action.bets[0].stake_units)
        oracle.observe(outcome(pocket))
    assert stakes == [1, 2, 4, 8, 1]


def test_stop_loss_halts_session():
    oracle = compile_spec(martingale_spec(bankroll={"stop_loss_units": 7}))
    for _ in range(3):  # 1+2+4 = 7 units lost
        assert not oracle.next_action().stop
        oracle.observe(outcome(BLACK))
    action = oracle.next_action()
    assert action.stop
    assert "stop-loss" in action.reason
    # stopped stays stopped
    assert oracle.next_action().stop


def test_stop_win_halts_session():
    oracle = compile_spec(martingale_spec(bankroll={"stop_win_units": 2}))
    oracle.next_action()
    oracle.observe(outcome(RED))
    oracle.next_action()
    oracle.observe(outcome(RED))
    action = oracle.next_action()
    assert action.stop
    assert "stop-win" in action.reason


def test_streak_entry_condition_gates_betting():
    spec = martingale_spec(entry_conditions=[{"kind": "streak", "outcome": "black", "count": 2}])
    oracle = compile_spec(spec)
    assert oracle.next_action().bets == []  # no history yet
    oracle.observe(outcome(BLACK))
    assert oracle.next_action().bets == []  # streak of 1
    oracle.observe(outcome(BLACK))
    assert len(oracle.next_action().bets) == 1  # streak of 2 → bet


def test_max_bet_clamps_progression():
    spec = martingale_spec(bankroll={"max_bet_units": 4, "stop_loss_units": 1000})
    oracle = compile_spec(spec)
    for _ in range(6):
        action = oracle.next_action()
        assert action.bets[0].stake_units <= 4
        oracle.observe(outcome(BLACK))


def test_fibonacci_progression():
    spec = martingale_spec(progression={"kind": "fibonacci", "on": "loss", "step_back_on_win": 2})
    oracle = compile_spec(spec)
    stakes = []
    for pocket in (BLACK, BLACK, BLACK, BLACK, RED, BLACK):
        stakes.append(oracle.next_action().bets[0].stake_units)
        oracle.observe(outcome(pocket))
    # fib: 1,1,2,3,5 → win steps back 2 → 2
    assert stakes == [1, 1, 2, 3, 5, 2]


def test_ladder_progression_resets_at_top():
    spec = martingale_spec(
        progression={
            "kind": "ladder",
            "steps": [{"stake_units": 1}, {"stake_units": 3}, {"stake_units": 5}],
            "advance_on": "loss",
            "reset_at_end": True,
        }
    )
    oracle = compile_spec(spec)
    stakes = []
    for _ in range(5):
        stakes.append(oracle.next_action().bets[0].stake_units)
        oracle.observe(outcome(BLACK))
    assert stakes == [1, 3, 5, 1, 3]


def test_unapproved_ambiguous_spec_refuses_to_compile():
    spec = martingale_spec(ambiguities=["What happens at the table max?"])
    with pytest.raises(CompileError, match="unresolved ambiguities"):
        compile_spec(spec)


def test_custom_condition_refuses_to_compile():
    spec = martingale_spec(
        entry_conditions=[{"kind": "custom", "description": "when the wheel feels hot"}]
    )
    with pytest.raises(CompileError, match="custom condition"):
        compile_spec(spec)


@settings(deadline=None, max_examples=25)
@given(seed=st.integers(min_value=0, max_value=10_000))
def test_session_invariants_over_random_seeds(seed):
    """Whole-session invariants: accounting exact, stops respected, stakes positive."""
    engine = RouletteEngine(seed=seed)
    oracle = compile_spec(martingale_spec())
    total = 0.0
    for _ in range(500):
        action = oracle.next_action()
        if action.stop:
            break
        spun = engine.spin()
        net = oracle.observe(spun)
        total += net
        for bet in action.bets:
            assert bet.stake_units > 0
    assert total == pytest.approx(oracle.net_units)
    if oracle.stopped and "stop-loss" in oracle.stopped:
        assert oracle.net_units <= -63
    if oracle.stopped and "stop-win" in oracle.stopped:
        assert oracle.net_units >= 20
