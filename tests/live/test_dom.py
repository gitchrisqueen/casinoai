"""DOM-first control detection and the pixel-rescaling fallback."""

import pytest

from casinoai.live.autoplay import ControlPoint, TableLayout
from casinoai.live.dom import DOM_CANDIDATES, scale_point


def test_scale_point_tracks_a_resized_viewport():
    """The whole point of rescaling: a calibrated pixel must follow the window."""
    # Calibrated at 1280x800, now running at 640x400 (half) -> point halves.
    assert scale_point(1000, 700, 1280, 800, 640, 400) == (500, 350)
    # Same size -> unchanged.
    assert scale_point(100, 200, 1280, 800, 1280, 800) == (100, 200)
    # Degenerate calibration size -> pass through rather than divide by zero.
    assert scale_point(10, 20, 0, 0, 640, 400) == (10, 20)


def test_every_control_has_dom_candidates():
    """Each control we calibrate should at least be *attempted* via the DOM."""
    for name in ("play_for_free", "settings", "turbo", "deal", "spin", "repeat_bet"):
        assert DOM_CANDIDATES.get(name), f"{name} has no DOM candidates"


def test_control_point_defaults_to_pixel_mode():
    pt = ControlPoint(x=1, y=2)
    assert pt.selector == "" and pt.frame_url == ""


@pytest.mark.parametrize("dom_first", [True, False])
def test_driver_prefers_selector_then_falls_back_to_scaled_pixel(dom_first):
    """The click path itself: selector when it resolves, rescaled pixel when not."""
    from casinoai.live import autoplay

    clicked: dict = {}

    class FakeLoc:
        def click(self):
            clicked["via"] = "dom"

    class FakeMouse:
        def click(self, x, y):
            clicked["via"] = "pixel"
            clicked["xy"] = (x, y)

    class FakePage:
        mouse = FakeMouse()
        viewport_size = {"width": 640, "height": 400}  # half of calibration size

        def wait_for_timeout(self, ms):
            pass

    # Patch the DOM resolver to simulate a selector that does / doesn't resolve.
    import casinoai.live.dom as dom_mod

    original = dom_mod.resolve_locator
    dom_mod.resolve_locator = lambda page, sel, frame="": FakeLoc() if dom_first else None
    try:
        layout = TableLayout(name="t", game="roulette", viewport_w=1280, viewport_h=800)
        driver = autoplay.AutoPlayDriver(FakePage(), layout, validate_advance=False)
        driver.click(ControlPoint(x=1000, y=700, selector='button:has-text("Spin")'))
    finally:
        dom_mod.resolve_locator = original

    if dom_first:
        assert clicked["via"] == "dom"
    else:
        assert clicked["via"] == "pixel"
        assert clicked["xy"] == (500, 350)  # rescaled to the smaller viewport


@pytest.mark.llm
def test_find_control_resolves_across_a_cross_origin_iframe():
    """Playwright reaches into iframes, so wrapper chrome is real DOM. Marked llm
    only because it needs the browser extra; it makes no model call."""
    from playwright.sync_api import sync_playwright

    from casinoai.live.dom import find_control

    inner = "<body><button>Play for free</button></body>"
    outer = f'<body><iframe srcdoc=\'{inner}\' width="600" height="300"></iframe></body>'
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(outer)
        hit = find_control(page, "play_for_free")
        browser.close()

    assert hit is not None, "should find the button inside the iframe"
    assert "Play for free" in hit.selector
    assert hit.x > 0 and hit.y > 0


@pytest.mark.llm
def test_find_control_rejects_ambiguous_matches():
    """Two identical buttons must NOT be auto-picked — we'd click the wrong one."""
    from playwright.sync_api import sync_playwright

    from casinoai.live.dom import find_control

    html = "<body><button>Deal</button><button>Deal</button></body>"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(html)
        hit = find_control(page, "deal")
        browser.close()
    assert hit is None
