"""Hands-free auto-play for FREE/DEMO tables (Phase 6, H3b accelerator).

The measurement is unchanged from manual play: the deterministic oracle applies
the strategy to the REAL outcomes read off the wire (`oracle.observe`), and that
is what produces the recorded P&L. Physical clicks only *advance the demo* so we
don't have to place every bet by hand — they don't change the outcome and don't
change the measured result. This just removes the human bottleneck so we can
collect live demo sessions faster.

HARD RULES (unchanged, enforced here and in SessionGuard):
  * FREE/DEMO tables only — the URL must pass assert_demo_mode(); real-money
    signals are refused. A loud on-screen notice + an explicit free-mode
    confirmation gate run before any automation.
  * Hard bet / round / stop-loss caps in code, independent of the spec.
  * We NEVER bypass bot-detection or captchas, and NEVER wager real money.

Each table is CALIBRATED once and stored against its URL (casinoai.live.layouts),
in three descending preferences:

  1. DOM selector (casinoai.live.dom) — deterministic and resize-proof, because
     Playwright clicks the element's own centre. Reaches into cross-origin
     iframes, so aggregator chrome ('Play for free', dialogs, settings/turbo) is
     usually real DOM.
  2. Vision-proposed pixel (casinoai.live.vision) — for the game surface itself
     when it's drawn on a WebGL/canvas and has no elements to select. A human
     confirms the drawn markers before anything is clicked.
  3. Manual pixel — read off a coordinate-grid screenshot, for the remainder.

Pixels are rescaled to the current viewport at click time, so resizing degrades
gracefully rather than silently misclicking. Two phases are calibrated: `startup`
(clicked once — free-play, dialogs, turbo) and `advance` (clicked every round).
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

TESTING_BANNER = (
    "\n"
    "============================================================\n"
    "  AUTO-PLAY — TESTING ONLY (FREE / DEMO TABLES)\n"
    "  This drives the demo game automatically to collect data.\n"
    "  • Make sure the table is in FREE / DEMO / FUN mode.\n"
    "  • No real money must be at stake. If in doubt, STOP.\n"
    "  • Physical clicks only advance the demo; the measured P&L\n"
    "    is the strategy applied to the real outcomes.\n"
    "============================================================\n"
)

_CONFIRM_PHRASES = {"yes free mode", "free mode", "yes-free-mode", "i am in free mode"}


def free_mode_confirmed(answer: str) -> bool:
    """True only if the operator explicitly confirmed FREE/DEMO mode."""
    return (answer or "").strip().lower() in _CONFIRM_PHRASES


class ControlPoint(BaseModel):
    """A viewport pixel to click (top-document coordinates; Playwright dispatches
    the click through to the iframe canvas underneath).

    `source` records who placed it ('llm' or 'manual') and `confirmed` whether a
    human has eyeballed it — only unconfirmed/missing points need the operator's
    attention on a re-calibration."""

    x: float
    y: float
    note: str = ""
    source: str = "manual"  # dom | llm | manual
    confidence: float = 1.0
    confirmed: bool = False
    # DOM-first: when set, the click resolves this selector instead of using the
    # pixel, which survives window resizes and small layout shifts. Pixels are the
    # fallback for canvas-drawn controls that have no element at all.
    selector: str = ""
    frame_url: str = ""


class TableLayout(BaseModel):
    """Calibrated click map for one demo table, keyed by `id` (derived from the
    game URL — see casinoai.live.layouts).

    Two click phases:
      * `startup` — clicked ONCE when a session opens: 'Play for free', dismiss
        dialogs, open settings, enable turbo / disable animations, close settings,
        place the first bet. Calibrating these makes every later auto start
        hands-free.
      * `advance` — clicked EVERY round to place a (repeat) bet and deal.
    """

    id: str = ""
    name: str
    game: str  # roulette | baccarat | craps
    url: str = ""
    viewport_w: int = 1280
    viewport_h: int = 800
    points: dict[str, ControlPoint] = Field(default_factory=dict)
    startup: list[str] = Field(default_factory=list)
    advance: list[str] = Field(default_factory=list)
    click_pause_ms: int = 700  # wait between clicks within a round
    settle_ms: int = 5000  # wait after the last click for the result to arrive
    startup_pause_ms: int = 2500  # waits during the one-off startup sequence
    calibrated_at: str = ""
    vision_model: str = ""
    stale: bool = False  # set when the table stopped responding — re-calibrate


class LayoutError(ValueError):
    """Layout can't drive the table (nothing to click, or a name isn't mapped)."""


def resolve_advance(layout: TableLayout) -> list[ControlPoint]:
    """The concrete click sequence for one round. Raises LayoutError if the
    layout is uncalibrated (empty advance) or references an unmapped control —
    so an uncalibrated table refuses to auto-play instead of clicking blindly."""
    if not layout.advance:
        raise LayoutError(
            f"Layout '{layout.name}' has no `advance` sequence — calibrate it first "
            f"(python -m casinoai.live.operator ... --calibrate)."
        )
    missing = [n for n in layout.advance if n not in layout.points]
    if missing:
        raise LayoutError(
            f"Layout '{layout.name}' advance references unmapped control(s): {missing}. "
            f"Known: {sorted(layout.points)}."
        )
    return [layout.points[n] for n in layout.advance]


def resolve_startup(layout: TableLayout) -> list[ControlPoint]:
    """The one-off startup click sequence (Play-for-free, turbo, first bet).
    Unlike `advance` this may legitimately be empty — a table where the operator
    prefers to set up by hand still auto-plays."""
    missing = [n for n in layout.startup if n not in layout.points]
    if missing:
        raise LayoutError(
            f"Layout '{layout.name}' startup references unmapped control(s): {missing}."
        )
    return [layout.points[n] for n in layout.startup]


def needs_attention(layout: TableLayout, min_confidence: float = 0.55) -> list[str]:
    """Control names the operator still has to resolve: referenced by a sequence
    but missing, or present-but-unconfirmed with weak model confidence. This is
    what keeps re-calibration to 'confirm, and click only what's uncalibrated'."""
    out: list[str] = []
    for name in list(layout.startup) + list(layout.advance):
        pt = layout.points.get(name)
        if pt is None:
            out.append(name)
        elif not pt.confirmed and pt.confidence < min_confidence:
            out.append(name)
    return list(dict.fromkeys(out))  # stable order, de-duplicated


def is_calibrated(layout: TableLayout) -> bool:
    """True when the table can actually be driven right now."""
    try:
        resolve_advance(layout)
        resolve_startup(layout)
    except LayoutError:
        return False
    return not layout.stale and not needs_attention(layout)


def load_layout(path: str | Path) -> TableLayout:
    data = yaml.safe_load(Path(path).read_text())
    return TableLayout.model_validate(data)


def save_layout(layout: TableLayout, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(layout.model_dump(), sort_keys=False))
    return p


# --- browser-driving layer (thin; needs Playwright + a live table) ---------------


class AutoPlayDriver:
    """Replays calibrated click sequences: `run_startup()` once to get from the
    landing page to a ready betting table (Play-for-free, dialogs, turbo), then
    `advance()` every round."""

    def __init__(self, page, layout: TableLayout, validate_advance: bool = True):
        self._page = page
        self._layout = layout
        # During calibration the advance points don't exist yet, so allow deferral.
        self._seq = resolve_advance(layout) if validate_advance else []

    def click(self, pt: ControlPoint) -> None:
        """DOM-first: click the element if this point has a selector that still
        resolves, else fall back to the calibrated pixel — rescaled to whatever
        the viewport is now, so a resized window doesn't misclick."""
        from casinoai.live.dom import resolve_locator, scale_point

        if pt.selector:
            loc = resolve_locator(self._page, pt.selector, pt.frame_url)
            if loc is not None:
                loc.click()
                return
        size = self._page.viewport_size or {
            "width": self._layout.viewport_w,
            "height": self._layout.viewport_h,
        }
        x, y = scale_point(
            pt.x,
            pt.y,
            self._layout.viewport_w,
            self._layout.viewport_h,
            size["width"],
            size["height"],
        )
        self._page.mouse.click(x, y)

    @property
    def page(self):
        return self._page

    def follow_new_tab(self):
        """Aggregators launch the game in a SECOND tab (casino.guru opens
        gameDetailIos?gameId=...). After startup, drive whichever page is newest,
        or the clicks keep landing on the now-irrelevant landing page."""
        try:
            pages = [p for p in self._page.context.pages if not p.is_closed()]
        except Exception:
            return self._page
        if pages and pages[-1] is not self._page:
            self._page = pages[-1]
            try:
                self._page.bring_to_front()
            except Exception:
                pass
        return self._page

    def wait_until_loaded(self, timeout_ms: int = 120_000, poll_ms: int = 4000) -> bool:
        """Block until the game stops visually changing. These WebGL tables take
        30s+ to load; detecting controls too early finds only a spinner. Returns
        True if it settled, False on timeout (an animating table never fully
        settles, which is fine — the caller still proceeds)."""
        import hashlib

        prev, stable, waited = None, 0, 0
        while waited < timeout_ms:
            self._page.wait_for_timeout(poll_ms)
            waited += poll_ms
            try:
                digest = hashlib.md5(self._page.screenshot()).hexdigest()
            except Exception:
                continue
            stable = stable + 1 if digest == prev else 0
            prev = digest
            if stable >= 2:
                return True
        return False

    def run_startup(self) -> None:
        """Click the one-off startup sequence, following the game into its new tab
        and waiting for it to load. Waits longer between these clicks than between
        round clicks — dialogs and settings panels animate in.

        Crucially, when a click opens the game in a new tab we wait for that tab to
        finish loading BEFORE the next click. These WebGL tables take 30s+, and
        firing the menu/turbo/first-bet clicks into a still-loading table silently
        does nothing — the table ends up with no bet placed and never spins."""
        for pt in resolve_startup(self._layout):
            before = self._page
            self.click(pt)
            self._page.wait_for_timeout(self._layout.startup_pause_ms)
            if self.follow_new_tab() is not before:
                self.wait_until_loaded()
        self.wait_until_loaded()

    def advance(self) -> None:
        for pt in self._seq:
            self.click(pt)
            self._page.wait_for_timeout(self._layout.click_pause_ms)
        self._page.wait_for_timeout(self._layout.settle_ms)


class AdvancingReader:
    """Wraps a live TableReader so each read first advances the demo. This keeps
    exactly one advance per round on BOTH bet rounds and strategy sit-out rounds
    (the session loop reads once per round either way)."""

    def __init__(self, base, driver: AutoPlayDriver):
        self._base = base
        self._driver = driver

    def attach(self, game_url: str) -> None:
        self._base.attach(game_url)

    def is_demo(self) -> bool:
        return self._base.is_demo()

    def read_next_spin(self):
        self._driver.advance()
        return self._base.read_next_spin()


class SilentPlacer:
    """Auto-play placer: the driver already advances the demo, so this only
    records the strategy's intended bets (printed for the watching operator).
    Placing the strategy's exact chips is not required for the measurement."""

    def __init__(self, printer=print):
        self._print = printer

    def place_bets(self, bets: list) -> None:
        desc = ", ".join(f"{b.stake_units:g}u on {b.bet_type}" for b in bets)
        self._print(f"[AUTO] strategy bet this round: {desc}")


# --- calibration -----------------------------------------------------------------

_GRID_JS = """
(step) => {
  const id = '__cai_grid__';
  document.getElementById(id)?.remove();
  const o = document.createElement('div');
  o.id = id;
  o.style.cssText = 'position:fixed;inset:0;z-index:2147483647;pointer-events:none;';
  const W = window.innerWidth, H = window.innerHeight;
  const svgns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(svgns, 'svg');
  svg.setAttribute('width', W); svg.setAttribute('height', H);
  svg.style.cssText = 'position:absolute;inset:0';
  const line = (x1,y1,x2,y2,c) => {
    const l = document.createElementNS(svgns,'line');
    l.setAttribute('x1',x1); l.setAttribute('y1',y1);
    l.setAttribute('x2',x2); l.setAttribute('y2',y2);
    l.setAttribute('stroke',c); l.setAttribute('stroke-width','1'); svg.appendChild(l);
  };
  const label = (x,y,t) => {
    const el = document.createElementNS(svgns,'text');
    el.setAttribute('x',x+2); el.setAttribute('y',y+11);
    el.setAttribute('fill','#ff2d55'); el.setAttribute('font-size','11');
    el.setAttribute('font-family','monospace'); el.textContent = t; svg.appendChild(el);
  };
  for (let x=0; x<=W; x+=step){
    line(x,0,x,H, x%(step*2)?'#ff2d5533':'#ff2d5588');
    if(!(x%(step*2))) label(x,12,String(x));
  }
  for (let y=0; y<=H; y+=step){
    line(0,y,W,y, y%(step*2)?'#ff2d5533':'#ff2d5588');
    if(!(y%(step*2))) label(2,y,String(y));
  }
  o.appendChild(svg); document.body.appendChild(o);
  return {W, H};
}
"""

_GRID_REMOVE_JS = "() => document.getElementById('__cai_grid__')?.remove()"


def grid_screenshot(page, out_path: str | Path, step: int = 50) -> Path:
    """Screenshot the page with a labelled coordinate grid overlaid — the fallback
    when the vision model can't see a control and the operator reads the pixel off
    by hand. The overlay is removed again afterwards."""
    page.evaluate(_GRID_JS, step)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out))
    page.evaluate(_GRID_REMOVE_JS)
    return out
