"""Mini-Max machines, verified against the book's own worked examples
(Mini-Max Roulette, Silverthorne 2018, pp. 69-76)."""

import pytest

from casinoai.engines.roulette import RouletteOutcome
from casinoai.rules.library import IABSelection, MiniMaxProgression
from casinoai.rules.oracle import compile_spec
from casinoai.strategies.spec import StrategySpec

RED, BLACK, ZERO = "1", "2", "0"  # pockets


def test_book_worked_example_pp70_73():
    """W W W W W L W: stacks 10/20/10 → ... → pivot win at the 4-unit wager."""
    m = MiniMaxProgression()
    expected = [
        (True, [1, 2, 1]),  # win A(1) → winnings to B
        (True, [1, 2, 2]),  # win A(1) → C
        (True, [2, 2, 2]),  # win A(1) → A
        (True, [2, 4, 2]),  # win A(2) → B
        (True, [2, 4, 4]),  # win A(2) → C
        (False, [0, 4, 4]),  # lose A(2)
        (True, [4, 4, 4]),  # win B(4) → replenish empty A; 4u wager = pivot
    ]
    stakes = []
    for won, stacks_after in expected:
        stakes.append(m.stake())
        m.advance(won)
        assert m.stacks == stacks_after
    assert stakes == [1, 1, 1, 2, 2, 2, 4]
    assert m.complete_reason is not None  # pivot bet won
    # book: group totals 12 units vs 3 to start = +9 net
    assert sum(m.stacks) - 3 == 9


def test_two_lost_groups_bust():
    m = MiniMaxProgression()
    for _ in range(3):
        m.advance(False)
    assert m.group == 2
    assert m.stacks == [1.0, 1.0, 1.0]
    assert not m.busted
    for _ in range(3):
        m.advance(False)
    assert m.busted


def test_iab_book_example_1_pp66_67():
    """Replay the book's Example 1 table exactly."""
    sel = IABSelection()
    # (observed decision, expected bet BEFORE observing it; None = observe only)
    table = [
        ("black", None),
        ("red", "black"),
        ("black", "red"),
        ("red", "red"),
        ("red", "black"),
        ("red", "red"),
        ("red", "red"),
        ("black", "red"),
        ("black", "red"),
        ("black", "black"),
    ]
    for observed, expected_bet in table:
        bet = sel.select()
        assert bet == expected_bet
        pocket = RED if observed == "red" else BLACK
        won = None if bet is None else (bet == observed)
        sel.observe(RouletteOutcome.from_pocket(pocket), won)


def test_iab_zero_ignored_in_history_but_counts_as_loss():
    sel = IABSelection()
    sel.observe(RouletteOutcome.from_pocket(BLACK), None)
    assert sel.select() == "black"
    sel.observe(RouletteOutcome.from_pocket(ZERO), False)  # zero: bet lost
    assert sel.select() == "black"  # decision history unchanged
    assert sel.consec_losses == 1  # but the loss counted
    sel.observe(RouletteOutcome.from_pocket(ZERO), False)
    assert sel.mode == "S2"  # two consecutive losses switch the mode


def minimax_spec() -> StrategySpec:
    return StrategySpec.model_validate(
        {
            "name": "Mini-Max Roulette",
            "game": "roulette",
            "summary": "IAB red/black selection with chip-stack bet sizing.",
            "bets": [{"bet_type": "red"}, {"bet_type": "black"}],
            "bet_selection": {"kind": "registered", "name": "iab", "description": "IAB S/S2"},
            "progression": {
                "kind": "registered",
                "name": "mini_max",
                "description": "A/B/C stacks",
            },
            "bankroll": {"unit_size": 10.0, "session_bankroll_units": 6.0, "stop_loss_units": 4.0},
        }
    )


def test_oracle_session_ends_by_pivot_loss_limit_or_bust():
    from casinoai.engines.roulette import RouletteEngine

    reasons = []
    for seed in range(40):
        oracle = compile_spec(minimax_spec())
        engine = RouletteEngine(seed=seed)
        total = 0.0
        for _ in range(500):
            action = oracle.next_action()
            if action.stop:
                reasons.append(action.reason)
                break
            total += oracle.observe(engine.spin())
        assert total == pytest.approx(oracle.net_units)
    assert reasons  # every session ends
    assert any("pivot" in r for r in reasons)
    assert all(
        "pivot" in r or "stop-loss" in r or "series lost" in r or "cannot cover" in r
        for r in reasons
    )
