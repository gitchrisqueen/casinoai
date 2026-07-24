"""Auto-play: pure calibration/advance logic (no browser needed)."""

import pytest

from casinoai.live.autoplay import (
    AdvancingReader,
    ControlPoint,
    LayoutError,
    SilentPlacer,
    TableLayout,
    free_mode_confirmed,
    load_layout,
    resolve_advance,
    save_layout,
)


def test_free_mode_confirmation_is_explicit():
    assert free_mode_confirmed("YES FREE MODE")
    assert free_mode_confirmed(" yes free mode ")
    assert free_mode_confirmed("I am in free mode")
    # Anything else must NOT confirm — no accidental auto-play.
    for bad in ("", "y", "yes", "ok", "sure", "real", "no"):
        assert not free_mode_confirmed(bad)


def test_resolve_advance_returns_click_sequence():
    layout = TableLayout(
        name="t",
        game="baccarat",
        points={
            "chip_min": ControlPoint(x=100, y=700),
            "player_box": ControlPoint(x=400, y=300),
            "deal": ControlPoint(x=1100, y=700),
        },
        advance=["chip_min", "player_box", "deal"],
    )
    seq = resolve_advance(layout)
    assert [(p.x, p.y) for p in seq] == [(100, 700), (400, 300), (1100, 700)]


def test_uncalibrated_layout_refuses_to_play():
    empty = TableLayout(name="t", game="roulette")  # no advance
    with pytest.raises(LayoutError):
        resolve_advance(empty)


def test_advance_referencing_unmapped_control_is_rejected():
    layout = TableLayout(
        name="t",
        game="roulette",
        points={"spin": ControlPoint(x=1, y=2)},
        advance=["repeat_bet", "spin"],  # repeat_bet not mapped
    )
    with pytest.raises(LayoutError) as exc:
        resolve_advance(layout)
    assert "repeat_bet" in str(exc.value)


def test_layout_round_trips_through_yaml(tmp_path):
    layout = TableLayout(
        name="casino.guru",
        game="baccarat",
        url="https://casino.guru/x",
        points={"deal": ControlPoint(x=10, y=20, note="deal")},
        advance=["deal"],
        settle_ms=3000,
    )
    p = save_layout(layout, tmp_path / "layout.yaml")
    back = load_layout(p)
    assert back == layout


def test_controls_per_game():
    from casinoai.live.vision import controls_for_game

    adv = [s.name for s in controls_for_game("roulette", "advance")]
    assert adv == ["repeat_bet", "spin"]
    assert "deal" in [s.name for s in controls_for_game("baccarat", "advance")]
    assert "roll" in [s.name for s in controls_for_game("craps", "advance")]
    # Startup controls are shared across games and drive the hands-free start.
    startup = [s.name for s in controls_for_game("roulette", "startup")]
    assert "play_for_free" in startup and "turbo" in startup


def test_startup_sequence_may_be_empty_but_must_be_mapped():
    from casinoai.live.autoplay import resolve_startup

    ok = TableLayout(name="t", game="roulette")
    assert resolve_startup(ok) == []  # no startup is legitimate

    bad = TableLayout(name="t", game="roulette", startup=["play_for_free"])
    with pytest.raises(LayoutError):
        resolve_startup(bad)


def test_needs_attention_flags_missing_and_low_confidence():
    from casinoai.live.autoplay import ControlPoint as CP
    from casinoai.live.autoplay import needs_attention

    layout = TableLayout(
        name="t",
        game="roulette",
        points={
            "repeat_bet": CP(x=1, y=1, source="llm", confidence=0.2, confirmed=False),
            "spin": CP(x=2, y=2, source="llm", confidence=0.9, confirmed=False),
            "play_for_free": CP(x=3, y=3, source="manual", confidence=0.1, confirmed=True),
        },
        startup=["play_for_free", "turbo"],
        advance=["repeat_bet", "spin"],
    )
    pending = needs_attention(layout)
    assert "turbo" in pending  # referenced but missing
    assert "repeat_bet" in pending  # unconfirmed + weak confidence
    assert "spin" not in pending  # unconfirmed but confident
    assert "play_for_free" not in pending  # human-confirmed wins


def test_advancing_reader_advances_once_then_reads():
    calls = []

    class FakeDriver:
        def advance(self):
            calls.append("advance")

    class FakeBase:
        def is_demo(self):
            return True

        def read_next_spin(self):
            calls.append("read")
            return "outcome"

    reader = AdvancingReader(FakeBase(), FakeDriver())
    assert reader.is_demo() is True
    assert reader.read_next_spin() == "outcome"
    # advance strictly precedes the read, exactly once each.
    assert calls == ["advance", "read"]


def test_batch_summary_reports_every_session(capsys):
    """The N-session batch rollup is what we read after a collection run."""
    from casinoai.live.operator import _print_batch_summary

    class S:
        def __init__(self, net, n):
            self.net_units = net
            self.rounds = [None] * n

    _print_batch_summary([S(+3.0, 20), S(-5.5, 18), S(+1.25, 22)])
    out = capsys.readouterr().out
    assert "3 sessions, 60 rounds" in out
    assert "winning sessions: 2/3" in out
    assert "-1.2u" in out  # total net +3 -5.5 +1.25 = -1.25
    assert "settle" not in out


def test_silent_placer_records_intended_bet():
    from types import SimpleNamespace

    lines: list[str] = []
    SilentPlacer(printer=lines.append).place_bets(
        [SimpleNamespace(stake_units=1.2, bet_type="player")]
    )
    assert "1.2u on player" in lines[0]


def test_game_controls_include_game_settings_in_click_order():
    """Regression: game_settings was defined as a control but left out of
    _GAME_CONTROLS, so re-calibration silently dropped it from startup and the
    turbo click then fired before its settings panel existed."""
    from casinoai.live.operator import _GAME_CONTROLS

    assert "game_settings" in _GAME_CONTROLS
    order = list(_GAME_CONTROLS)
    assert order.index("settings") < order.index("game_settings") < order.index("turbo")
    assert order.index("turbo") < order.index("close_settings")


def test_unresolvable_dom_point_is_skipped_not_clicked_at_origin():
    """A DOM point carries no real pixel (0,0). If its selector doesn't resolve we
    must skip, not fall through and click the top-left corner."""
    import casinoai.live.dom as dom_mod
    from casinoai.live import autoplay

    clicked = []

    class FakeMouse:
        def click(self, x, y):
            clicked.append((x, y))

    class FakePage:
        mouse = FakeMouse()
        viewport_size = {"width": 1280, "height": 800}

        def wait_for_timeout(self, ms):
            pass

    original = dom_mod.resolve_locator
    dom_mod.resolve_locator = lambda page, sel, frame="": None  # never resolves
    try:
        layout = TableLayout(name="t", game="baccarat")
        driver = autoplay.AutoPlayDriver(FakePage(), layout, validate_advance=False)
        driver.click(ControlPoint(x=0, y=0, selector="li#settings", note="game_settings"))
        assert clicked == [], "must not click (0,0)"
        # A point with a real pixel still falls back to it.
        driver.click(ControlPoint(x=500, y=400, selector="li#nope"))
        assert clicked == [(500, 400)]
    finally:
        dom_mod.resolve_locator = original
