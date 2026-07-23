"""Layout registry (URL-keyed) and the LLM calibration merge logic."""

import pytest

from casinoai.live.autoplay import ControlPoint, TableLayout
from casinoai.live.layouts import (
    find_layout,
    layout_id,
    list_layouts,
    mark_stale,
    normalise_url,
    render_registry,
    status_of,
    store_layout,
)
from casinoai.live.vision import (
    ProposedControl,
    VisionProposal,
    build_prompt,
    controls_for_game,
    in_bounds,
    merge_proposal,
)


def test_url_normalisation_ignores_incidentals():
    same = [
        "https://casino.guru/no-commission-baccarat-play-free",
        "http://www.casino.guru/no-commission-baccarat-play-free/",
        "https://CASINO.guru/no-commission-baccarat-play-free?utm=x#frag",
    ]
    ids = {layout_id(u) for u in same}
    assert len(ids) == 1, "the same table must map to one id"
    assert normalise_url(same[0]) == "casino.guru/no-commission-baccarat-play-free"


def test_different_tables_get_different_ids():
    a = layout_id("https://casino.guru/no-commission-baccarat-play-free")
    b = layout_id("https://casino.guru/casino-roulette-play-free")
    assert a != b


def _layout(url, game="baccarat"):
    return TableLayout(
        name="t",
        game=game,
        url=url,
        points={"deal": ControlPoint(x=10, y=20, confirmed=True)},
        advance=["deal"],
    )


def test_store_then_find_by_url(tmp_path):
    url = "https://casino.guru/no-commission-baccarat-play-free"
    store_layout(_layout(url), tmp_path)
    # Found again from a differently-written but equivalent URL.
    got = find_layout("http://www.casino.guru/no-commission-baccarat-play-free/", tmp_path)
    assert got is not None
    assert got.id == layout_id(url)
    assert got.calibrated_at  # stamped on store
    assert status_of(got) == "ready"


def test_find_returns_none_for_uncalibrated_table(tmp_path):
    assert find_layout("https://example.com/never-seen", tmp_path) is None


def test_mark_stale_makes_it_need_recalibration(tmp_path):
    url = "https://casino.guru/casino-roulette-play-free"
    store_layout(_layout(url, "roulette"), tmp_path)
    assert mark_stale(url, tmp_path) is not None
    got = find_layout(url, tmp_path)
    assert got.stale
    assert "STALE" in status_of(got)
    # Unknown table -> nothing to mark.
    assert mark_stale("https://example.com/nope", tmp_path) is None


def test_registry_listing(tmp_path):
    store_layout(_layout("https://a.test/baccarat"), tmp_path)
    store_layout(_layout("https://b.test/roulette", "roulette"), tmp_path)
    assert len(list_layouts(tmp_path)) == 2
    out = render_registry(tmp_path)
    assert "a.test/baccarat" in out and "b.test/roulette" in out
    assert render_registry(tmp_path / "empty").startswith("No calibrated tables")


def test_merge_proposal_keeps_human_confirmed_points():
    """A re-calibration must not silently move a point a human already confirmed."""
    layout = TableLayout(
        name="t",
        game="baccarat",
        points={"deal": ControlPoint(x=10, y=20, source="manual", confirmed=True)},
    )
    proposal = VisionProposal(
        controls=[
            ProposedControl(
                name="deal", found=True, x1=990, y1=990, x2=1008, y2=1008, confidence=0.9
            ),
            ProposedControl(
                name="chip_min", found=True, x1=40, y1=50, x2=60, y2=70, confidence=0.8
            ),
        ]
    )
    written = merge_proposal(layout, proposal, "m")
    assert written == ["chip_min"]
    assert (layout.points["deal"].x, layout.points["deal"].y) == (10, 20)
    assert layout.points["chip_min"].source == "llm"
    assert layout.points["chip_min"].confirmed is False  # needs eyeballing


def test_merge_proposal_rejects_not_found_and_out_of_bounds():
    layout = TableLayout(name="t", game="baccarat", viewport_w=800, viewport_h=400)
    proposal = VisionProposal(
        controls=[
            ProposedControl(name="deal", found=False, x1=0, y1=0, x2=20, y2=20, confidence=0.9),
            ProposedControl(
                name="chip_min", found=True, x1=815, y1=775, x2=835, y2=795, confidence=0.9
            ),
        ]
    )
    assert merge_proposal(layout, proposal, "m") == []
    assert layout.points == {}


def test_in_bounds():
    assert in_bounds(ProposedControl(name="a", found=True, x1=0, y1=0, x2=20, y2=20), 800, 400)
    assert not in_bounds(
        ProposedControl(name="a", found=True, x1=795, y1=5, x2=815, y2=25), 800, 400
    )
    # degenerate box (x2 <= x1) is rejected outright
    assert not in_bounds(
        ProposedControl(name="a", found=True, x1=10, y1=10, x2=10, y2=20), 800, 400
    )


def test_prompt_states_dimensions_and_controls():
    specs = controls_for_game("baccarat", "advance")
    prompt = build_prompt(specs, 1280, 800)
    assert "1280 pixels wide" in prompt and "800 pixels tall" in prompt
    assert "BOUNDING BOX" in prompt
    for s in specs:
        assert s.name in prompt


@pytest.mark.llm
def test_vision_locates_controls_on_a_mock_table(tmp_path):
    """Real vision call: the model must find the advance controls on a mock
    baccarat table, and each point must land inside its target element."""
    from playwright.sync_api import sync_playwright

    from casinoai.live.vision import propose_controls

    html = """<body style="margin:0;width:1280px;height:800px;background:#0b5132">
    <div style="position:absolute;left:240px;top:220px;width:340px;height:180px;
      border:4px solid #ffd54f;color:#ffd54f;font:34px sans-serif;display:flex;
      align-items:center;justify-content:center">PLAYER</div>
    <div style="position:absolute;left:120px;top:660px;width:70px;height:70px;
      background:#fff;border-radius:50%"></div>
    <div style="position:absolute;left:1020px;top:670px;width:180px;height:60px;
      background:#43a047;color:#fff;font:24px sans-serif;display:flex;
      align-items:center;justify-content:center">DEAL</div></body>"""
    # (left, top, right, bottom) of each control
    boxes = {
        "player_box": (240, 220, 580, 400),
        "chip_min": (120, 660, 190, 730),
        "deal": (1020, 670, 1200, 730),
    }
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.set_content(html)
        png = page.screenshot()
        browser.close()

    proposal = propose_controls(png, controls_for_game("baccarat", "advance"), 1280, 800)
    found = {c.name: c for c in proposal.controls if c.found}
    assert set(found) == set(boxes), f"model missed: {set(boxes) - set(found)}"
    for name, (x0, y0, x1, y1) in boxes.items():
        c = found[name]
        assert x0 <= c.x <= x1 and y0 <= c.y <= y1, f"{name} landed outside its control"
