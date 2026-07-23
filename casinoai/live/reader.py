"""Table I/O protocols for live/demo play, and a recorded-tape fake for tests.

A TableReader turns whatever the demo game shows into the SAME typed outcome
the engines emit (RouletteOutcome), so the oracle cannot tell live from sim.
A BetPlacer drives the demo UI to place bets. Concrete Playwright bindings
live in playwright_adapter.py; the session logic depends only on these
protocols, so it is fully testable without a browser.
"""

from typing import Protocol, runtime_checkable

from casinoai.engines.roulette import RouletteOutcome


@runtime_checkable
class TableReader(Protocol):
    def read_next_spin(self) -> RouletteOutcome | None:
        """Block until the current spin resolves; return its outcome, or None
        if the table is unavailable/closed (the session then ends cleanly)."""
        ...

    def is_demo(self) -> bool:
        """True only if the table is confirmed in demo/free-play mode."""
        ...


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
