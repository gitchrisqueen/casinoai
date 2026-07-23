"""Seeded roulette simulator (European / American).

Determinism is sacred: seeded RNG only, no wall-clock, no LLM. Emits typed
outcomes identical in shape to what the live adapter will emit, so agents
cannot distinguish simulation from live play.
"""

import random
from enum import StrEnum
from fractions import Fraction

from pydantic import BaseModel

RED_NUMBERS = frozenset({1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36})


class Wheel(StrEnum):
    EUROPEAN = "european"  # single zero, 37 pockets
    AMERICAN = "american"  # 0 and 00, 38 pockets


class Color(StrEnum):
    RED = "red"
    BLACK = "black"
    GREEN = "green"


class RouletteOutcome(BaseModel):
    """One spin, fully described. `pocket` is '0'..'36' or '00'."""

    pocket: str
    color: Color
    parity: str | None  # even / odd; None for zeros
    dozen: int | None  # 1..3; None for zeros
    column: int | None  # 1..3; None for zeros
    half: str | None  # low (1-18) / high (19-36); None for zeros

    @classmethod
    def from_pocket(cls, pocket: str) -> "RouletteOutcome":
        if pocket in ("0", "00"):
            return cls(
                pocket=pocket, color=Color.GREEN, parity=None, dozen=None, column=None, half=None
            )
        n = int(pocket)
        return cls(
            pocket=pocket,
            color=Color.RED if n in RED_NUMBERS else Color.BLACK,
            parity="even" if n % 2 == 0 else "odd",
            dozen=(n - 1) // 12 + 1,
            column=(n - 1) % 3 + 1,
            half="low" if n <= 18 else "high",
        )


# bet_type -> (win predicate, payout odds as Fraction winnings-per-unit-staked)
def _payout_table() -> dict[str, tuple]:
    table: dict[str, tuple] = {
        "red": (lambda o: o.color == Color.RED, Fraction(1)),
        "black": (lambda o: o.color == Color.BLACK, Fraction(1)),
        "even": (lambda o: o.parity == "even", Fraction(1)),
        "odd": (lambda o: o.parity == "odd", Fraction(1)),
        "low": (lambda o: o.half == "low", Fraction(1)),
        "high": (lambda o: o.half == "high", Fraction(1)),
    }
    for d in (1, 2, 3):
        table[f"dozen_{d}"] = (lambda o, d=d: o.dozen == d, Fraction(2))
        table[f"column_{d}"] = (lambda o, d=d: o.column == d, Fraction(2))
    for n in ["0", "00", *map(str, range(1, 37))]:
        table[f"straight_{n}"] = (lambda o, n=n: o.pocket == n, Fraction(35))
    table["zero"] = table["straight_0"]
    return table


PAYOUTS = _payout_table()


class RouletteEngine:
    """Seeded wheel. Same seed → identical spin sequence, forever."""

    def __init__(self, wheel: Wheel = Wheel.EUROPEAN, seed: int = 0):
        self.wheel = wheel
        self.seed = seed
        self._rng = random.Random(seed)
        self._pockets = [*map(str, range(37))]
        if wheel == Wheel.AMERICAN:
            self._pockets.append("00")
        self.round_index = 0

    def spin(self) -> RouletteOutcome:
        pocket = self._rng.choice(self._pockets)
        self.round_index += 1
        return RouletteOutcome.from_pocket(pocket)

    @staticmethod
    def settle(bet_type: str, stake: float, outcome: RouletteOutcome) -> float:
        """Net result of one bet: +winnings on a win, -stake on a loss."""
        if bet_type not in PAYOUTS:
            raise ValueError(f"Unknown bet type: {bet_type}")
        wins, odds = PAYOUTS[bet_type]
        return float(stake * odds) if wins(outcome) else -stake
