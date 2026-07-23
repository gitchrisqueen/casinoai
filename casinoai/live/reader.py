"""Table I/O protocols for live/demo play, and recorded-tape fakes for tests.

A TableReader turns whatever the demo game shows into the SAME typed outcome
the engines emit (RouletteOutcome / BaccaratOutcome), so the oracle cannot tell
live from sim. A BetPlacer drives the demo UI to place bets. Concrete Playwright
bindings live in playwright_adapter.py; the session logic depends only on these
protocols, so it is fully testable without a browser.
"""

from typing import Any, Protocol, runtime_checkable

from casinoai.engines.baccarat import BaccaratOutcome, BaccaratWinner
from casinoai.engines.craps import CrapsOutcome, LineResult
from casinoai.engines.roulette import RouletteOutcome


@runtime_checkable
class TableReader(Protocol):
    def read_next_spin(self) -> Any | None:
        """Block until the current round resolves; return its typed outcome, or
        None if the table is unavailable/closed (the session then ends cleanly)."""
        ...

    def is_demo(self) -> bool:
        """True only if the table is confirmed in demo/free-play mode."""
        ...


def _baccarat_outcome(winner: BaccaratWinner) -> BaccaratOutcome:
    """A minimal BaccaratOutcome carrying only the observed winner — that is all
    the oracle's settle and Tracker selection read. Card totals are placeholders."""
    return BaccaratOutcome(
        winner=winner,
        player_total=0,
        banker_total=0,
        player_cards=[],
        banker_cards=[],
        natural=False,
    )


def _craps_outcome(result: LineResult) -> CrapsOutcome:
    """A minimal CrapsOutcome carrying only the observed line result — all the
    oracle's settle reads. come_out/point/rolls are placeholders (we only see
    the line decision, not the dice)."""
    placeholder = {LineResult.PASS_WIN: 7, LineResult.PASS_LOSE: 2, LineResult.DONT_PUSH: 12}
    co = placeholder[result]
    return CrapsOutcome(result=result, come_out=co, point=None, rolls=[co], seven_out=False)


@runtime_checkable
class BetPlacer(Protocol):
    def place_bets(self, bets: list) -> None:
        """Place the given bets on the demo table (drive the UI)."""
        ...


class RecordedTableReader:
    """Replays a fixed list of pockets — the test/replay double for a live
    table. `pockets` are strings like '0', '00', '17'."""

    def __init__(self, pockets: list[str], is_demo: bool = True):
        self._pockets = list(pockets)
        self._i = 0
        self._is_demo = is_demo

    def read_next_spin(self) -> RouletteOutcome | None:
        if self._i >= len(self._pockets):
            return None
        pocket = self._pockets[self._i]
        self._i += 1
        return RouletteOutcome.from_pocket(pocket)

    def is_demo(self) -> bool:
        return self._is_demo


class NullBetPlacer:
    """Records placed bets without touching any UI (tests / dry runs)."""

    def __init__(self):
        self.placed: list[list] = []

    def place_bets(self, bets: list) -> None:
        self.placed.append(list(bets))


class ManualTableReader:
    """OBSERVER mode: a human plays the real demo table by hand and types in the
    winning pocket after each spin. The most robust, ToS-safe way to collect
    H3b data — no automation touches the casino at all. `read_fn`/`is_demo` are
    injectable so this is testable without real stdin."""

    def __init__(self, read_fn=input, is_demo: bool = True):
        self._read_fn = read_fn
        self._is_demo = is_demo

    def is_demo(self) -> bool:
        return self._is_demo

    def read_next_spin(self) -> RouletteOutcome | None:
        raw = self._read_fn("Winning pocket (blank/q to end session): ")
        if raw is None:
            return None
        raw = raw.strip().lower()
        if raw in ("", "q", "quit", "stop"):
            return None
        try:
            return RouletteOutcome.from_pocket("00" if raw == "00" else str(int(raw)))
        except (ValueError, KeyError):
            print(f"  '{raw}' is not a valid pocket (0-36 or 00); try again.")
            return self.read_next_spin()


_BACC_WORDS = {
    "p": BaccaratWinner.PLAYER,
    "player": BaccaratWinner.PLAYER,
    "b": BaccaratWinner.BANKER,
    "banker": BaccaratWinner.BANKER,
    "t": BaccaratWinner.TIE,
    "tie": BaccaratWinner.TIE,
}


class ManualBaccaratReader:
    """OBSERVER mode for baccarat: the human plays the demo table and types the
    winner (p/b/t) after each coup. Ties push Player/Banker bets, exactly as at
    a real table."""

    def __init__(self, read_fn=input, is_demo: bool = True):
        self._read_fn = read_fn
        self._is_demo = is_demo

    def is_demo(self) -> bool:
        return self._is_demo

    def read_next_spin(self) -> BaccaratOutcome | None:
        raw = self._read_fn("Result — [p]layer / [b]anker / [t]ie (blank/q to end): ")
        if raw is None:
            return None
        raw = raw.strip().lower()
        if raw in ("", "q", "quit", "stop"):
            return None
        winner = _BACC_WORDS.get(raw)
        if winner is None:
            print(f"  '{raw}' is not p/b/t; try again.")
            return self.read_next_spin()
        return _baccarat_outcome(winner)


class RecordedBaccaratReader:
    """Replays a fixed list of winners ('player'/'banker'/'tie') — test double."""

    def __init__(self, winners: list[str], is_demo: bool = True):
        self._winners = list(winners)
        self._i = 0
        self._is_demo = is_demo

    def is_demo(self) -> bool:
        return self._is_demo

    def read_next_spin(self) -> BaccaratOutcome | None:
        if self._i >= len(self._winners):
            return None
        w = self._winners[self._i]
        self._i += 1
        return _baccarat_outcome(BaccaratWinner(w))


_CRAPS_WORDS = {
    "w": LineResult.PASS_WIN,
    "win": LineResult.PASS_WIN,
    "pass": LineResult.PASS_WIN,
    "l": LineResult.PASS_LOSE,
    "lose": LineResult.PASS_LOSE,
    "loss": LineResult.PASS_LOSE,
    "seven": LineResult.PASS_LOSE,
    "7out": LineResult.PASS_LOSE,
    "push": LineResult.DONT_PUSH,
    "12": LineResult.DONT_PUSH,
    "bar": LineResult.DONT_PUSH,
}


class ManualCrapsReader:
    """OBSERVER mode for craps: the human watches each pass-line coup resolve and
    types the line result — [w]in / [l]ose / [push] (come-out 12, a don't-pass
    push). One coup = one betting round, matching the engine."""

    def __init__(self, read_fn=input, is_demo: bool = True):
        self._read_fn = read_fn
        self._is_demo = is_demo

    def is_demo(self) -> bool:
        return self._is_demo

    def read_next_spin(self) -> CrapsOutcome | None:
        raw = self._read_fn("Line result — [w]in / [l]ose / [push] come-out 12 (blank/q to end): ")
        if raw is None:
            return None
        raw = raw.strip().lower()
        if raw in ("", "q", "quit", "stop"):
            return None
        result = _CRAPS_WORDS.get(raw)
        if result is None:
            print(f"  '{raw}' is not win/lose/push; try again.")
            return self.read_next_spin()
        return _craps_outcome(result)


class RecordedCrapsReader:
    """Replays a fixed list of line results ('pass_win'/'pass_lose'/'dont_push')."""

    def __init__(self, results: list[str], is_demo: bool = True):
        self._results = list(results)
        self._i = 0
        self._is_demo = is_demo

    def is_demo(self) -> bool:
        return self._is_demo

    def read_next_spin(self) -> CrapsOutcome | None:
        if self._i >= len(self._results):
            return None
        r = self._results[self._i]
        self._i += 1
        return _craps_outcome(LineResult(r))
