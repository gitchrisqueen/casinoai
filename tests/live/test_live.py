"""Live/demo adapter tests — driven by a recorded tape, no browser needed."""

import pytest

from casinoai.backtest.runner import backtest
from casinoai.live import (
    GuardViolation,
    NullBetPlacer,
    RecordedTableReader,
    SessionGuard,
    SessionLimits,
    compare,
    run_live_session,
)
from casinoai.live.playwright_adapter import assert_demo_mode, default_result_parser
from casinoai.live.session import load_sessions, save_session
from tests.rules.test_oracle import martingale_spec

# -- guard -----------------------------------------------------------------------


def test_guard_refuses_non_demo():
    with pytest.raises(GuardViolation, match="demo"):
        SessionGuard(SessionLimits(demo_only=True), is_demo=False)


def test_guard_blocks_oversized_bet():
    guard = SessionGuard(SessionLimits(max_bet_units=4), is_demo=True)

    class B:
        def __init__(self, s):
            self.stake_units = s
            self.bet_type = "red"

    guard.check_bets([B(4)])  # ok
    with pytest.raises(GuardViolation, match="max_bet"):
        guard.check_bets([B(8)])


def test_guard_caps_total_stake():
    guard = SessionGuard(SessionLimits(max_bet_units=10, max_total_stake_units=5), is_demo=True)

    class B:
        def __init__(self, s):
            self.stake_units = s
            self.bet_type = "red"

    with pytest.raises(GuardViolation, match="max_total_stake"):
        guard.check_bets([B(3), B(3)])


def test_guard_session_stops():
    guard = SessionGuard(
        SessionLimits(stop_loss_units=10, stop_win_units=10, max_rounds=5), is_demo=True
    )
    assert guard.check_session(-10, 1) is not None
    assert "stop-loss" in guard.check_session(-11, 1)
    assert "stop-win" in guard.check_session(10, 1)
    assert "max-rounds" in guard.check_session(0, 5)
    assert guard.check_session(-3, 2) is None


# -- session loop ----------------------------------------------------------------


def test_live_session_matches_engine_on_same_tape():
    """The live loop over a fixed pocket tape must reproduce exactly what the
    oracle+engine would compute for that same sequence — sim/live parity."""
    # black=2, red=1 pockets; martingale on red
    pockets = ["2", "2", "2", "1", "2"]  # L L L W L
    spec = martingale_spec(bankroll={"stop_loss_units": 1000, "stop_win_units": 1000})
    reader = RecordedTableReader(pockets)
    placer = NullBetPlacer()
    session = run_live_session(
        spec,
        reader,
        placer,
        SessionLimits(max_bet_units=100, stop_loss_units=1000, max_rounds=100),
        table_url="demo://tape",
        now="2026-07-23T00:00:00Z",
    )
    stakes = [r.bets[0]["stake_units"] for r in session.rounds]
    assert stakes == [1, 2, 4, 8, 1]
    # net: -1-2-4+8-1 = 0
    assert session.net_units == pytest.approx(0.0)
    assert len(session.rounds) == 5  # 5 resolved rounds
    # a 6th bet is placed (martingale after the round-5 loss) but the tape ends
    # before it resolves — realistic: an unresolved demo bet is simply not recorded
    assert [p[0].stake_units for p in placer.placed][:5] == [1, 2, 4, 8, 1]


def test_live_session_guard_stop_loss_overrides_spec():
    """Even with a huge spec stop-loss, the guard halts the session."""
    spec = martingale_spec(bankroll={"stop_loss_units": 100000})
    reader = RecordedTableReader(["2"] * 50)  # all losses
    session = run_live_session(
        spec,
        reader,
        NullBetPlacer(),
        SessionLimits(max_bet_units=100000, max_total_stake_units=100000, stop_loss_units=7),
        now="2026-07-23T00:00:00Z",
    )
    assert "guard stop-loss" in session.stop_reason
    assert session.net_units <= -7


def test_live_session_ends_when_table_unavailable():
    spec = martingale_spec(bankroll={"stop_loss_units": 1000})
    reader = RecordedTableReader(["2", "2"])  # tape runs out
    session = run_live_session(
        spec,
        reader,
        NullBetPlacer(),
        SessionLimits(stop_loss_units=1000, max_bet_units=1000),
        now="2026-07-23T00:00:00Z",
    )
    assert session.stop_reason == "table unavailable"


def test_session_save_and_load(tmp_path):
    spec = martingale_spec()
    session = run_live_session(
        spec,
        RecordedTableReader(["1", "2"]),
        NullBetPlacer(),
        SessionLimits(max_bet_units=100, stop_loss_units=1000),
        now="2026-07-23T00:00:00Z",
    )
    save_session(session, sessions_dir=tmp_path)
    loaded = load_sessions(tmp_path)
    assert len(loaded) == 1
    assert loaded[0].strategy == session.strategy


# -- compare ---------------------------------------------------------------------


def test_compare_live_to_sim():
    spec = martingale_spec(bankroll={"stop_loss_units": 20, "stop_win_units": 10})
    bt = backtest(spec, seeds=list(range(50)), max_rounds=500)
    sessions = [
        run_live_session(
            spec,
            RecordedTableReader([str(p) for p in ([2] * 3 + [1] * 3) * 20]),
            NullBetPlacer(),
            SessionLimits(
                max_bet_units=1000,
                max_total_stake_units=1000,
                stop_loss_units=20,
                stop_win_units=10,
            ),
            now="2026-07-23T00:00:00Z",
        )
    ]
    cmp = compare(sessions, bt)
    assert cmp.live_sessions == 1
    assert cmp.strategy == bt.strategy
    assert "directional" in cmp.note  # < 10 sessions
    assert cmp.sim_ev_per_unit_staked == bt.ev_per_unit_staked


# -- demo-mode safety ------------------------------------------------------------


def test_assert_demo_mode_accepts_demo_and_refuses_real():
    assert_demo_mode("https://x.com/GameLauncher?realMode=0&game=roulette")  # ok
    with pytest.raises(RuntimeError, match="real-money"):
        assert_demo_mode("https://x.com/GameLauncher?realMode=1")
    with pytest.raises(RuntimeError, match="could not confirm"):
        assert_demo_mode("https://x.com/game?foo=bar")


def test_default_result_parser():
    assert default_result_parser({"winningNumber": 17}) == "17"
    assert default_result_parser({"result": "0"}) == "0"
    assert default_result_parser({"chat": "hello"}) is None
    assert default_result_parser({"number": 99}) is None  # out of range


def test_extract_pockets_from_frame():
    from casinoai.live.playwright_adapter import extract_pockets_from_frame

    # nested dict — the winning number is buried inside a game-state message
    frame = '{"type":"spinResult","data":{"round":42,"winningNumber":17}}'
    assert extract_pockets_from_frame(frame) == ["17"]
    # array of messages
    assert extract_pockets_from_frame('[{"result":"0"},{"chat":"hi"}]') == ["0"]
    # non-JSON keepalive frames are ignored
    assert extract_pockets_from_frame("ping") == []
    assert extract_pockets_from_frame('{"heartbeat":true}') == []


def test_extract_pockets_from_socketio_frame():
    """Softswiss/twogameslink 'gpas' games wrap messages in socket.io framing
    like `3:::{...}` (real format captured from the roulettesimulator demo)."""
    from casinoai.live.playwright_adapter import extract_pockets_from_frame

    frame = '3:::{"data":{"_type":"SpinResult","winningNumber":23},"t":123}'
    assert extract_pockets_from_frame(frame) == ["23"]
    # socket.io connect/heartbeat frames carry no result
    assert extract_pockets_from_frame("1::") == []
    assert extract_pockets_from_frame("2::") == []


# -- operator entry point (no browser: capture/auto need --url and refuse real) --


def test_operator_capture_requires_url(capsys):
    from casinoai.live.operator import main

    rc = main(["strategies/approved/power-pro-roulette-v2.yaml", "--mode", "capture"])
    assert rc == 1
    assert "capture mode needs --url" in capsys.readouterr().err


def test_operator_refuses_real_money_url():
    from casinoai.live.operator import _refuse_if_real_money

    _refuse_if_real_money(["https://x.com/game?realMode=0"])  # ok
    with pytest.raises(SystemExit, match="real-money"):
        _refuse_if_real_money(["https://x.com/game?realMode=1"])


def test_operator_default_parser_hits():
    from casinoai.live.operator import default_result_parser_hits

    assert default_result_parser_hits('{"winningNumber":7}')
    assert not default_result_parser_hits("ping")


# -- manual observer reader ------------------------------------------------------


def test_manual_reader_reads_pockets_and_ends():
    from casinoai.live.reader import ManualTableReader

    tape = iter(["17", "0", "q"])
    reader = ManualTableReader(read_fn=lambda _prompt: next(tape))
    assert reader.read_next_spin().pocket == "17"
    assert reader.read_next_spin().pocket == "0"
    assert reader.read_next_spin() is None  # 'q' ends


def test_manual_reader_drives_full_session():
    tape = iter(["2", "2", "1", ""])  # L L W, then end
    from casinoai.live.reader import ManualTableReader

    spec = martingale_spec(bankroll={"stop_loss_units": 1000})
    session = run_live_session(
        spec,
        ManualTableReader(read_fn=lambda _p: next(tape)),
        NullBetPlacer(),
        SessionLimits(max_bet_units=100, max_total_stake_units=100, stop_loss_units=1000),
        now="2026-07-23T00:00:00Z",
    )
    assert [r.outcome for r in session.rounds] == ["2", "2", "1"]
    assert session.stop_reason == "table unavailable"


# -- CLI safety gate -------------------------------------------------------------


def test_cli_live_refuses_without_confirmation(tmp_path, capsys):
    from casinoai.cli import main
    from casinoai.strategies import load_spec, save_spec

    spec = load_spec("strategies/approved/power-pro-roulette-v2.yaml")
    spec_path = save_spec(spec, spec_dir=tmp_path)
    # without the confirmation flag, it must refuse and not start a session
    rc = main(["live", str(spec_path)])
    assert rc == 1
    assert "Refusing to start" in capsys.readouterr().out


# -- baccarat live sessions + tracking -------------------------------------------


def test_baccarat_live_session_records_winners():
    from casinoai.live.reader import RecordedBaccaratReader
    from casinoai.rules.oracle import compile_spec  # noqa: F401
    from tests.rules.test_power_baccarat import pb_spec

    spec = pb_spec()
    # player/banker/tie tape; ties push
    reader = RecordedBaccaratReader(["banker", "player", "tie", "banker", "player"])
    session = run_live_session(
        spec,
        reader,
        NullBetPlacer(),
        SessionLimits(
            max_bet_units=100,
            max_total_stake_units=100,
            stop_loss_units=1000,
            stop_win_units=1000,
            max_rounds=100,
        ),
        now="2026-07-23T00:00:00Z",
    )
    # Tracker selection observes round 1 before betting, so that outcome is
    # consumed but not a recorded bet round.
    assert session.is_demo
    assert len(session.rounds) >= 3
    assert all(r.outcome in ("player", "banker", "tie") for r in session.rounds)


def test_manual_baccarat_reader():
    from casinoai.live.reader import ManualBaccaratReader

    tape = iter(["b", "player", "t", "q"])
    reader = ManualBaccaratReader(read_fn=lambda _p: next(tape))
    assert reader.read_next_spin().winner.value == "banker"
    assert reader.read_next_spin().winner.value == "player"
    assert reader.read_next_spin().winner.value == "tie"
    assert reader.read_next_spin() is None


def test_tracking_joins_claim_sim_and_live(tmp_path):
    from casinoai.backtest.runner import backtest
    from casinoai.discovery.claims import ClaimedMetrics, StrategyClaim
    from casinoai.live.session import save_session
    from casinoai.live.tracker import build_tracking, render_tracking
    from tests.rules.test_oracle import martingale_spec

    spec = martingale_spec(bankroll={"stop_loss_units": 20, "stop_win_units": 10})
    bt = backtest(spec, seeds=list(range(30)), max_rounds=500)
    # one recorded live session
    sess = run_live_session(
        spec,
        RecordedTableReader([str(p) for p in ([2] * 3 + [1] * 3) * 20]),
        NullBetPlacer(),
        SessionLimits(
            max_bet_units=1000, max_total_stake_units=1000, stop_loss_units=20, stop_win_units=10
        ),
        now="2026-07-23T00:00:00Z",
    )
    save_session(sess, sessions_dir=tmp_path)
    claim = StrategyClaim(
        name="Martingale Red",
        source_url="x",
        claimed=ClaimedMetrics(win_rate=0.9, beats_house_edge=True),
    )
    t = build_tracking("Martingale Red", backtest=bt, claim=claim, sessions_dir=tmp_path)
    assert t.live_sessions == 1
    assert t.sim_ev_per_unit == bt.ev_per_unit_staked
    assert t.claimed_win_rate == 0.9
    md = render_tracking([t])
    assert "Martingale Red" in md and "90% win" in md


# -- baccarat auto (WebSocket) parsing -------------------------------------------


def test_default_baccarat_parser():
    from casinoai.live.playwright_adapter import default_baccarat_parser

    assert default_baccarat_parser({"winner": "Player"}) == "player"
    assert default_baccarat_parser({"result": "B"}) == "banker"
    assert default_baccarat_parser({"outcome": "tie"}) == "tie"
    # derive from scores
    assert default_baccarat_parser({"playerScore": 8, "bankerScore": 5}) == "player"
    assert default_baccarat_parser({"playerScore": 3, "bankerScore": 3}) == "tie"
    assert default_baccarat_parser({"chat": "hi"}) is None


def test_extract_winners_from_frame_handles_socketio():
    from casinoai.live.playwright_adapter import extract_winners_from_frame

    # nested + socket.io framing, mirroring the captured roulette format
    frame = '3:::{"data":{"_type":"GameResult","winner":"banker"},"t":9}'
    assert extract_winners_from_frame(frame) == ["banker"]
    assert extract_winners_from_frame('[{"winningSide":"player"},{"chat":"x"}]') == ["player"]
    assert extract_winners_from_frame("2::") == []  # heartbeat, no result


def test_capture_hit_detection_covers_both_games():
    from casinoai.live.operator import default_result_parser_hits

    assert default_result_parser_hits('{"winningNumber":17}')  # roulette
    assert default_result_parser_hits('3:::{"data":{"winner":"tie"}}')  # baccarat
    assert not default_result_parser_hits("ping")


# -- craps live + auto -----------------------------------------------------------


def _passline_craps_spec():
    from casinoai.strategies.spec import StrategySpec

    return StrategySpec.model_validate(
        {
            "name": "Pass Line Flat",
            "game": "craps",
            "summary": "flat pass-line bet every coup",
            "bets": [{"bet_type": "pass_line"}],
            "progression": {"kind": "flat", "units": 1.0},
            "bankroll": {"stop_loss_units": 1000},
        }
    )


def test_craps_live_session_records_line_results():
    from casinoai.live.reader import RecordedCrapsReader

    spec = _passline_craps_spec()
    reader = RecordedCrapsReader(["pass_win", "pass_lose", "dont_push", "pass_win"])
    session = run_live_session(
        spec,
        reader,
        NullBetPlacer(),
        SessionLimits(
            max_bet_units=100, max_total_stake_units=100, stop_loss_units=1000, max_rounds=100
        ),
        now="2026-07-23T00:00:00Z",
    )
    assert [r.outcome for r in session.rounds] == ["pass_win", "pass_lose", "dont_push", "pass_win"]
    # pass line: +1 -1 (push on dont_push -> pass loses its 12) ... net checks accounting
    assert session.net_units == pytest.approx(sum(r.net_units for r in session.rounds))


def test_manual_craps_reader():
    from casinoai.live.reader import ManualCrapsReader

    tape = iter(["w", "lose", "push", "q"])
    reader = ManualCrapsReader(read_fn=lambda _p: next(tape))
    assert reader.read_next_spin().result.value == "pass_win"
    assert reader.read_next_spin().result.value == "pass_lose"
    assert reader.read_next_spin().result.value == "dont_push"
    assert reader.read_next_spin() is None


def test_default_craps_parser_and_frame():
    from casinoai.live.playwright_adapter import (
        default_craps_parser,
        extract_line_results_from_frame,
    )

    assert default_craps_parser({"lineResult": "seven out"}) == "pass_lose"
    assert default_craps_parser({"decision": "PASS"}) == "pass_win"
    assert default_craps_parser({"chat": "hi"}) is None
    frame = '3:::{"data":{"_type":"CoupResult","lineResult":"point_made"}}'
    assert extract_line_results_from_frame(frame) == ["pass_win"]


def test_extract_gpas_opcode45_roulette_result():
    """Softswiss/gpas encodes a spin as a chr(0xFD)-delimited command; opcode 45,
    field[2] = winning pocket (real captured format: 45ý0ý29ý200 -> 29)."""
    from casinoai.live.playwright_adapter import extract_pockets_from_frame

    d = "\xfd"
    frame = (
        '3:::{"correlationId":"r","data":{"gameData":{"commands":['
        f'"42{d}0","45{d}0{d}29{d}200","48{d}0{d}0"]}},"winAmount":200,'
        '"_type":"com.pt.casino.platform.game.GameCommand"}}'
    )
    assert extract_pockets_from_frame(frame) == ["29"]
    # a zero result and the config command (opcode 13100) must not false-match
    frame0 = '3:::{"data":{"gameData":{"commands":["45\xfd0\xfd0\xfd200","13100\xfd0\xfd1.10"]}}}'
    assert extract_pockets_from_frame(frame0) == ["0"]


def test_wire_ws_capture_follows_new_tabs():
    """The game often opens in a second tab; capture must follow it."""
    from casinoai.live.playwright_adapter import wire_ws_capture

    class FakeWS:
        def __init__(self, url):
            self.url = url
            self.handlers = {}

        def on(self, ev, cb):
            self.handlers[ev] = cb

    class FakeCtx:
        def __init__(self):
            self.page_cb = None

        def on(self, ev, cb):
            if ev == "page":
                self.page_cb = cb

    class FakePage:
        def __init__(self, ctx):
            self.context = ctx
            self.ws_cb = None

        def on(self, ev, cb):
            if ev == "websocket":
                self.ws_cb = cb

    got = []
    ctx = FakeCtx()
    page = FakePage(ctx)
    wire_ws_capture(page, got.append)

    # original page's websocket delivers frames
    ws1 = FakeWS("wss://a")
    page.ws_cb(ws1)
    ws1.handlers["framereceived"]("frame-from-page")
    # a NEW TAB opens; its websocket must also be captured
    tab = FakePage(ctx)
    ctx.page_cb(tab)
    ws2 = FakeWS("wss://game-tab")
    tab.ws_cb(ws2)
    ws2.handlers["framereceived"]("frame-from-new-tab")

    assert got == ["frame-from-page", "frame-from-new-tab"]


def test_onetouch_baccarat_result_parsing():
    """Real OneTouch responses captured from casino.guru: the winner is in
    `betAreaOutcomes` (PLAYER/BANKER/TIE + side bets), served over HTTP."""
    from casinoai.live.playwright_adapter import (
        default_baccarat_parser,
        extract_winners_from_frame,
    )

    player_win = (
        '{"gameId":"YIFsK9mQTO01a29d","state":"DEAL_DONE",'
        '"playerCards":[{"card":"4c","handScore":"4"},{"card":"Ks","handScore":"4"}],'
        '"dealerCards":[{"card":"Kd","handScore":"0"},{"card":"3s","handScore":"3"}],'
        '"totalWin":1770.00,"betAreaOutcomes":["PLAYER","BIG"],"win":{"BIG":770,"PLAYER":1000}}'
    )
    banker_win = (
        '{"gameId":"6zu1kThfNeRmOelk","state":"DEAL_DONE",'
        '"playerCards":[{"card":"8d","handScore":"8"}],'
        '"dealerCards":[{"card":"6s","handScore":"9"}],'
        '"totalWin":0,"betAreaOutcomes":["BANKER","SMALL"],"win":{"LUCKY_SIX":0}}'
    )
    # a pre-deal state message carries no result
    no_game = '{"gameId":"x","state":"NO_GAME","config":{"betLimit":{"min":1.0,"max":1000.0}}}'

    assert extract_winners_from_frame(player_win) == ["player"]
    assert extract_winners_from_frame(banker_win) == ["banker"]
    assert extract_winners_from_frame(no_game) == []
    # falls back to card handScores if betAreaOutcomes is ever absent
    cards_only = (
        '{"state":"DEAL_DONE",'
        '"playerCards":[{"card":"9d","handScore":"9"}],'
        '"dealerCards":[{"card":"7s","handScore":"7"}]}'
    )
    assert (
        default_baccarat_parser(
            {"playerCards": [{"handScore": "9"}], "dealerCards": [{"handScore": "7"}]}
        )
        == "player"
    )
    assert extract_winners_from_frame(cards_only) == ["player"]


# -- blackjack live + auto -------------------------------------------------------


def _formula57_spec():
    from casinoai.strategies import load_spec

    return load_spec("strategies/approved/formula-57-blackjack-v2.yaml")


def test_manual_blackjack_reader_tokens():
    from casinoai.live.reader import ManualBlackjackReader

    tape = iter(["w", "loss", "p", "bj", "dw", "dl", "+3", "q"])
    reader = ManualBlackjackReader(read_fn=lambda _p: next(tape))
    assert reader.read_next_spin().net_multiplier == 1.0
    assert reader.read_next_spin().net_multiplier == -1.0
    assert reader.read_next_spin().net_multiplier == 0.0
    bj = reader.read_next_spin()
    assert bj.net_multiplier == 1.5 and bj.player_blackjack  # 3:2, as the engine pays
    dbl = reader.read_next_spin()
    assert dbl.net_multiplier == 2.0 and dbl.total_staked_multiplier == 2.0 and dbl.doubled
    assert reader.read_next_spin().net_multiplier == -2.0
    split = reader.read_next_spin()
    assert split.net_multiplier == 3.0 and split.split  # two hands, one doubled
    assert reader.read_next_spin() is None  # 'q' ends


def test_manual_blackjack_reader_reprompts_on_bad_input(capsys):
    """Unknown input must re-prompt, never crash the operator's session."""
    from casinoai.live.reader import ManualBlackjackReader

    # '21' is a hand total, not a net — no blackjack round can pay more than ±4
    tape = iter(["banana", "21", "-", "w"])
    reader = ManualBlackjackReader(read_fn=lambda _p: next(tape))
    assert reader.read_next_spin().net_multiplier == 1.0
    assert capsys.readouterr().out.count("try again") == 3


def test_blackjack_reader_emits_the_engine_outcome_type():
    """Sim/live parity: the reader must emit exactly what BlackjackEngine.deal()
    emits, so the oracle's settle path cannot tell them apart."""
    from casinoai.engines.blackjack import BlackjackEngine, BlackjackOutcome
    from casinoai.live.reader import RecordedBlackjackReader

    live = RecordedBlackjackReader(["blackjack"]).read_next_spin()
    assert isinstance(live, BlackjackOutcome)
    assert set(live.model_dump()) == set(BlackjackEngine(seed=1).deal().model_dump())
    assert BlackjackEngine.settle("hand", 10, live) == pytest.approx(15.0)


def test_blackjack_live_session_records_nets():
    from casinoai.live.reader import RecordedBlackjackReader

    spec = _formula57_spec()
    # three straight losses take Formula 57 into Rapid Recovery (1,2,4,8,16)
    reader = RecordedBlackjackReader(["loss", "loss", "loss", "win", "push", "blackjack"])
    session = run_live_session(
        spec,
        reader,
        NullBetPlacer(),
        SessionLimits(
            max_bet_units=100, max_total_stake_units=100, stop_loss_units=1000, max_rounds=100
        ),
        now="2026-07-23T00:00:00Z",
    )
    assert [r.outcome for r in session.rounds] == ["-1", "-1", "-1", "+1", "+0", "+1.5"]
    # Foundation 1 -> 1.6 -> 2.6, then Rapid Recovery level 1 after the third loss
    assert [r.bets[0]["stake_units"] for r in session.rounds][:4] == [1.0, 1.6, 2.6, 1.0]
    assert session.net_units == pytest.approx(sum(r.net_units for r in session.rounds))
    assert session.stop_reason == "table unavailable"  # tape ran out


def test_recorded_blackjack_reader_rejects_unknown_result():
    from casinoai.live.reader import RecordedBlackjackReader

    with pytest.raises(ValueError, match="Unknown blackjack result"):
        RecordedBlackjackReader(["surrendered"]).read_next_spin()


def test_default_blackjack_parser_and_frame():
    from casinoai.live.playwright_adapter import (
        default_blackjack_parser,
        extract_blackjack_results_from_frame,
    )

    assert default_blackjack_parser({"handResult": "WIN"}) == "win"
    assert default_blackjack_parser({"result": "player bust"}) == "loss"
    assert default_blackjack_parser({"outcome": "push"}) == "push"
    assert default_blackjack_parser({"playerResult": "blackjack"}) == "blackjack"
    assert default_blackjack_parser({"winner": "dealer"}) == "loss"
    assert default_blackjack_parser({"chat": "hi"}) is None
    # totals alone are NOT inferred — they can't express a double or a split
    assert default_blackjack_parser({"playerTotal": 20, "dealerTotal": 18}) is None

    frame = '3:::{"data":{"_type":"HandResult","handResult":"dealer_bust"}}'
    assert extract_blackjack_results_from_frame(frame) == ["win"]
    assert extract_blackjack_results_from_frame("2::") == []


def test_pragmatic_blackjack_result_is_parsed():
    """casino.guru's 'American Blackjack' is Pragmatic Play ('bjmb', 6-deck S17 BJ
    3:2): it answers over HTTP with a URL-encoded body, settled at end=1 with a
    signed net winN over the base bet betN. These bodies are REAL captures,
    trimmed to their result fields — data/results/live/bj_pragmatic_*.jsonl."""
    from casinoai.live.playwright_adapter import (
        _pragmatic_blackjack_net,
        extract_blackjack_results_from_frame,
    )

    # CAPTURE-VERIFIED: loss (dealer 21), win (dealer bust 25 -> gross win=2.00).
    loss = "sd=21&stat2=2&end=1&win=0.00&win2=-1.00&bet2=1.00&sp2=13&cp2=47,14"
    win = "sd=25&stat2=3&end=1&win=2.00&win2=1.00&bet2=1.00&sp2=11&cp2=44,41"
    assert _pragmatic_blackjack_net(loss) == "loss"
    assert _pragmatic_blackjack_net(win) == "win"
    assert extract_blackjack_results_from_frame(loss) == ["loss"]
    assert extract_blackjack_results_from_frame(win) == ["win"]

    # CAPTURE-VERIFIED: a dealer natural settles on the doInsurance frame; the
    # unrelated 'insbet2' key must not be mistaken for a hand stake.
    dealer_natural = "insbet2=0.00&sd=11/21&stat2=2&end=1&win=0.00&win2=-1.00&bet2=1.00&sp2=12"
    assert _pragmatic_blackjack_net(dealer_natural) == "loss"

    # NOT SETTLED: the deal frame (end=0) carries win2=0.00 but is not a result.
    deal = "sd=6&stat2=1&end=0&win=0.00&win2=0.00&bet2=1.00&sp2=11"
    assert _pragmatic_blackjack_net(deal) is None
    assert extract_blackjack_results_from_frame(deal) == []

    # CAPTURE-VERIFIED double (win=4.00, win2=2.00, bet2=2.00) — documented
    # limitation: betN is the ESCALATED stake, so win2/bet2 collapses the double
    # win to a flat 'win'. Auto-play never doubles, so this never misreports live.
    double_win = "win=4.00&win2=2.00&bet2=2.00&sd=26&sp2=21&stat2=3&end=1"
    assert _pragmatic_blackjack_net(double_win) == "win"

    # push (win2=0.00 at end=1) — not observed in our short live sample, but the
    # win2/bet2 semantics are identical; kept as a formula check, not a capture.
    push = "sd=18&stat2=4&end=1&win=1.00&win2=0.00&bet2=1.00&sp2=18"
    assert _pragmatic_blackjack_net(push) == "push"


def test_playwright_blackjack_reader_buffers_frames():
    """No browser: drive _on_frame directly, as the baccarat test does."""
    from casinoai.live.playwright_adapter import PlaywrightBlackjackReader

    reader = PlaywrightBlackjackReader(page=None)
    reader._on_frame('{"handResult":"win"}')
    reader._on_frame('{"handResult":"push"}')
    assert reader._pending == ["win", "push"]
    assert not reader.is_demo()  # not demo until attach() proves it


def test_operator_wires_blackjack_readers():
    from casinoai.live.operator import _auto_reader_for, _manual_reader_for
    from casinoai.live.playwright_adapter import PlaywrightBlackjackReader
    from casinoai.live.reader import ManualBlackjackReader

    spec = _formula57_spec()
    assert isinstance(_manual_reader_for(spec), ManualBlackjackReader)
    assert isinstance(_auto_reader_for(spec, page=None), PlaywrightBlackjackReader)


def test_capture_hit_detection_covers_blackjack():
    from casinoai.live.operator import default_result_parser_hits

    assert default_result_parser_hits('{"data":{"handResult":"blackjack"}}')


def test_baccarat_reader_dedups_resent_results():
    """OneTouch can re-send the last DEAL_DONE; the reader dedups by gameId so a
    hand isn't counted twice, while distinct hands each register."""
    from casinoai.live.playwright_adapter import PlaywrightBaccaratReader

    reader = PlaywrightBaccaratReader(page=None)  # no browser; drive _on_frame directly
    hand1 = '{"gameId":"AAA","state":"DEAL_DONE","betAreaOutcomes":["PLAYER","BIG"]}'
    hand2 = '{"gameId":"BBB","state":"DEAL_DONE","betAreaOutcomes":["BANKER","SMALL"]}'
    reader._on_frame(hand1)
    reader._on_frame(hand1)  # exact re-send of the same coup -> ignored
    reader._on_frame(hand2)
    reader._on_frame(hand2)  # ditto
    assert reader._pending == ["player", "banker"]
