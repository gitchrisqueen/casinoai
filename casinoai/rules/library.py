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


class MiniMaxProgression:
    """Mini-Max Roulette (Silverthorne 2018): three chip stacks A/B/C, each
    starting at one Base Bet. Always wager the entire leftmost non-empty stack.
    On a win the stake returns to its stack and the winnings go to the leftmost
    EMPTY spot if any (replenish), otherwise cycle B → C → A. Winning any single
    wager of 4+ units (the Pivot Bet) completes the game. Losing all three
    stacks loses the Betting Group; a game allows exactly two groups.

    Review decisions (draft-v1 ambiguities), 2026-07-22:
    - Buy-in: the book says both 'nine-unit buy-in' (three groups) and 'never
      risk more than two Betting Groups' with $60/two-group buy-in in the rules
      summary. Modeled per the summary: max exposure 6 units per game. The
      9-unit figure belongs to the optional zero-hedge (BPS) variant, which has
      no complete procedure in the text and is not modeled.
    - The 4-unit special Loss Limit and the two-group cap BOTH apply (the book
      states them side by side): session stops at net -4u or two lost groups,
      whichever first.
    - The winnings-placement cycle pointer only advances on a cycle placement,
      not when winnings replenish an empty spot (matches the worked example).
    - A new group starts the placement cycle back at Spot B.
    """

    def __init__(self):
        self.stacks = [1.0, 1.0, 1.0]
        self.group = 1
        self._cycle = [1, 2, 0]  # B, C, A
        self._cycle_pos = 0
        self.busted = False
        self.complete_reason: str | None = None

    def _leftmost(self) -> int:
        for i, chips in enumerate(self.stacks):
            if chips > 0:
                return i
        raise RuntimeError("all stacks empty — advance() should have handled this")

    def stake(self) -> float:
        return self.stacks[self._leftmost()]

    def advance(self, won: bool) -> None:
        i = self._leftmost()
        amount = self.stacks[i]
        if won:
            empties = [j for j, chips in enumerate(self.stacks) if chips == 0]
            if empties:
                self.stacks[empties[0]] += amount  # replenish leftmost empty
            else:
                target = self._cycle[self._cycle_pos]
                self.stacks[target] += amount
                self._cycle_pos = (self._cycle_pos + 1) % 3
            if amount >= 4.0:
                self.complete_reason = f"pivot bet won ({amount:g} units)"
            return
        self.stacks[i] = 0.0
        if not any(self.stacks):
            if self.group == 1:
                self.group = 2
                self.stacks = [1.0, 1.0, 1.0]
                self._cycle_pos = 0
            else:
                self.busted = True


class IABSelection:
    """Mini-Max's Intelligent Adaptive Betting for red/black. Mode S bets the
    previous decision; after two consecutive losing bets switch to S2 (bet the
    second-preceding decision); after two more consecutive losses switch back.
    Zeros are ignored in the decision history but their lost bets count toward
    the consecutive-loss switch (they are losing bets per the text).

    Review decisions:
    - No bet until one decision is observed (land-based rule; the online
      'default to Red' shortcut is not modeled).
    - A win resets the consecutive-loss count; switching modes resets it too
      (per Example 1: losses at rows 8-9 switch back at row 10).
    """

    def __init__(self):
        self.mode = "S"
        self.decisions: list[str] = []
        self.consec_losses = 0

    def select(self) -> str | None:
        if self.mode == "S":
            return self.decisions[-1] if self.decisions else None
        return self.decisions[-2] if len(self.decisions) >= 2 else None

    def observe(self, outcome, won: bool | None) -> None:
        color = getattr(outcome, "color", None)
        color = color.value if color is not None else None
        if color in ("red", "black"):
            self.decisions.append(color)
        if won is None:
            return
        if won:
            self.consec_losses = 0
            return
        self.consec_losses += 1
        if self.consec_losses >= 2:
            self.mode = "S2" if self.mode == "S" else "S"
            self.consec_losses = 0


class PowerBaccaratProgression:
    """Power Baccarat (LaMarca 2015): three betting modes. Strike (default)
    ladder 1,2,3,5,8,13,21,34 units — up one on loss, down one on win, reset to
    L1 after two wins in a row or two of the last three strike bets. Two
    consecutive strike losses enter Counterstrike (0.6,1,2,4,8,16,32 — pure
    Martingale); any CS win resumes Strike one level above the last strike bet;
    losing all seven CS bets loses the game. Winning a Level-1 strike bet
    enters Trend (1.2, 1, 1.6, 2, 2.4, 2.8, 3.2, then +0.6 per win); any trend
    loss resumes Strike at the lowest level whose stake strictly exceeds the
    lost trend stake. Verified against the book's 14-round worked table (p.65).

    Review decisions (draft-v1 ambiguities), 2026-07-22:
    - Strike losses at the top (L8): no L9 exists; stay at L8 (the next loss is
      the second consecutive and enters Counterstrike anyway).
    - CS resume 'one level above the last strike bet' is capped at L8.
    - The two-of-three strike-win window only counts strike-mode results and
      clears on any mode change.
    - Trend Level-1 entry takes precedence over the win-reset rule when a
      Level-1 strike bet wins (the book states it as an unconditional signal).
    """

    STRIKE = [1.0, 2.0, 3.0, 5.0, 8.0, 13.0, 21.0, 34.0]
    COUNTER = [0.6, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0]
    TREND = [1.2, 1.0, 1.6, 2.0, 2.4, 2.8, 3.2]

    def __init__(self):
        self.mode = "strike"
        self.strike_index = 0
        self.counter_index = 0
        self.trend_index = 0
        self.strike_window: list[bool] = []  # recent strike results, max 3
        self.strike_consec_losses = 0
        self.last_strike_index = 0
        self.busted = False

    def stake(self) -> float:
        if self.mode == "strike":
            return self.STRIKE[self.strike_index]
        if self.mode == "counter":
            return self.COUNTER[self.counter_index]
        if self.trend_index < len(self.TREND):
            return self.TREND[self.trend_index]
        return self.TREND[-1] + 0.6 * (self.trend_index - len(self.TREND) + 1)

    def _enter_strike(self, index: int) -> None:
        self.mode = "strike"
        self.strike_index = min(index, len(self.STRIKE) - 1)
        self.strike_window = []
        self.strike_consec_losses = 0

    def advance(self, won: bool) -> None:
        if self.mode == "strike":
            self.last_strike_index = self.strike_index
            self.strike_window = (self.strike_window + [won])[-3:]
            if won:
                self.strike_consec_losses = 0
                if self.strike_index == 0:
                    self.mode = "trend"
                    self.trend_index = 0
                    self.strike_window = []
                elif sum(self.strike_window) >= 2:  # two in a row or two of three
                    self.strike_index = 0
                else:
                    self.strike_index = max(0, self.strike_index - 1)
            else:
                self.strike_consec_losses += 1
                if self.strike_consec_losses >= 2:
                    self.mode = "counter"
                    self.counter_index = 0
                    self.strike_window = []
                else:
                    self.strike_index = min(self.strike_index + 1, len(self.STRIKE) - 1)
            return
        if self.mode == "counter":
            if won:
                self._enter_strike(self.last_strike_index + 1)
            else:
                self.counter_index += 1
                if self.counter_index >= len(self.COUNTER):
                    self.busted = True
                    self.counter_index = len(self.COUNTER) - 1
            return
        # trend
        if won:
            self.trend_index += 1
        else:
            lost = self.stake()
            resume = next((i for i, s in enumerate(self.STRIKE) if s > lost), len(self.STRIKE) - 1)
            self._enter_strike(resume)


class TrackerSelection:
    """Power Baccarat's Target/Tracker selection: alternate S (bet the last
    decision) and O (bet its opposite) every round regardless of results; after
    two consecutive losing bets, repeat the last letter for exactly one bet,
    then restart the alternation at S. Ties are not decisions: they push the
    bet and change nothing.

    Review decisions:
    - After the one-bet repeat, the consecutive-loss count restarts (the book:
      'win or lose your next bet will be on S'), so a lost repeat cannot
      immediately trigger another repeat.
    - No bet until one Player/Banker decision has been observed.
    """

    OPPOSITE = {"banker": "player", "player": "banker"}

    def __init__(self):
        self.last_decision: str | None = None
        self.pos = 0  # index into the infinite S,O,S,O... alternation
        self.repeating = False
        self.last_letter = "S"
        self.consec_losses = 0

    def _letter(self) -> str:
        if self.repeating:
            return self.last_letter
        return "S" if self.pos % 2 == 0 else "O"

    def select(self) -> str | None:
        if self.last_decision is None:
            return None
        letter = self._letter()
        return self.last_decision if letter == "S" else self.OPPOSITE[self.last_decision]

    def observe(self, outcome, won: bool | None) -> None:
        winner = getattr(outcome, "winner", None)
        winner = winner.value if winner is not None else None
        played = self._letter() if won is not None else None
        if winner in self.OPPOSITE:
            self.last_decision = winner
        if won is None:
            return  # no bet, or a push (tie): nothing advances
        if self.repeating:
            self.repeating = False
            self.pos = 0  # restart alternation at S
            self.consec_losses = 0
            return
        self.last_letter = played
        self.pos += 1
        if won:
            self.consec_losses = 0
        else:
            self.consec_losses += 1
            if self.consec_losses >= 2:
                self.repeating = True
                self.consec_losses = 0


PROGRESSIONS = {
    "super_fibonacci": SuperFibonacciProgression,
    "mini_max": MiniMaxProgression,
    "power_baccarat": PowerBaccaratProgression,
}

SELECTIONS = {
    "power_pivot": PowerPivotSelection,
    "iab": IABSelection,
    "tracker": TrackerSelection,
}
