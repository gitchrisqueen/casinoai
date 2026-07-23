"""Compiles a StrategySpec into the deterministic oracle (ground truth for H2).

Pure state machine: no LLM, no RNG, no wall-clock. A spec that cannot be
compiled deterministically (custom conditions, missing rules) raises
CompileError — that's the review gate doing its job, not a bug.

Protocol per round:
    action = oracle.next_action()      # bets for the coming round (or stop)
    outcome = engine.spin()/deal()
    oracle.observe(outcome)            # settles bets, advances progression
"""

from typing import Any

from pydantic import BaseModel, Field

from casinoai.engines.baccarat import BaccaratEngine, BaccaratOutcome
from casinoai.engines.roulette import RouletteEngine, RouletteOutcome
from casinoai.strategies.spec import (
    FibonacciProgression,
    FlatProgression,
    GameType,
    LadderProgression,
    MultiplierProgression,
    StrategySpec,
    StreakCondition,
)


class CompileError(Exception):
    """The spec has parts no deterministic oracle can execute — needs review."""


class PlacedBet(BaseModel):
    bet_type: str
    stake_units: float


class Action(BaseModel):
    bets: list[PlacedBet] = Field(default_factory=list)
    stop: bool = False
    reason: str | None = None


def _outcome_matches(game: GameType, outcome: Any, token: str) -> bool:
    """Does this round's outcome count as `token` (e.g. 'red', 'banker')?"""
    if game == GameType.ROULETTE:
        o: RouletteOutcome = outcome
        return token in (o.color.value, o.parity, o.half, o.pocket) or token in (
            f"dozen_{o.dozen}",
            f"column_{o.column}",
        )
    if game == GameType.BACCARAT:
        b: BaccaratOutcome = outcome
        return b.winner.value == token
    raise CompileError(f"Outcome matching not implemented for {game}")


_SETTLERS = {
    GameType.ROULETTE: RouletteEngine.settle,
    GameType.BACCARAT: BaccaratEngine.settle,
}


class _ProgressionState:
    """Stake ladder for any supported progression kind."""

    def __init__(self, progression):
        self.p = progression
        self.index = 0
        self._fib = [1.0, 1.0]

    def stake(self) -> float:
        p = self.p
        if isinstance(p, FlatProgression):
            return p.units
        if isinstance(p, MultiplierProgression):
            return float(p.factor**self.index)
        if isinstance(p, FibonacciProgression):
            while len(self._fib) <= self.index:
                self._fib.append(self._fib[-1] + self._fib[-2])
            return self._fib[self.index]
        if isinstance(p, LadderProgression):
            return p.steps[self.index].stake_units
        raise CompileError(f"Unknown progression: {p}")

    def advance(self, won: bool) -> None:
        p = self.p
        if isinstance(p, FlatProgression):
            return
        if isinstance(p, MultiplierProgression):
            trigger = (p.on == "loss") != won  # lost and on-loss, or won and on-win
            if trigger:
                self.index += 1
                if p.reset_after_steps is not None and self.index >= p.reset_after_steps:
                    self.index = 0
            else:
                self.index = 0
            return
        if isinstance(p, FibonacciProgression):
            trigger = (p.on == "loss") != won
            if trigger:
                self.index += 1
            else:
                self.index = max(0, self.index - p.step_back_on_win)
            return
        if isinstance(p, LadderProgression):
            trigger = (p.advance_on == "loss") != won
            if trigger:
                self.index += 1
                if self.index >= len(p.steps):
                    self.index = 0 if p.reset_at_end else len(p.steps) - 1
            else:
                self.index = max(0, self.index - p.retreat_steps)
            return


class Oracle:
    def __init__(self, spec: StrategySpec):
        _validate_compilable(spec)
        self.spec = spec
        self.settle = _SETTLERS[spec.game]
        self.progression = _ProgressionState(spec.progression)
        self.outcomes: list[Any] = []
        self.net_units = 0.0
        self.rounds_played = 0
        self.stopped: str | None = None
        self._pending: list[PlacedBet] = []

    # -- decision --------------------------------------------------------------

    def next_action(self) -> Action:
        if self.stopped:
            return Action(stop=True, reason=self.stopped)
        stop = self._stop_reason()
        if stop:
            self.stopped = stop
            return Action(stop=True, reason=stop)
        if not self._entry_met():
            self._pending = []
            return Action(bets=[])
        stake = self.progression.stake()
        max_bet = self.spec.bankroll.max_bet_units
        if max_bet is not None:
            stake = min(stake, max_bet)
        self._pending = [PlacedBet(bet_type=b.bet_type, stake_units=stake) for b in self.spec.bets]
        return Action(bets=list(self._pending))

    def observe(self, outcome: Any) -> float:
        """Settle the pending action against the outcome; returns net units."""
        net = sum(self.settle(bet.bet_type, bet.stake_units, outcome) for bet in self._pending)
        if self._pending:
            self.rounds_played += 1
            self.net_units += net
            won = net > 0
            self.progression.advance(won)
        self.outcomes.append(outcome)
        self._pending = []
        return net

    # -- internals -------------------------------------------------------------

    def _entry_met(self) -> bool:
        conditions = self.spec.entry_conditions
        if not conditions:
            return True
        for cond in conditions:
            if isinstance(cond, StreakCondition):
                if len(self.outcomes) < cond.count:
                    return False
                recent = self.outcomes[-cond.count :]
                if not all(_outcome_matches(self.spec.game, o, cond.outcome) for o in recent):
                    return False
            # AlwaysCondition: no constraint
        return True

    def _stop_reason(self) -> str | None:
        bk = self.spec.bankroll
        if bk.stop_loss_units is not None and self.net_units <= -bk.stop_loss_units:
            return f"stop-loss hit ({self.net_units:+.1f} units)"
        if bk.stop_win_units is not None and self.net_units >= bk.stop_win_units:
            return f"stop-win hit ({self.net_units:+.1f} units)"
        if bk.session_bankroll_units is not None and self.net_units <= -bk.session_bankroll_units:
            return f"session bankroll exhausted ({self.net_units:+.1f} units)"
        return None


def _validate_compilable(spec: StrategySpec) -> None:
    problems = []
    if spec.game not in _SETTLERS:
        problems.append(f"no engine for game {spec.game}")
    for cond in spec.entry_conditions:
        if getattr(cond, "kind", None) == "custom":
            problems.append(f"custom condition needs human translation: {cond.description}")
    if spec.progression.kind == "custom":
        problems.append(
            f"custom progression needs human translation: {spec.progression.description}"
        )
    if not spec.bets:
        problems.append("spec has no bets")
    if spec.ambiguities and spec.approval is None:
        problems.append(f"{len(spec.ambiguities)} unresolved ambiguities and no human approval")
    if problems:
        raise CompileError("; ".join(problems))


def compile_spec(spec: StrategySpec) -> Oracle:
    return Oracle(spec)
