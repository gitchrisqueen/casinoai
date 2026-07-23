"""Registry of human-translated procedural strategy machines.

Each entry is a reviewed translation of a book's procedural rules that the
generic StrategySpec primitives cannot express. Translations live here as
code so the review surface is git, not the LLM. All classes are pure and
deterministic.

Progression protocol:  stake() -> units, advance(won), .busted (bool)
Selection protocol:    select() -> bet_type | None, observe(outcome, won)
"""


class SuperFibonacciProgression:
    """Super Fibonacci (Silverthorne): 7-step modified-Fibonacci ladder with a
    mandatory parlay after every win and a 5-step Martingale fallback after
    three consecutive losses. Units for a $5 base: 5,8,13,20,35,50,60 and
    5,10,20,40,80.

    Review decisions (draft-v1 ambiguities), 2026-07-22:
    - A parlay loss counts toward the consecutive-loss count (it is a losing
      wager; the book's trigger is 'three consecutive losing wagers').
    - 'Resume one level higher' past the top of the 7-step ladder is undefined
      in the source: capped at level 7. Session bust is handled by the generic
      cannot-cover-next-wager rule, matching the book's own end condition.
    - Any win (fib, parlay, or Martingale) resets the consecutive-loss count.
    """

    FIB = [1.0, 1.6, 2.6, 4.0, 7.0, 10.0, 12.0]
    MART = [1.0, 2.0, 4.0, 8.0, 16.0]

    def __init__(self):
        self.mode = "fib"  # fib | parlay | mart
        self.fib_index = 0
        self.mart_index = 0
        self.consec_losses = 0
        self.parlay_from = 0  # fib index the winning bet was at
        self.parlay_stake = 0.0
        self.busted = False

    def stake(self) -> float:
        if self.mode == "parlay":
            return self.parlay_stake
        if self.mode == "mart":
            return self.MART[self.mart_index]
        return self.FIB[self.fib_index]

    def _cap_fib(self, index: int) -> int:
        return min(index, len(self.FIB) - 1)

    def advance(self, won: bool) -> None:
        if won:
            self.consec_losses = 0
            if self.mode == "fib":
                # mandatory parlay: winnings ride on top of the original stake
                self.parlay_from = self.fib_index
                self.parlay_stake = 2 * self.FIB[self.fib_index]
                self.mode = "parlay"
            elif self.mode == "parlay":
                # successful parlay completes the series
                self.mode = "fib"
                self.fib_index = 0
            else:
                # martingale win: resume fib one level above the last fib loss —
                # fib_index already advanced past that loss when it happened
                self.mode = "fib"
            return
        self.consec_losses += 1
        if self.mode == "parlay":
            self.mode = "fib"
            self.fib_index = self._cap_fib(self.parlay_from + 1)
        elif self.mode == "fib":
            self.fib_index = self._cap_fib(self.fib_index + 1)
        else:  # martingale
            self.mart_index += 1
            if self.mart_index >= len(self.MART):
                self.busted = True
                self.mart_index = len(self.MART) - 1
                return
        if self.mode != "mart" and self.consec_losses >= 3:
            self.mode = "mart"
            self.mart_index = 0


class PowerPivotSelection:
    """Super Fibonacci's bet selection for even-money games. Track the previous
    decision; in Same mode bet it again, in Opposite mode bet its opposite.
    Switch modes after any loss; after three consecutive losses stay in the
    current mode for one extra round before switching again.

    Review decisions:
    - Baccarat ties produce no decision: they neither update the last outcome
      nor count as a win/loss for mode switching (the bet pushes).
    - No bet until one decision (non-tie) has been observed.
    """

    OPPOSITE = {"banker": "player", "player": "banker"}

    def __init__(self):
        self.mode = "same"
        self.last_decision: str | None = None
        self.consec_losses = 0
        self.extension_pending = False

    def select(self) -> str | None:
        if self.last_decision is None:
            return None
        if self.mode == "same":
            return self.last_decision
        return self.OPPOSITE[self.last_decision]

    def observe(self, outcome, won: bool | None) -> None:
        """`won` is None when we had no bet on the round (observation only)."""
        winner = getattr(outcome, "winner", None)
        winner = winner.value if winner is not None else None
        if winner in self.OPPOSITE:
            self.last_decision = winner
        if won is None or winner not in self.OPPOSITE:
            return  # no decision (tie) or no bet: mode state unchanged
        if won:
            self.consec_losses = 0
            self.extension_pending = False
            return
        self.consec_losses += 1
        if self.extension_pending:
            self.extension_pending = False
            self._switch()
        elif self.consec_losses >= 3:
            self.extension_pending = True  # ride one extra round in this mode
        else:
            self._switch()

    def _switch(self) -> None:
        self.mode = "opposite" if self.mode == "same" else "same"


PROGRESSIONS = {
    "super_fibonacci": SuperFibonacciProgression,
}

SELECTIONS = {
    "power_pivot": PowerPivotSelection,
}
