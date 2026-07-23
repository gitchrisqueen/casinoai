"""Formula 57 machine, verified against the book's Example 3 worked table
(Formula 57 Blackjack, Silverthorne 2018, pp. 119-120)."""

import pytest

from casinoai.rules.library import Formula57Progression
from casinoai.rules.oracle import compile_spec
from casinoai.strategies.spec import StrategySpec


def test_book_example_3_pp119_120():
    """18 rounds exercising Foundation, Rapid Recovery, and Profit Participation."""
    m = Formula57Progression()
    # (mode, stake_units, won) — dollars from the book divided by the $5 base
    table = [
        ("f", 1.0, True),  # 1  F1 W -> PP
        ("pp", 1.4, True),  # 2  P $7 W
        ("pp", 1.2, False),  # 3  P $6 L -> F2
        ("f", 1.6, False),  # 4  F2 L
        ("f", 2.6, False),  # 5  F3 L -> 3 consecutive losses -> RR
        ("rr", 1.0, False),  # 6  R1 L
        ("rr", 2.0, False),  # 7  R2 L
        ("rr", 4.0, False),  # 8  R3 L
        ("rr", 8.0, True),  # 9  R4 W -> resume F one above last F bet (L4)
        ("f", 4.2, True),  # 10 F4 W
        ("f", 2.6, True),  # 11 F3 W -> two straight -> series complete
        ("f", 1.0, True),  # 12 F1 W -> PP
        ("pp", 1.4, True),  # 13 P $7 W
        ("pp", 1.2, True),  # 14 P $6 W
        ("pp", 1.6, True),  # 15 P $8 W
        ("pp", 2.0, True),  # 16 P $10 W
        ("pp", 2.4, False),  # 17 P $12 L -> F2
        ("f", 1.6, True),  # 18 F2 W
    ]
    for i, (mode, stake, won) in enumerate(table, 1):
        assert m.mode == mode, f"round {i}: expected {mode}, got {m.mode}"
        assert m.stake() == pytest.approx(stake), f"round {i}"
        m.advance(won)


def test_rapid_recovery_exhaustion_busts():
    m = Formula57Progression()
    for _ in range(3):
        m.advance(False)
    assert m.mode == "rr"
    for _ in range(5):
        m.advance(False)
    assert m.busted


def test_two_of_three_completes_series():
    m = Formula57Progression()
    # L L W L W: rounds 3 and 5 are two wins out of the last three -> reset
    m.advance(False)  # F1 -> F2
    m.advance(False)  # F2 -> F3
    m.advance(True)  # F3 win -> drop to F2 (one win in window)
    assert m.f_index == 1
    m.advance(False)  # F2 -> F3 (window: W, L)
    m.advance(True)  # F3 win -> window W, L, W = two of three -> complete
    assert m.f_index == 0
    assert m.mode == "f"


def f57_spec() -> StrategySpec:
    return StrategySpec.model_validate(
        {
            "name": "Formula 57 Blackjack",
            "game": "blackjack",
            "summary": "Three-mode bet sizing over basic strategy.",
            "bets": [{"bet_type": "hand"}],
            "progression": {
                "kind": "registered",
                "name": "formula_57",
                "description": "Foundation / Rapid Recovery / Profit Participation",
            },
            "bankroll": {
                "unit_size": 5.0,
                "session_bankroll_units": 40.0,
                "stop_loss_units": 40.0,
                "stop_win_units": 10.0,
            },
        }
    )


def test_oracle_plays_blackjack_sessions():
    from casinoai.engines.blackjack import BlackjackEngine

    reasons = []
    for seed in range(30):
        oracle = compile_spec(f57_spec())
        engine = BlackjackEngine(seed=seed)
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
