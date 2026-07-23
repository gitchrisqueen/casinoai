"""Auto-play: pure calibration/advance logic (no browser needed)."""

import pytest

from casinoai.live.autoplay import (
    AdvancingReader,
    ControlPoint,
    LayoutError,
    SilentPlacer,
    TableLayout,
    controls_for,
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
    assert controls_for("roulette") == ["repeat_bet", "spin"]
    assert "deal" in controls_for("baccarat")
    assert "roll" in controls_for("craps")


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
