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

    def __init__(
        self, selector: str, frame_url: str = "", x: float = 0.0, y: float = 0.0, nth: int = 0
    ):
        self.selector = selector
        self.nth = nth
        self.frame_url = frame_url
        self.x = x
        self.y = y

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"DomHit({self.selector!r}, frame={self.frame_url!r}, at=({self.x:.0f},{self.y:.0f}))"
        )


def _area(b) -> float:
    return float(b["width"]) * float(b["height"])


def _contains(outer, inner, slack: float = 2.0) -> bool:
    return (
        outer["x"] - slack <= inner["x"]
        and outer["y"] - slack <= inner["y"]
        and outer["x"] + outer["width"] + slack >= inner["x"] + inner["width"]
        and outer["y"] + outer["height"] + slack >= inner["y"] + inner["height"]
    )


def best_match(boxes: list) -> int | None:
    """Index of the box to click, or None if the matches are genuinely ambiguous.

    Text selectors match every ANCESTOR containing the text as well as the control
    itself, so several matches is normal and `count() == 1` would reject almost
    everything real. The control is the smallest box; ancestors strictly contain
    it. So: take the smallest, and only bail out if some other match neither
    contains it nor is contained by it — that's two different controls, and
    guessing between them could click the wrong thing. Pure, so it's tested."""
    usable = [(i, b) for i, b in enumerate(boxes) if b and _area(b) > 0]
    if not usable:
        return None
    idx, smallest = min(usable, key=lambda ib: _area(ib[1]))
    for j, b in usable:
        if j == idx:
            continue
        if not _contains(b, smallest) and not _contains(smallest, b):
            return None  # disjoint alternative -> ambiguous
    return idx


def _visible_boxes(frame, selector: str) -> list:
    """Bounding boxes of every visible match, capped so a pathological selector
    can't stall calibration."""
    try:
        loc = frame.locator(selector)
        n = min(loc.count(), 30)
        out = []
        for i in range(n):
            el = loc.nth(i)
            out.append(el.bounding_box() if el.is_visible() else None)
        return out
    except Exception:
        return []  # bad selector for this frame / detached / cross-process race


# Real casino markup rarely uses <button>/<a>. casino.guru's free-play control is
# a <span id="game_link">, and bare text= matches dozens of thumbnail overlays. So
# the second DOM strategy searches for the smallest element that (a) has matching
# text of its own and (b) actually looks clickable (cursor:pointer / role / onclick).
TEXT_PATTERNS: dict[str, str] = {
    "play_for_free": r"play for (free|fun)|demo play|try (it )?for free",
    "close_dialog": r"^(accept all|accept|i agree|got it|continue|ok|close)$",
    "settings": r"^(settings|options)$",
    "turbo": r"turbo|fast play|quick spin|skip animation|disable animation",
    "close_settings": r"^(done|back|close|apply)$",
    "repeat_bet": r"^(repeat|rebet|re-bet)$",
    "spin": r"^spin$",
    "deal": r"^deal$",
    "roll": r"^roll$",
    "player_box": r"^player$",
    "pass_line": r"^pass line$",
}

# Finds the smallest visible, clickable-looking element whose own text matches,
# and returns a stable selector for it (id, unique class, else an nth-child path).
_FIND_CLICKABLE_JS = r"""
(pattern) => {
  const re = new RegExp(pattern, 'i');
  const clickable = (e) => {
    if (['A','BUTTON','INPUT'].includes(e.tagName)) return true;
    if (e.getAttribute('role') === 'button') return true;
    if (e.hasAttribute('onclick')) return true;
    const cls = (e.className || '').toString();
    if (/\b(btn|button|js-)/i.test(cls)) return true;
    try { return getComputedStyle(e).cursor === 'pointer'; } catch { return false; }
  };
  const ownText = (e) => {
    let t = '';
    for (const n of e.childNodes) if (n.nodeType === 3) t += n.textContent;
    return t.trim() || (e.textContent || '').trim();
  };
  const VW = window.innerWidth, VH = window.innerHeight;
  const cands = [];
  for (const e of document.querySelectorAll('*')) {
    if (!e.offsetParent && getComputedStyle(e).position !== 'fixed') continue;
    const r = e.getBoundingClientRect();
    if (r.width < 8 || r.height < 8) continue;
    // Must actually be ON SCREEN. Without this, footer/off-screen text matches
    // (casino.guru has a 'Close' in its footer at y~1800) look like real controls
    // and clicking them scrolls the page and hits something unrelated.
    if (r.bottom <= 0 || r.top >= VH || r.right <= 0 || r.left >= VW) continue;
    const t = ownText(e);
    if (!t || t.length > 60 || !re.test(t)) continue;
    if (!clickable(e)) continue;
    cands.push({e, area: r.width * r.height});
  }
  if (!cands.length) return null;
  cands.sort((a, b) => a.area - b.area);
  const el = cands[0].e;
  const sel = (() => {
    if (el.id) return '#' + CSS.escape(el.id);
    const cls = (el.className || '').toString().trim().split(/\s+/).filter(Boolean);
    for (const c of cls) {
      const s = el.tagName.toLowerCase() + '.' + CSS.escape(c);
      if (document.querySelectorAll(s).length === 1) return s;
    }
    const path = [];
    let cur = el;
    while (cur && cur.nodeType === 1 && path.length < 6) {
      let part = cur.tagName.toLowerCase();
      if (cur.id) { path.unshift('#' + CSS.escape(cur.id)); break; }
      const sibs = cur.parentNode ? Array.from(cur.parentNode.children) : [];
      const same = sibs.filter(s => s.tagName === cur.tagName);
      if (same.length > 1) part += `:nth-of-type(${same.indexOf(cur) + 1})`;
      path.unshift(part);
      cur = cur.parentElement;
    }
    return path.join(' > ');
  })();
  const r = el.getBoundingClientRect();
  return {selector: sel, x: r.x + r.width / 2, y: r.y + r.height / 2};
}
"""


def find_by_clickable_text(frame, pattern: str):
    """Smallest visible clickable element whose own text matches `pattern`."""
    try:
        return frame.evaluate(_FIND_CLICKABLE_JS, pattern)
    except Exception:
        return None


def find_control(page, name: str, candidates: dict[str, list[str]] | None = None) -> DomHit | None:
    """Search every frame for `name`'s first unambiguous candidate selector.
    Returns a DomHit (with the element's current centre, useful for annotating)
    or None if the DOM can't resolve it — e.g. a canvas-drawn chip."""
    for selector in (candidates or DOM_CANDIDATES).get(name, []):
        for frame in page.frames:
            boxes = _visible_boxes(frame, selector)
            idx = best_match(boxes)
            if idx is None:
                continue
            box = boxes[idx]
            return DomHit(
                selector=selector,
                nth=idx,
                frame_url=getattr(frame, "url", "") or "",
                x=box["x"] + box["width"] / 2,
                y=box["y"] + box["height"] / 2,
            )
    # Fallback: clickable-text search, for the non-semantic markup real sites use.
    pattern = TEXT_PATTERNS.get(name)
    if pattern:
        for frame in page.frames:
            hit = find_by_clickable_text(frame, pattern)
            if hit:
                return DomHit(
                    selector=hit["selector"],
                    frame_url=getattr(frame, "url", "") or "",
                    x=hit["x"],
                    y=hit["y"],
                )
    return None


def resolve_locator(page, selector: str, frame_url: str = "", nth: int | None = None):
    """Re-resolve a stored selector at click time. Prefers the frame it was
    calibrated in, then any frame — frame URLs often carry volatile session ids,
    so a miss there shouldn't fail the click. Re-picks the smallest match the same
    way calibration did, rather than blindly taking .first (which is usually a
    page-sized ancestor for text selectors)."""
    frames = list(page.frames)
    if frame_url:
        exact = [f for f in frames if getattr(f, "url", "") == frame_url]
        frames = exact + [f for f in frames if f not in exact]
    for frame in frames:
        boxes = _visible_boxes(frame, selector)
        idx = best_match(boxes)
        if idx is None:
            continue
        try:
            return frame.locator(selector).nth(idx)
        except Exception:
            continue
    return None


def scale_point(x: float, y: float, from_w: int, from_h: int, to_w: int, to_h: int) -> tuple:
    """Rescale a calibrated pixel to the current viewport. Pure, so it's tested:
    it's the whole reason a resized window doesn't silently misclick."""
    if not from_w or not from_h:
        return (x, y)
    return (x * (to_w / from_w), y * (to_h / from_h))
