"""Seeded craps simulator (pass line / don't pass line resolutions).

Determinism is sacred: seeded RNG only, no wall-clock, no LLM. A single
betting round is one full line "coup" — come-out roll through resolution
(a decision on the point) — because that is the unit the betting systems
wager on. Emits a typed outcome identical in shape to what the live adapter
will emit, so agents cannot distinguish simulation from live play.

Bets modeled (even-money line bets — the ones the CasinoAI strategies use):
- pass_line: win on come-out 7/11, lose on 2/3/12; else make the point.
  Win if the point repeats before a 7.
- dont_pass: mirror; come-out 2/3 win, 7/11 lose, 12 is a push (bar 12).
  After a point, win if a 7 comes before the point.
"""

import random
from enum import StrEnum

from pydantic import BaseModel


class LineResult(StrEnum):
    PASS_WIN = "pass_win"  # pass line wins (dont pass loses)
    PASS_LOSE = "pass_lose"  # pass line loses (dont pass wins, except bar)
    DONT_PUSH = "dont_push"  # come-out 12: pass loses, dont pass pushes


class CrapsOutcome(BaseModel):
    """One resolved line coup."""

    result: LineResult
    come_out: int  # the come-out roll (2..12)
    point: int | None  # the established point, or None if resolved on come-out
    rolls: list[int]  # every dice total rolled this coup, come-out first
    seven_out: bool  # True if resolved by a 7 after a point


class CrapsEngine:
    """Seeded two-dice shooter. Same seed → identical roll sequence, forever."""

    def __init__(self, seed: int = 0):
        self.seed = seed
        self._rng = random.Random(seed)
        self.round_index = 0

    def _roll(self) -> int:
        return self._rng.randint(1, 6) + self._rng.randint(1, 6)

    def play_coup(self) -> CrapsOutcome:
        """Play one line decision from come-out to resolution."""
        self.round_index += 1
        come_out = self._roll()
        rolls = [come_out]

        if come_out in (7, 11):
            return CrapsOutcome(
                result=LineResult.PASS_WIN,
                come_out=come_out,
                point=None,
                rolls=rolls,
                seven_out=False,
            )
        if come_out in (2, 3):
            return CrapsOutcome(
                result=LineResult.PASS_LOSE,
                come_out=come_out,
                point=None,
                rolls=rolls,
                seven_out=False,
            )
        if come_out == 12:
            return CrapsOutcome(
                result=LineResult.DONT_PUSH,
                come_out=come_out,
                point=None,
                rolls=rolls,
                seven_out=False,
            )

        # a point is established (4,5,6,8,9,10): roll until point or 7
        point = come_out
        while True:
            roll = self._roll()
            rolls.append(roll)
            if roll == point:
                return CrapsOutcome(
                    result=LineResult.PASS_WIN,
                    come_out=come_out,
                    point=point,
                    rolls=rolls,
                    seven_out=False,
                )
            if roll == 7:
                return CrapsOutcome(
                    result=LineResult.PASS_LOSE,
                    come_out=come_out,
                    point=point,
                    rolls=rolls,
                    seven_out=True,
                )

    # keep the engine-factory play_round(engine) convention working
    def deal(self) -> CrapsOutcome:
        return self.play_coup()

    @staticmethod
    def settle(bet_type: str, stake: float, outcome: CrapsOutcome) -> float:
        """Even-money line bets. Bar-12 makes dont_pass a push on come-out 12."""
        if bet_type in ("pass_line", "pass"):
            return stake if outcome.result == LineResult.PASS_WIN else -stake
        if bet_type in ("dont_pass", "dont_pass_line", "dont"):
            if outcome.result == LineResult.DONT_PUSH:
                return 0.0
            return stake if outcome.result == LineResult.PASS_LOSE else -stake
        raise ValueError(f"Unknown bet type: {bet_type}")
