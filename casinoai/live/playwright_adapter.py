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
    demo_signals = (
        "realmode=0",
        "mode=demo",
        "funmode",
        "play=fun",
        "demo=1",
        "/demo",
        "play-free",
        "free-play",
        "/free",
        "for-fun",
        "playforfun",
        "gamedetail",
    )
    real_signals = ("realmode=1", "mode=real", "play=real")
    if any(s in lowered for s in real_signals):
        raise RuntimeError(f"Refusing: URL indicates real-money mode: {url}")
    if not any(s in lowered for s in demo_signals):
        raise RuntimeError(
            "Refusing: could not confirm demo/free-play mode from the launcher URL. "
            "An operator must verify demo mode before running."
        )


def wire_ws_capture(page, on_frame, sent=False) -> None:
    """Attach a WebSocket-frame listener to `page` AND to any new tab/popup
    opened in its browser context — many casino aggregators launch the game in a
    SECOND tab, whose WebSocket the original page never sees. `on_frame(payload)`
    is called per received frame (and per sent frame too if `sent=True`)."""

    def hook(pg):
        def on_ws(ws):
            ws.on("framereceived", on_frame)
            if sent:
                ws.on("framesent", on_frame)

        pg.on("websocket", on_ws)

    hook(page)
    page.context.on("page", hook)  # future tabs/popups (the real game window)


def wire_result_capture(page, on_payload) -> None:
    """Feed `on_payload(text)` with every WebSocket frame AND every HTTP JSON
    response body, across `page` and any new tab. Providers deliver results over
    WebSocket (Softswiss/gpas) OR plain HTTP (OneTouch), so we watch both."""

    def hook(pg):
        pg.on("websocket", lambda ws: ws.on("framereceived", on_payload))

        def on_resp(resp):
            try:
                if resp.request.resource_type not in ("xhr", "fetch"):
                    return
                ctype = (resp.headers or {}).get("content-type", "")
                if "json" in ctype or "text" in ctype:
                    on_payload(resp.text())
            except Exception:
                pass

        pg.on("response", on_resp)

    hook(page)
    page.context.on("page", hook)


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


_POCKET_RE = re.compile(r"00|0|[1-9]|[12][0-9]|3[0-6]")
# Softswiss / twogameslink 'gpas' games encode a spin as a chr(0xFD)-delimited
# command string inside gameData.commands, opcode 45 = result, field[2] = pocket
# (captured live: "45ý0ý29ý200" -> winning number 29). Delimiter is 'ý' (0xFD).
_GPAS_DELIM = "\xfd"


def _gpas_pocket(s: str) -> str | None:
    if _GPAS_DELIM not in s:
        return None
    parts = s.split(_GPAS_DELIM)
    if len(parts) >= 3 and parts[0] == "45" and _POCKET_RE.fullmatch(parts[2]):
        return parts[2]
    return None


def extract_pockets_from_frame(raw: str, parser: ResultParser = default_result_parser) -> list[str]:
    """Pure helper (unit-tested): pull any roulette results out of one raw
    WebSocket frame. Handles bare JSON, arrays, socket.io framing, nested dicts,
    AND Softswiss/gpas opcode-45 command strings. Non-JSON → []."""
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
        elif isinstance(node, str):
            g = _gpas_pocket(node)
            if g is not None:
                found.append(g)

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
    """Best-effort baccarat winner parser across the formats seen in the wild:
    OneTouch `betAreaOutcomes` (["PLAYER","BIG"] -> player), explicit winner
    words, OneTouch player/dealer card hands (final handScore), and generic
    player/banker scores. Verify against captured traffic for a new provider."""
    # OneTouch (playmode.onetouch.io): betAreaOutcomes lists the winning areas,
    # incl. the main outcome PLAYER / BANKER / TIE (plus side bets like BIG).
    areas = payload.get("betAreaOutcomes")
    if isinstance(areas, list):
        up = {str(a).upper() for a in areas}
        for word, winner in (("PLAYER", "player"), ("BANKER", "banker"), ("TIE", "tie")):
            if word in up:
                return winner
    for key in ("winner", "result", "outcome", "gameResult", "side", "winningSide"):
        if key in payload:
            v = str(payload[key]).strip().lower()
            if v in _BACC_WORDS:
                return _BACC_WORDS[v]
    # OneTouch card hands: the last card's handScore is the final hand total.
    pc, dc = payload.get("playerCards"), payload.get("dealerCards")
    if isinstance(pc, list) and isinstance(dc, list) and pc and dc:
        try:
            ps, bs = int(pc[-1]["handScore"]), int(dc[-1]["handScore"])
            return "player" if ps > bs else "banker" if bs > ps else "tie"
        except (KeyError, ValueError, TypeError, IndexError):
            pass
    ps = payload.get("playerScore", payload.get("player_score", payload.get("playerPoints")))
    bs = payload.get("bankerScore", payload.get("banker_score", payload.get("bankerPoints")))
    if ps is not None and bs is not None:
        try:
            ps, bs = int(ps), int(bs)
        except (ValueError, TypeError):
            return None
        return "player" if ps > bs else "banker" if bs > ps else "tie"
    return None


_GAME_ID_RE = re.compile(r'"gameId"\s*:\s*"([^"]+)"')


def _frame_game_id(raw: str) -> str | None:
    """The provider's per-coup id, used to dedup re-sent results (OneTouch)."""
    m = _GAME_ID_RE.search(raw)
    return m.group(1) if m else None


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

        wire_result_capture(self._page, self._on_frame)
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
        self._seen: set[str] = set()  # dedup by gameId — OneTouch re-sends results
        self._is_demo = False

    def attach(self, game_url: str) -> None:
        assert_demo_mode(game_url)
        self._is_demo = True
        wire_result_capture(self._page, self._on_frame)
        self._page.goto(game_url)

    def _on_frame(self, payload) -> None:
        winners = extract_winners_from_frame(payload, self._parser)
        if not winners:
            return
        # A result frame is one coup; dedup by its gameId (or the raw payload)
        # so a re-sent/refreshed result isn't counted twice.
        key = _frame_game_id(payload) or payload
        if key in self._seen:
            return
        self._seen.add(key)
        self._pending.extend(winners[:1])

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
        wire_result_capture(self._page, self._on_frame)
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
    nothing automatically. The safe default for live/demo runs.

    When told the table's base unit (unit_size) and chips, it prints the real
    currency amount and the exact chip stack for each bet, so the instruction
    lines up with the verified table-compatible stakes instead of raw units."""

    def __init__(
        self, printer=print, unit_size: float = 1.0, chips=None, currency: str = "credits"
    ):
        self._print = printer
        self._unit = unit_size or 1.0
        self._chips = chips
        self._currency = currency

    def _one(self, b) -> str:
        # Show units (the strategy's language) plus, when we know the base unit /
        # table chips, the real currency amount and the exact chip stack — so the
        # instruction is the verified table-compatible amount, not a raw unit.
        if self._unit == 1.0 and not self._chips:
            return f"{b.stake_units:g}u on {b.bet_type}"
        amount = round(b.stake_units * self._unit, 2)
        note = f"{amount:g} {self._currency} ({b.stake_units:g}u"
        if self._chips:
            from casinoai.live.table import chip_breakdown

            stack = chip_breakdown(amount, self._chips)
            note += (
                "; chips " + "+".join(f"{c:g}" for c in stack)
                if stack
                else "; NOT PLACEABLE with this table's chips"
            )
        return f"{note}) on {b.bet_type}"

    def place_bets(self, bets: list) -> None:
        desc = ", ".join(self._one(b) for b in bets)
        self._print(f"[OPERATOR] Place: {desc}")
