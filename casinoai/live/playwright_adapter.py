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
    for key in ("winningNumber", "winning_number", "result", "number", "pocket", "value"):
        if key in payload:
            val = str(payload[key]).strip()
            if re.fullmatch(r"00|0|[1-9]|[12][0-9]|3[0-6]", val):
                return val
    return None


def _loads_framed(raw: str):
    """Parse a WebSocket frame that may be wrapped in transport framing. Handles
    bare JSON and socket.io-style prefixes (e.g. `3:::{...}` used by Softswiss /
    twogameslink 'gpas' games) by falling back to the first `{`/`[` .. last
    `}`/`]` slice. Returns the decoded object, or None if there's no JSON."""
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        pass
    starts = [i for i in (raw.find("{"), raw.find("[")) if i != -1]
    if not starts:
        return None
    start = min(starts)
    end = max(raw.rfind("}"), raw.rfind("]"))
    if end <= start:
        return None
    try:
        return json.loads(raw[start : end + 1])
    except (ValueError, TypeError):
        return None


def extract_pockets_from_frame(raw: str, parser: ResultParser = default_result_parser) -> list[str]:
    """Pure helper (unit-tested): pull any roulette results out of one raw
    WebSocket frame. Accepts bare JSON, JSON arrays, socket.io-framed messages,
    and nested dicts; returns every pocket the parser recognizes. Non-JSON → []."""
    data = _loads_framed(raw)
    if data is None:
        return []

    found: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            pocket = parser(node)
            if pocket is not None:
                found.append(pocket)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data)
    return found


# --- baccarat --------------------------------------------------------------------

_BACC_WORDS = {
    "player": "player",
    "p": "player",
    "punto": "player",
    "banker": "banker",
    "b": "banker",
    "banco": "banker",
    "tie": "tie",
    "t": "tie",
    "egalite": "tie",
    "draw": "tie",
    "égalité": "tie",
}


def default_baccarat_parser(payload: dict) -> str | None:
    """Best-effort baccarat winner parser: reads an explicit winner word from
    common keys, else derives it from player/banker scores. Operators should
    verify against captured traffic (use `capture` mode) and specialize if the
    provider encodes the winner differently."""
    for key in ("winner", "result", "outcome", "gameResult", "win", "side", "winningSide"):
        if key in payload:
            v = str(payload[key]).strip().lower()
            if v in _BACC_WORDS:
                return _BACC_WORDS[v]
    ps = payload.get("playerScore", payload.get("player_score", payload.get("playerPoints")))
    bs = payload.get("bankerScore", payload.get("banker_score", payload.get("bankerPoints")))
    if ps is not None and bs is not None:
        try:
            ps, bs = int(ps), int(bs)
        except (ValueError, TypeError):
            return None
        return "player" if ps > bs else "banker" if bs > ps else "tie"
    return None


def extract_winners_from_frame(
    raw: str, parser: ResultParser = default_baccarat_parser
) -> list[str]:
    """Pure helper (unit-tested): pull any baccarat winners ('player'/'banker'/
    'tie') out of one raw WebSocket frame. Same framing handling as roulette."""
    data = _loads_framed(raw)
    if data is None:
        return []
    found: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            w = parser(node)
            if w is not None:
                found.append(w)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data)
    return found


# --- craps -----------------------------------------------------------------------

_CRAPS_WORDS = {
    "pass": "pass_win",
    "pass_win": "pass_win",
    "passline": "pass_win",
    "pass_line_win": "pass_win",
    "win": "pass_win",
    "point_made": "pass_win",
    "dont": "pass_lose",
    "dont_pass": "pass_lose",
    "pass_line_lose": "pass_lose",
    "lose": "pass_lose",
    "loss": "pass_lose",
    "seven_out": "pass_lose",
    "sevenout": "pass_lose",
    "push": "dont_push",
    "bar": "dont_push",
}


def default_craps_parser(payload: dict) -> str | None:
    """Best-effort craps line-result parser: reads a resolved pass-line decision
    ('pass_win'/'pass_lose'/'dont_push') from common keys. Verify against
    captured traffic — craps message formats vary widely by provider."""
    for key in ("lineResult", "line_result", "result", "outcome", "passLine", "decision"):
        if key in payload:
            v = str(payload[key]).strip().lower().replace(" ", "_")
            if v in _CRAPS_WORDS:
                return _CRAPS_WORDS[v]
    return None


def extract_line_results_from_frame(
    raw: str, parser: ResultParser = default_craps_parser
) -> list[str]:
    """Pure helper (unit-tested): pull craps line results out of one WS frame."""
    data = _loads_framed(raw)
    if data is None:
        return []
    found: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            r = parser(node)
            if r is not None:
                found.append(r)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data)
    return found


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
        self._pending.extend(extract_pockets_from_frame(payload, self._parser))

    def is_demo(self) -> bool:
        return self._is_demo

    def read_next_spin(self) -> RouletteOutcome | None:
        """Block (polling the WS buffer) until a new spin result arrives, or
        return None on timeout so the session ends cleanly."""
        waited = 0.0
        while waited < self._timeout_s:
            if self._pending:
                return RouletteOutcome.from_pocket(self._pending.pop(0))
            self._page.wait_for_timeout(500)
            waited += 0.5
        return None


class PlaywrightBaccaratReader:
    """Reads baccarat coup winners off the game's WebSocket frames — the
    baccarat twin of PlaywrightRouletteReader. Emits BaccaratOutcome so the
    oracle can't tell live from sim."""

    def __init__(
        self, page, parser: ResultParser = default_baccarat_parser, timeout_s: float = 120.0
    ):
        self._page = page
        self._parser = parser
        self._timeout_s = timeout_s
        self._pending: list[str] = []
        self._is_demo = False

    def attach(self, game_url: str) -> None:
        assert_demo_mode(game_url)
        self._is_demo = True
        self._page.on("websocket", lambda ws: ws.on("framereceived", self._on_frame))
        self._page.goto(game_url)

    def _on_frame(self, payload) -> None:
        self._pending.extend(extract_winners_from_frame(payload, self._parser))

    def is_demo(self) -> bool:
        return self._is_demo

    def read_next_spin(self):
        from casinoai.engines.baccarat import BaccaratWinner
        from casinoai.live.reader import _baccarat_outcome

        waited = 0.0
        while waited < self._timeout_s:
            if self._pending:
                return _baccarat_outcome(BaccaratWinner(self._pending.pop(0)))
            self._page.wait_for_timeout(500)
            waited += 0.5
        return None


class PlaywrightCrapsReader:
    """Reads craps pass-line results off the game's WebSocket frames; emits
    CrapsOutcome. One coup = one round, matching the engine."""

    def __init__(self, page, parser: ResultParser = default_craps_parser, timeout_s: float = 120.0):
        self._page = page
        self._parser = parser
        self._timeout_s = timeout_s
        self._pending: list[str] = []
        self._is_demo = False

    def attach(self, game_url: str) -> None:
        assert_demo_mode(game_url)
        self._is_demo = True
        self._page.on("websocket", lambda ws: ws.on("framereceived", self._on_frame))
        self._page.goto(game_url)

    def _on_frame(self, payload) -> None:
        self._pending.extend(extract_line_results_from_frame(payload, self._parser))

    def is_demo(self) -> bool:
        return self._is_demo

    def read_next_spin(self):
        from casinoai.engines.craps import LineResult
        from casinoai.live.reader import _craps_outcome

        waited = 0.0
        while waited < self._timeout_s:
            if self._pending:
                return _craps_outcome(LineResult(self._pending.pop(0)))
            self._page.wait_for_timeout(500)
            waited += 0.5
        return None


class OperatorBetPlacer:
    """OBSERVER mode: the human places bets by hand. This placer only prints the
    oracle's instruction for the operator to follow; it drives no UI, wagers
    nothing automatically. The safe default for live/demo runs."""

    def __init__(self, printer=print):
        self._print = printer

    def place_bets(self, bets: list) -> None:
        desc = ", ".join(f"{b.stake_units:g}u on {b.bet_type}" for b in bets)
        self._print(f"[OPERATOR] Place: {desc}")
