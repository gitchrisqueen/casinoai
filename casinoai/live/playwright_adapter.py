"""Thin Playwright binding for live/demo roulette (Phase 6, H3b).

WHAT WE LEARNED probing the recommended demos (see docs/live_adapter.md):
the free-play provider roulette games (Softswiss / twogameslink / Playzido etc.)
render on WebGL/canvas inside nested cross-origin iframes, so the winning number
is NOT DOM text. The robust, low-fragility way to read outcomes is to intercept
the game's WebSocket/network messages, which carry the spin result as structured
data. Demo mode is confirmable from the launcher URL (`realMode=0`).

Two operating modes, both human-initiated:
- OBSERVER (default, recommended): the human operator places bets by hand
  following the oracle's printed instructions; this adapter only *reads* spin
  results off the wire to record and compare. No automated wagering, maximally
  ToS-respectful.
- ASSISTED: the adapter also drives bet placement via canvas coordinates. Off
  by default; fragile and per-site; enable only with explicit go-ahead.

Playwright is an optional dependency (extra `live`); imported lazily so the
rest of casinoai needs neither Playwright nor a browser.

This module is deliberately thin. The reusable, tested logic lives in
session.py / guard.py / compare.py; here we only bind those to a real browser.
"""

import json
import re
from collections.abc import Callable

from casinoai.engines.roulette import RouletteOutcome

# Message shapes vary per provider; an operator supplies a parser that maps a
# raw WS/JSON payload to a pocket string ('0'..'36') or None if it isn't a result.
ResultParser = Callable[[dict], str | None]


def assert_demo_mode(url: str) -> None:
    """Refuse anything that isn't demonstrably demo/free-play. We look for the
    common launcher signals; if we cannot prove demo, we do not proceed."""
    lowered = url.lower()
    demo_signals = ("realmode=0", "mode=demo", "funmode", "play=fun", "demo=1", "/demo")
    real_signals = ("realmode=1", "mode=real", "play=real")
    if any(s in lowered for s in real_signals):
        raise RuntimeError(f"Refusing: URL indicates real-money mode: {url}")
    if not any(s in lowered for s in demo_signals):
        raise RuntimeError(
            "Refusing: could not confirm demo/free-play mode from the launcher URL. "
            "An operator must verify demo mode before running."
        )


def default_result_parser(payload: dict) -> str | None:
    """Best-effort generic parser: many providers put the winning number under a
    key like 'result'/'winningNumber'/'number'. Operators should replace this
    with a provider-specific parser verified against captured traffic."""
    for key in ("winningNumber", "winning_number", "result", "number", "pocket"):
        if key in payload:
            val = str(payload[key]).strip()
            if re.fullmatch(r"00|0|[1-9]|[12][0-9]|3[0-6]", val):
                return val
    return None


class PlaywrightRouletteReader:
    """Reads roulette spin outcomes off the game's WebSocket frames.

    Usage (operator entry point, human-launched):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)   # operator watches
            page = browser.new_page()
            reader = PlaywrightRouletteReader(page, parser=my_provider_parser)
            reader.attach(game_url)          # asserts demo mode, wires WS capture
            # ... hand `reader` to run_live_session(...)
    """

    def __init__(self, page, parser: ResultParser = default_result_parser, timeout_s: float = 90.0):
        self._page = page
        self._parser = parser
        self._timeout_s = timeout_s
        self._pending: list[str] = []
        self._is_demo = False

    def attach(self, game_url: str) -> None:
        assert_demo_mode(game_url)
        self._is_demo = True

        def on_ws(ws):
            ws.on("framereceived", self._on_frame)

        # Capture spin results from every websocket the game opens.
        self._page.on("websocket", on_ws)
        self._page.goto(game_url)

    def _on_frame(self, payload) -> None:
        try:
            data = json.loads(payload)
        except (ValueError, TypeError):
            return
        for obj in data if isinstance(data, list) else [data]:
            if isinstance(obj, dict):
                pocket = self._parser(obj)
                if pocket is not None:
                    self._pending.append(pocket)

    def is_demo(self) -> bool:
        return self._is_demo

    def read_next_spin(self) -> RouletteOutcome | None:
        """Wait until a new spin result arrives on the wire (or timeout)."""
        try:
            self._page.wait_for_event(
                "websocket",  # cheap keepalive; real wait is the polling below
                timeout=1,
            )
        except Exception:
            pass
        # poll the buffer the WS handler fills
        deadline = self._timeout_s
        step = 0.5
        while deadline > 0:
            if self._pending:
                return RouletteOutcome.from_pocket(self._pending.pop(0))
            self._page.wait_for_timeout(int(step * 1000))
            deadline -= step
        return None  # table went quiet — session ends cleanly


class OperatorBetPlacer:
    """OBSERVER mode: the human places bets by hand. This placer only prints the
    oracle's instruction for the operator to follow; it drives no UI, wagers
    nothing automatically. The safe default for live/demo runs."""

    def __init__(self, printer=print):
        self._print = printer

    def place_bets(self, bets: list) -> None:
        desc = ", ".join(f"{b.stake_units:g}u on {b.bet_type}" for b in bets)
        self._print(f"[OPERATOR] Place: {desc}")
