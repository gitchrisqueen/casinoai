"""LLM-driven table calibration: find the clickable controls in a screenshot.

A vision model is shown the table screenshot and asked for the centre pixel of
each named control ('Play for free', the turbo toggle, the deal button, ...).
The proposal is then drawn back onto the screenshot so the operator confirms it
by eye — measured accuracy is good but not exact, so a human always sees the
markers before anything is clicked. Only controls the model missed (or that the
operator rejects) need a manual coordinate.

Model choice is a parameter, never hardcoded (CLAUDE.md); the default comes from
CASINOAI_VISION_MODEL. Measured on a synthetic probe (800x400, 120x40 buttons):

    ollama-cloud/minimax-m3    ~10-20px error — inside the target      (default)
    ollama-cloud/qwen3.5:397b  ~30-50px error — consistently just outside
    ollama-cloud/gemma4:31b    returned out-of-bounds coordinates
    ollama-cloud/glm-5.2       rejects image input entirely

All access goes through casinoai.llm.gateway, which handles structured output,
retries and cost logging.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field

from casinoai.live.autoplay import ControlPoint, TableLayout

DEFAULT_VISION_MODEL = os.environ.get("CASINOAI_VISION_MODEL", "ollama-cloud/minimax-m3")


class ControlSpec(BaseModel):
    """A control we want located, described in the words a model can see."""

    name: str
    description: str
    phase: str  # startup | advance
    required: bool = True


# Startup controls are clicked ONCE per session; advance controls every round.
_COMMON_STARTUP = [
    ControlSpec(
        name="play_for_free",
        description=(
            "the button that starts the game in free/demo mode — labelled like "
            "'Play for free', 'Demo', 'Try for free' or 'Play for fun'"
        ),
        phase="startup",
    ),
    ControlSpec(
        name="close_dialog",
        description=(
            "the close/dismiss control (an X, 'OK', 'Continue' or 'Accept') of any "
            "welcome, cookie or info dialog covering the table; skip if none"
        ),
        phase="startup",
        required=False,
    ),
    ControlSpec(
        name="settings",
        description="the game's settings/options button, usually a gear or hamburger icon",
        phase="startup",
        required=False,
    ),
    ControlSpec(
        name="turbo",
        description=(
            "the toggle that speeds play up — 'Turbo', 'Fast play', 'Quick spin', or "
            "the switch that disables animations, inside the settings panel"
        ),
        phase="startup",
        required=False,
    ),
    ControlSpec(
        name="close_settings",
        description="the control that closes the settings panel and returns to the table",
        phase="startup",
        required=False,
    ),
]

_ADVANCE: dict[str, list[ControlSpec]] = {
    "roulette": [
        ControlSpec(
            name="repeat_bet",
            description="the 'Repeat'/'Rebet'/'Double' button that re-places the previous bet",
            phase="advance",
        ),
        ControlSpec(
            name="spin",
            description="the button that starts the spin — 'Spin' or 'Play'",
            phase="advance",
        ),
    ],
    "baccarat": [
        ControlSpec(
            name="chip_min",
            description="the lowest-value chip in the chip tray (the smallest denomination)",
            phase="advance",
        ),
        ControlSpec(
            name="player_box",
            description="the PLAYER betting box on the baccarat table felt",
            phase="advance",
        ),
        ControlSpec(
            name="deal",
            description="the button that deals the hand — 'Deal' or 'Play'",
            phase="advance",
        ),
    ],
    "craps": [
        ControlSpec(
            name="chip_min",
            description="the lowest-value chip in the chip tray",
            phase="advance",
        ),
        ControlSpec(
            name="pass_line",
            description="the PASS LINE betting area on the craps felt",
            phase="advance",
        ),
        ControlSpec(name="roll", description="the button that rolls the dice", phase="advance"),
    ],
}


def controls_for_game(game: str, phase: str | None = None) -> list[ControlSpec]:
    specs = _COMMON_STARTUP + _ADVANCE.get(game.lower(), _ADVANCE["baccarat"])
    return [s for s in specs if phase is None or s.phase == phase]


class ProposedControl(BaseModel):
    """A located control as a BOUNDING BOX, not a point.

    Asking for a box and clicking its centre measurably beats asking for a centre
    directly: on the real OneTouch baccarat table, points put 2 of 3 controls a
    few pixels OUTSIDE their target (a consistent downward bias — and 4px below
    the DEAL button is a dead click), while box centres put 3 of 3 inside."""

    name: str
    found: bool
    x1: float = 0.0
    y1: float = 0.0
    x2: float = 0.0
    y2: float = 0.0
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @property
    def x(self) -> float:
        return (self.x1 + self.x2) / 2

    @property
    def y(self) -> float:
        return (self.y1 + self.y2) / 2


class VisionProposal(BaseModel):
    controls: list[ProposedControl] = Field(default_factory=list)


_SYSTEM = (
    "You locate UI controls in screenshots of online casino demo games. "
    "You answer only with the requested JSON. Coordinates are pixels in the "
    "image's own coordinate space, origin (0,0) at the TOP-LEFT. Give the CENTRE "
    "of each control. If a control is not visible, set found=false — never guess."
)


def build_prompt(specs: list[ControlSpec], width: int, height: int) -> str:
    lines = [
        f"This screenshot is exactly {width} pixels wide and {height} pixels tall.",
        "For each control below, give its BOUNDING BOX: x1,y1 is the top-left "
        "corner and x2,y2 the bottom-right corner, in image pixels.",
        "",
    ]
    for s in specs:
        opt = "" if s.required else " (optional — may not exist)"
        lines.append(f"- {s.name}: {s.description}{opt}")
    lines += [
        "",
        "Return one entry per control with found, x1, y1, x2, y2 and a confidence "
        f"in 0..1. Coordinates must satisfy 0 <= x1 < x2 <= {width} and "
        f"0 <= y1 < y2 <= {height}. Box the control tightly. "
        "Set found=false (and confidence 0) for anything you cannot actually see.",
    ]
    return "\n".join(lines)


def propose_controls(
    screenshot: str | Path | bytes,
    specs: list[ControlSpec],
    width: int,
    height: int,
    model: str | None = None,
) -> VisionProposal:
    """Ask the vision model to locate `specs` in the screenshot."""
    from casinoai.llm.gateway import complete

    resp = complete(
        build_prompt(specs, width, height),
        model=model or DEFAULT_VISION_MODEL,
        schema=VisionProposal,
        system=_SYSTEM,
        images=[screenshot],
        max_tokens=3000,
        tag="table-calibration",
    )
    return resp.parsed if isinstance(resp.parsed, VisionProposal) else VisionProposal()


def in_bounds(p: ProposedControl, width: int, height: int) -> bool:
    """The box must be well-formed AND on-screen; its centre is what we click."""
    if not (p.x2 > p.x1 and p.y2 > p.y1):
        return False
    return 0 <= p.x <= width and 0 <= p.y <= height


def merge_proposal(
    layout: TableLayout, proposal: VisionProposal, model: str, overwrite_confirmed: bool = False
) -> list[str]:
    """Fold a proposal into `layout`. Points a human already confirmed are kept
    (a re-calibration shouldn't silently move them) unless overwrite_confirmed.
    Returns the names that were written."""
    written: list[str] = []
    for pc in proposal.controls:
        if not pc.found or not in_bounds(pc, layout.viewport_w, layout.viewport_h):
            continue
        existing = layout.points.get(pc.name)
        if existing is not None and existing.confirmed and not overwrite_confirmed:
            continue
        layout.points[pc.name] = ControlPoint(
            x=pc.x,
            y=pc.y,
            note=pc.name,
            source="llm",
            confidence=pc.confidence,
            confirmed=False,
        )
        written.append(pc.name)
    layout.vision_model = model
    return written


# --- visual confirmation ---------------------------------------------------------

_ANNOTATE_HTML = """
<body style="margin:0;position:relative;width:{w}px;height:{h}px">
<img src="data:image/png;base64,{b64}" style="position:absolute;inset:0;width:{w}px;height:{h}px">
{markers}
</body>
"""

_MARKER = (
    '<div style="position:absolute;left:{x}px;top:{y}px;width:26px;height:26px;'
    'margin:-13px 0 0 -13px;border:3px solid {color};border-radius:50%"></div>'
    '<div style="position:absolute;left:{lx}px;top:{ly}px;background:{color};color:#fff;'
    'font:bold 12px monospace;padding:2px 5px;border-radius:3px;white-space:nowrap">{label}</div>'
)


def annotate(
    page, screenshot_png: bytes, layout: TableLayout, names: list[str], out_path: Path
) -> Path:
    """Draw the proposed points on the screenshot so the operator can confirm by
    eye. Rendered in a SEPARATE throwaway page — never `page` itself, because
    set_content() would replace the live game and kill the session."""
    import base64

    markers = []
    for n in names:
        pt = layout.points.get(n)
        if pt is None:
            continue
        color = "#00c853" if pt.confidence >= 0.55 else "#ff6d00"
        markers.append(
            _MARKER.format(
                x=pt.x,
                y=pt.y,
                lx=pt.x + 16,
                ly=pt.y + 10,
                color=color,
                label=f"{n} {pt.confidence:.2f}",
            )
        )
    html = _ANNOTATE_HTML.format(
        w=layout.viewport_w,
        h=layout.viewport_h,
        b64=base64.b64encode(screenshot_png).decode(),
        markers="".join(markers),
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # A throwaway page in the same context: the live game page must survive.
    render = page.context.new_page()
    try:
        render.set_viewport_size({"width": layout.viewport_w, "height": layout.viewport_h})
        render.set_content(html)
        render.screenshot(path=str(out_path))
    finally:
        render.close()
    return out_path
