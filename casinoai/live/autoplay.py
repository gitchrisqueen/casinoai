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

Because the provider games render on a WebGL/canvas inside cross-origin iframes,
the clickable control positions can't be auto-detected (the browser blocks
reading events inside cross-origin frames). So each table is CALIBRATED once:
we screenshot the table with a coordinate grid overlaid and you record the pixel
(x, y) of each control (select-chip, bet spot(s), deal/spin, new-round). Those
points are replayed every round. Calibration is per table/viewport; re-run it if
the layout changes.
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
    the click through to the iframe canvas underneath)."""

    x: float
    y: float
    note: str = ""


class TableLayout(BaseModel):
    """Calibrated click map for one demo table. `advance` is the ordered list of
    control names clicked every round to place a (repeat) bet and deal."""

    name: str
    game: str  # roulette | baccarat | craps
    url: str = ""
    viewport_w: int = 1280
    viewport_h: int = 800
    points: dict[str, ControlPoint] = Field(default_factory=dict)
    advance: list[str] = Field(default_factory=list)
    click_pause_ms: int = 700  # wait between clicks within a round
    settle_ms: int = 5000  # wait after the last click for the result to arrive


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
    """Replays a calibrated click sequence to advance the demo one round."""

    def __init__(self, page, layout: TableLayout):
        self._page = page
        self._layout = layout
        self._seq = resolve_advance(layout)  # validates up front

    def advance(self) -> None:
        for pt in self._seq:
            self._page.mouse.click(pt.x, pt.y)
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


def controls_for(game: str) -> list[str]:
    """The control points to calibrate for each game's simplest advance loop."""
    game = game.lower()
    if game == "roulette":
        # Repeat the previous bet, then spin (most demos keep the last chips).
        return ["repeat_bet", "spin"]
    if game == "baccarat":
        return ["chip_min", "player_box", "deal"]
    if game == "craps":
        return ["chip_min", "pass_line", "roll"]
    return ["bet_spot", "deal"]


def calibrate(
    page, game: str, name: str, url: str, out_path: str | Path, read_fn=input
) -> TableLayout:
    """Interactive one-time calibration. Assumes `page` is already on the betting
    table (operator navigated there). Overlays a coordinate grid, screenshots it,
    and asks the operator to read off each control's (x, y). Returns/saves a
    TableLayout. Playwright-driven; not unit-tested."""
    step = 50
    dims = page.evaluate(_GRID_JS, step)
    shot = Path(out_path).with_suffix(".calibration.png")
    shot.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(shot))
    print(f"\nSaved a coordinate-grid screenshot to: {shot}")
    print("Open it, read the pixel (x, y) of each control below, and enter them.\n")

    points: dict[str, ControlPoint] = {}
    for ctrl in controls_for(game):
        raw = (read_fn(f"  {ctrl} — x,y (blank to skip): ") or "").strip()
        if not raw:
            continue
        xs, ys = raw.replace(" ", "").split(",")[:2]
        points[ctrl] = ControlPoint(x=float(xs), y=float(ys), note=ctrl)

    page.evaluate(_GRID_REMOVE_JS)
    layout = TableLayout(
        name=name,
        game=game,
        url=url,
        viewport_w=int(dims["W"]),
        viewport_h=int(dims["H"]),
        points=points,
        advance=[c for c in controls_for(game) if c in points],
    )
    save_layout(layout, out_path)
    print(f"\nSaved layout -> {out_path}")
    try:
        resolve_advance(layout)
        print("Layout is playable. ✓")
    except LayoutError as exc:
        print(f"⚠ Not yet playable: {exc}")
    return layout
