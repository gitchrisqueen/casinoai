"""DOM-first control detection, with pixel coordinates as the fallback.

Preferred over pixels wherever it works, because a DOM selector is *resolution
independent*: Playwright clicks the element's own centre, so the layout survives
the operator resizing the window, a different display, or the site nudging its
layout. Pixel points only stay correct at the viewport they were calibrated at.

Playwright resolves selectors across cross-origin iframes (it drives the browser
protocol rather than running in-page JS), so the aggregator's wrapper chrome —
'Play for free', cookie/consent dialogs, settings and turbo toggles — is usually
reachable as real DOM. What genuinely isn't reachable is the game surface itself
when it's drawn on a WebGL/canvas: chips and bet spots are pixels, not elements.
Those fall back to vision-proposed coordinates (casinoai.live.vision).

So the calibration order is: DOM first (deterministic, resize-proof) → vision for
whatever is left → manual coordinates for anything still missing.
"""

from __future__ import annotations

# Candidate selectors per control, tried in order. Playwright text engines are
# case-insensitive for :has-text; :text-matches takes an explicit "i" flag.
DOM_CANDIDATES: dict[str, list[str]] = {
    "play_for_free": [
        'button:has-text("Play for free")',
        'a:has-text("Play for free")',
        'button:has-text("Play for fun")',
        'button:has-text("Demo")',
        'a:has-text("Demo play")',
        '[data-testid*="demo" i]',
        'button:text-matches("try (it )?for free", "i")',
    ],
    "close_dialog": [
        'button:has-text("Accept all")',
        'button:has-text("Accept")',
        'button:has-text("I agree")',
        'button:has-text("Continue")',
        '[aria-label="Close" i]',
        'button[aria-label*="close" i]',
        'button:has-text("OK")',
    ],
    "settings": [
        'button[aria-label*="setting" i]',
        '[aria-label*="setting" i]',
        'button:has-text("Settings")',
        'button[aria-label*="menu" i]',
    ],
    "turbo": [
        ':text-matches("turbo", "i")',
        ':text-matches("fast play", "i")',
        ':text-matches("quick spin", "i")',
        ':text-matches("skip animation|disable animation", "i")',
    ],
    "close_settings": [
        '[aria-label="Close" i]',
        'button[aria-label*="close" i]',
        'button:has-text("Done")',
        'button:has-text("Back")',
    ],
    "repeat_bet": [
        'button:has-text("Repeat")',
        'button:has-text("Rebet")',
        'button[aria-label*="repeat" i]',
        'button:has-text("Double")',
    ],
    "spin": ['button:has-text("Spin")', 'button[aria-label*="spin" i]', 'button:has-text("Play")'],
    "deal": ['button:has-text("Deal")', 'button[aria-label*="deal" i]', 'button:has-text("Play")'],
    "roll": ['button:has-text("Roll")', 'button[aria-label*="roll" i]'],
    "player_box": ['[aria-label*="player" i]', ':text-is("PLAYER")', ':text-is("Player")'],
    "pass_line": ['[aria-label*="pass line" i]', ':text-matches("pass line", "i")'],
    "chip_min": ['[aria-label*="chip" i]', '[class*="chip" i]'],
}


class DomHit:
    """A control resolved to a real element: which selector, and in which frame."""

    def __init__(self, selector: str, frame_url: str = "", x: float = 0.0, y: float = 0.0):
        self.selector = selector
        self.frame_url = frame_url
        self.x = x
        self.y = y

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"DomHit({self.selector!r}, frame={self.frame_url!r}, at=({self.x:.0f},{self.y:.0f}))"
        )


def _visible_single(frame, selector: str):
    """The element for `selector` in `frame` if it resolves to exactly one visible
    node — ambiguous or hidden matches are rejected so we never click the wrong
    thing. Returns its bounding box, or None."""
    try:
        loc = frame.locator(selector)
        if loc.count() != 1:
            return None
        if not loc.first.is_visible():
            return None
        return loc.first.bounding_box()
    except Exception:
        return None  # bad selector for this frame / detached / cross-process race


def find_control(page, name: str, candidates: dict[str, list[str]] | None = None) -> DomHit | None:
    """Search every frame for `name`'s first unambiguous candidate selector.
    Returns a DomHit (with the element's current centre, useful for annotating)
    or None if the DOM can't resolve it — e.g. a canvas-drawn chip."""
    for selector in (candidates or DOM_CANDIDATES).get(name, []):
        for frame in page.frames:
            box = _visible_single(frame, selector)
            if box is None:
                continue
            return DomHit(
                selector=selector,
                frame_url=getattr(frame, "url", "") or "",
                x=box["x"] + box["width"] / 2,
                y=box["y"] + box["height"] / 2,
            )
    return None


def resolve_locator(page, selector: str, frame_url: str = ""):
    """Re-resolve a stored selector at click time. Prefers the frame it was
    calibrated in, then any frame — frame URLs often carry volatile session ids,
    so a miss there shouldn't fail the click."""
    frames = list(page.frames)
    if frame_url:
        exact = [f for f in frames if getattr(f, "url", "") == frame_url]
        frames = exact + [f for f in frames if f not in exact]
    for frame in frames:
        try:
            loc = frame.locator(selector)
            if loc.count() >= 1 and loc.first.is_visible():
                return loc.first
        except Exception:
            continue
    return None


def scale_point(x: float, y: float, from_w: int, from_h: int, to_w: int, to_h: int) -> tuple:
    """Rescale a calibrated pixel to the current viewport. Pure, so it's tested:
    it's the whole reason a resized window doesn't silently misclick."""
    if not from_w or not from_h:
        return (x, y)
    return (x * (to_w / from_w), y * (to_h / from_h))
