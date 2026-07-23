"""Registered machines: Super Fibonacci progression + Power Pivot selection."""

import pytest

from casinoai.engines.baccarat import BaccaratOutcome, BaccaratWinner
from casinoai.rules.library import PowerPivotSelection, SuperFibonacciProgression
from casinoai.rules.oracle import CompileError, compile_spec
from casinoai.strategies.spec import StrategySpec


def replay(machine, results):
    stakes = []
    for won in results:
        stakes.append(machine.stake())
        machine.advance(won)
    return stakes


def test_fib_ladder_advances_on_losses():
    m = SuperFibonacciProgression()
    # two losses climb the ladder; third consecutive loss switches to Martingale
    assert replay(m, [False, False, False]) == [1.0, 1.6, 2.6]
    assert m.mode == "mart"
    assert m.stake() == 1.0  # martingale starts at base


def test_win_triggers_parlay_and_parlay_win_completes_series():
    m = SuperFibonacciProgression()
    stakes = replay(m, [False, True, True])  # lose, win at 1.6, parlay wins
    assert stakes == [1.0, 1.6, 3.2]  # parlay doubles the winning stake
    assert m.mode == "fib"
    assert m.stake() == 1.0  # series completed, reset


def test_parlay_loss_resumes_one_level_higher():
    m = SuperFibonacciProgression()
    stakes = replay(m, [False, True, False])  # lose, win at 1.6 (idx1), parlay loses
    assert stakes == [1.0, 1.6, 3.2]
    assert m.mode == "fib"
    assert m.stake() == 2.6  # one level above the parlayed bet (idx 2)


def test_martingale_win_resumes_fib_one_level_up():
    m = SuperFibonacciProgression()
    replay(m, [False, False, False])  # into martingale at fib idx 2
    stakes = replay(m, [False, False, True])  # two mart losses then a win
    assert stakes == [1.0, 2.0, 4.0]
    assert m.mode == "fib"
    assert m.stake() == 4.0  # fib idx 3, one above the last fib loss (idx 2)


def test_martingale_exhaustion_busts():
    m = SuperFibonacciProgression()
    replay(m, [False] * 3)  # into martingale
    replay(m, [False] * 5)  # lose all five martingale steps
    assert m.busted


def test_power_pivot_modes():
    sel = PowerPivotSelection()
    banker = BaccaratOutcome(
        winner=BaccaratWinner.BANKER,
        player_total=1,
        banker_total=5,
        player_cards=[1, 0],
        banker_cards=[2, 3],
        natural=False,
    )
    player = banker.model_copy(update={"winner": BaccaratWinner.PLAYER, "player_total": 9})
    tie = banker.model_copy(update={"winner": BaccaratWinner.TIE, "player_total": 5})

    assert sel.select() is None  # nothing observed yet
    sel.observe(banker, None)  # observation round
    assert sel.select() == "banker"  # same mode: repeat last decision
    sel.observe(player, False)  # we bet banker, player won → loss → switch mode
    assert sel.mode == "opposite"
    assert sel.select() == "banker"  # opposite of last decision (player)
    sel.observe(tie, None)  # tie: no decision, no mode change
    assert sel.mode == "opposite"
    assert sel.select() == "banker"


def test_power_pivot_three_loss_extension():
    sel = PowerPivotSelection()
    banker = BaccaratOutcome(
        winner=BaccaratWinner.BANKER,
        player_total=1,
        banker_total=5,
        player_cards=[1, 0],
        banker_cards=[2, 3],
        natural=False,
    )
    sel.observe(banker, None)
    sel.observe(banker, False)  # loss 1 → switch
    sel.observe(banker, False)  # loss 2 → switch
    mode_after_two = sel.mode
    sel.observe(banker, False)  # loss 3 → extension: NO switch this round
    assert sel.mode == mode_after_two
    sel.observe(banker, False)  # loss 4 → extension consumed, switch now
    assert sel.mode != mode_after_two


def superfib_spec() -> StrategySpec:
    return StrategySpec.model_validate(
        {
            "name": "Super Fibonacci",
            "game": "baccarat",
            "summary": "Modified Fibonacci with parlay and Martingale fallback.",
            "bets": [{"bet_type": "player"}, {"bet_type": "banker"}],
            "bet_selection": {
                "kind": "registered",
                "name": "power_pivot",
                "description": "Same/Opposite mode switching",
            },
            "progression": {
                "kind": "registered",
                "name": "super_fibonacci",
                "description": "Fib ladder + parlay + Martingale fallback",
            },
            "bankroll": {"unit_size": 5.0, "session_bankroll_units": 40.0},
        }
    )


def test_oracle_runs_registered_machines_end_to_end():
    from casinoai.engines.baccarat import BaccaratEngine

    oracle = compile_spec(superfib_spec())
    engine = BaccaratEngine(seed=11)
    total = 0.0
    for _ in range(300):
        action = oracle.next_action()
        if action.stop:
            break
        outcome = engine.deal()
        total += oracle.observe(outcome)
    assert total == pytest.approx(oracle.net_units)
    assert oracle.rounds_played > 0


def test_unknown_registered_name_refuses_to_compile():
    spec = superfib_spec()
    spec.progression.name = "does_not_exist"
    with pytest.raises(CompileError, match="not in library"):
        compile_spec(spec)
