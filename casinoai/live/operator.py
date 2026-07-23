"""Runnable operator entry point for live/demo sessions (Phase 6, H3b).

    python -m casinoai.live.operator <spec.yaml> --url <demo-url> [--mode ...]

Modes:
  manual  (default) Open the demo game in a VISIBLE browser. You place each bet
          by hand following the printed instructions and type the winning pocket
          in the terminal. Always works; no provider reverse-engineering; the
          most ToS-safe path. This is the "watch it test live" demo.
  auto    Read spin outcomes automatically off the game's WebSocket and feed
          them to the oracle. Needs a parser that matches the provider's message
          format — use `capture` first to discover it.
  capture Open the game and log every WebSocket frame to a file so you can find
          the winning-number message and write/verify a parser. No betting.
  autoplay Hands-free: drive a CALIBRATED demo table to advance each round and
          read outcomes off the wire, so you don't place every bet by hand.
          FREE/DEMO only; prints a TESTING notice and requires a free-mode
          confirmation. Needs --layout (calibrate once with --calibrate).
          Physical clicks only advance the demo; measured P&L is the oracle
          applied to the real outcomes. See casinoai/live/autoplay.py.

Hard rules still apply: demo/free-play only (refuses real-money URLs), human
initiated, hard caps via SessionGuard. Playwright is an optional extra:
    uv sync --extra live && uv run playwright install chromium
"""

import argparse
import json
import re
import sys
from pathlib import Path

from casinoai.live.guard import SessionLimits
from casinoai.live.playwright_adapter import (
    OperatorBetPlacer,
    assert_demo_mode,
)
from casinoai.live.reader import ManualBaccaratReader, ManualCrapsReader, ManualTableReader
from casinoai.live.session import run_live_session, save_session
from casinoai.strategies import load_spec
from casinoai.strategies.spec import GameType


def _manual_reader_for(spec):
    """Observer reader matching the strategy's game (human types outcomes)."""
    if spec.game == GameType.BACCARAT:
        return ManualBaccaratReader()
    if spec.game == GameType.ROULETTE:
        return ManualTableReader()
    if spec.game == GameType.CRAPS:
        return ManualCrapsReader()
    raise SystemExit(
        f"Manual live sessions support roulette, baccarat, craps; {spec.game.value} not yet wired."
    )


REAL_MONEY_SIGNALS = ("realmode=1", "mode=real", "play=real", "/real")


def _require_playwright():
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "Playwright is not installed. Run:\n"
            "  uv sync --extra live && uv run playwright install chromium"
        ) from exc
    from playwright.sync_api import sync_playwright

    return sync_playwright


def _refuse_if_real_money(urls: list[str]) -> None:
    for url in urls:
        low = url.lower()
        if any(s in low for s in REAL_MONEY_SIGNALS):
            raise SystemExit(f"Refusing: a real-money signal was seen in {url}")


def _host(u: str) -> str:
    m = re.match(r"[a-z]+://([^/]+)", u or "")
    return m.group(1) if m else (u or "")[:40]


def _detect_limits_from_capture(path: Path = Path("data/results/live/ws_capture.jsonl")):
    """Best-effort (min, max) bet from a prior capture's provider config."""
    if not path.exists():
        return None
    m = re.search(r'"betLimit":\s*\{\s*"min":\s*([\d.]+),\s*"max":\s*([\d.]+)', path.read_text())
    return (float(m.group(1)), float(m.group(2))) if m else None


def verify_table(spec, chips=None, table_min=None, table_max=None, table_name="", read_fn=input):
    """Check the strategy's required stakes against the live table's chips/limits.
    Prompts the operator for anything not passed as a flag (auto-filling from a
    prior capture's betLimit). Returns the resolved TableProfile to proceed
    (truthy), or None to abort — so the caller can reuse the confirmed chips."""
    from casinoai.live.table import TableProfile, check_table, render_check

    detected = _detect_limits_from_capture()
    if chips is None:
        raw = read_fn("Table chip denominations, comma-separated (e.g. 1,5,25,100,500): ")
        chips = [float(x) for x in (raw or "").replace(" ", "").split(",") if x]
    if not chips:
        print("No chip denominations given — cannot verify table; aborting.", file=sys.stderr)
        return None
    if table_min is None:
        d = f" [{detected[0]:g}]" if detected else ""
        raw = (read_fn(f"Table minimum bet{d}: ") or "").strip()
        table_min = float(raw) if raw else (detected[0] if detected else min(chips))
    if table_max is None:
        d = f" [{detected[1]:g}]" if detected else ""
        raw = (read_fn(f"Table maximum bet{d}: ") or "").strip()
        table_max = float(raw) if raw else (detected[1] if detected else 1e9)

    profile = TableProfile(
        name=_host(table_name) or "table",
        min_bet=table_min,
        max_bet=table_max,
        chip_denominations=sorted(chips),
    )
    check = check_table(spec, profile)
    print("\n" + render_check(spec, profile, check) + "\n")
    if check.ok and not check.dynamic:
        return profile
    ans = (read_fn("Proceed anyway? [y/N]: ") or "").strip().lower()
    return profile if ans in ("y", "yes") else None


def capture(url: str, seconds: int, out_path: Path, headed: bool = True) -> Path:
    """Log the game's result traffic — WebSocket frames AND HTTP/JSON responses,
    across the page and any new tab — to discover the result message format.
    Writes newline-delimited JSON records with a `payload` field."""
    sync_playwright = _require_playwright()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    tabs = {"n": 0}
    hosts: set[str] = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        page = browser.new_page()

        def on_response(resp):
            try:
                rt = resp.request.resource_type
                if rt not in ("xhr", "fetch"):
                    return
                hosts.add(_host(resp.url))
                ctype = (resp.headers or {}).get("content-type", "")
                if "json" not in ctype and "text" not in ctype:
                    return
                body = resp.text()[:2000]
                records.append({"kind": "http", "ws_url": resp.url, "dir": rt, "payload": body})
            except Exception:
                pass

        # Hook every page (current + any new tab/popup) for BOTH transports.
        def hook(pg):
            tabs["n"] += 1

            def on_ws(ws):
                _refuse_if_real_money([ws.url])
                hosts.add(_host(ws.url))
                for ev in ("framereceived", "framesent"):
                    d = "recv" if ev == "framereceived" else "sent"
                    ws.on(
                        ev,
                        lambda payload, d=d, u=ws.url: records.append(
                            {"kind": "ws", "ws_url": u, "dir": d, "payload": str(payload)[:1500]}
                        ),
                    )

            pg.on("websocket", on_ws)
            pg.on("response", on_response)

        hook(page)
        page.context.on("page", hook)
        print(f"Opening {url} — capturing WebSocket + HTTP result traffic for {seconds}s ...")
        print(
            "  (if the game opens in a NEW TAB, that's fine — we follow it. "
            "Click 'Play for free' and play several rounds.)"
        )
        page.goto(url)
        page.wait_for_timeout(seconds * 1000)
        browser.close()

    with out_path.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    ws_n = sum(1 for r in records if r["kind"] == "ws")
    http_n = sum(1 for r in records if r["kind"] == "http")
    hits = [r for r in records if default_result_parser_hits(r["payload"])]
    print(
        f"Captured {ws_n} WS frames + {http_n} HTTP/JSON responses "
        f"across {tabs['n']} tab(s) -> {out_path}"
    )
    print(f"  hosts seen: {', '.join(sorted(hosts)) or '(none)'}")
    print(f"  {len(hits)} record(s) look like they contain a game result:")
    for r in hits[:5]:
        print(f"    [{r['kind']}] {r['ws_url'][:55]} : {r['payload'][:150]}")
    if not records:
        print(
            "  Captured NOTHING — the game tab may not have loaded, or blocks "
            "automation. Try playing more rounds, or a different demo table."
        )
    elif not hits:
        print(
            "  (traffic captured but no result matched — paste a few records "
            "from the file and I'll add a provider-specific parser)"
        )
    return out_path


def default_result_parser_hits(payload: str) -> bool:
    """A frame looks like a result if a roulette pocket, baccarat winner, or
    craps line result can be pulled from it — so `capture` works for any game."""
    from casinoai.live.playwright_adapter import (
        extract_line_results_from_frame,
        extract_pockets_from_frame,
        extract_winners_from_frame,
    )

    return bool(
        extract_pockets_from_frame(payload)
        or extract_winners_from_frame(payload)
        or extract_line_results_from_frame(payload)
    )


def _auto_reader_for(spec, page):
    """WebSocket reader matching the strategy's game."""
    from casinoai.live.playwright_adapter import (
        PlaywrightBaccaratReader,
        PlaywrightCrapsReader,
        PlaywrightRouletteReader,
    )

    if spec.game == GameType.BACCARAT:
        return PlaywrightBaccaratReader(page)
    if spec.game == GameType.ROULETTE:
        return PlaywrightRouletteReader(page)
    if spec.game == GameType.CRAPS:
        return PlaywrightCrapsReader(page)
    raise SystemExit(
        f"Auto live sessions support roulette, baccarat, craps; {spec.game.value} not yet wired."
    )


def _placer_for(spec, chips=None):
    """Bet placer that prints currency + chip stacks (verified stakes), not raw
    units, whenever we know the base unit / table chips."""
    return OperatorBetPlacer(unit_size=spec.bankroll.unit_size or 1.0, chips=chips)


def run_auto(spec_path: str, url: str, limits: SessionLimits, headed: bool = True, chips=None):
    """Read outcomes off the WebSocket automatically and run the oracle loop."""
    sync_playwright = _require_playwright()

    spec = load_spec(spec_path)
    assert_demo_mode(url)  # refuses non-demo up front
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        page = browser.new_page()
        reader = _auto_reader_for(spec, page)
        reader.attach(url)
        session = run_live_session(spec, reader, _placer_for(spec, chips), limits, table_url=url)
        browser.close()
    path = save_session(session)
    _print_summary(session, path)


def run_manual(
    spec_path: str, url: str | None, limits: SessionLimits, headed: bool = True, chips=None
):
    """Open the game (if a URL is given) for the human to watch/play, and read
    winning pockets from the terminal."""
    spec = load_spec(spec_path)
    browser = None
    if url:
        sync_playwright = _require_playwright()
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=not headed)
        page = browser.new_page()
        _refuse_if_real_money([url])
        print(f"Opening {url} — play the demo here; type each winning pocket below.\n")
        page.goto(url)
    try:
        session = run_live_session(
            spec, _manual_reader_for(spec), _placer_for(spec, chips), limits, table_url=url
        )
    finally:
        if browser:
            browser.close()
    path = save_session(session)
    _print_summary(session, path)


def _confirm_free_mode(assume_yes: bool = False, read_fn=input) -> bool:
    """Loud TESTING notice + explicit FREE/DEMO confirmation before auto-play."""
    from casinoai.live.autoplay import TESTING_BANNER, free_mode_confirmed

    print(TESTING_BANNER)
    if assume_yes:
        print("  (--i-am-in-free-mode given; skipping the interactive prompt)\n")
        return True
    ans = read_fn("Type 'YES FREE MODE' to confirm the table is FREE/DEMO: ")
    return free_mode_confirmed(ans)


def run_calibrate(spec_path: str, url: str, layout_path: str, headed: bool = True):
    """One-time table calibration: navigate to the betting table, then record
    each control's coordinates from a grid screenshot."""
    from casinoai.live.autoplay import calibrate

    sync_playwright = _require_playwright()
    assert_demo_mode(url)
    spec = load_spec(spec_path)
    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=not headed)
    try:
        page = browser.new_page()
        page.goto(url)
        input(
            "\nGet the demo to the BETTING TABLE (click 'Play for free', dismiss any "
            "dialogs, place one bet so 'repeat' works), then press ENTER to calibrate..."
        )
        calibrate(page, spec.game.value, name=_host(url), url=url, out_path=layout_path)
    finally:
        browser.close()


def run_autoplay(
    spec_path: str,
    url: str,
    layout_path: str,
    limits: SessionLimits,
    headed: bool = True,
    assume_yes: bool = False,
):
    """Hands-free demo play: drive the calibrated table to advance each round and
    read real outcomes off the wire. FREE/DEMO only, gated by a free-mode
    confirmation; measured P&L is the oracle applied to the real outcomes."""
    from casinoai.live.autoplay import AdvancingReader, AutoPlayDriver, SilentPlacer, load_layout

    if not _confirm_free_mode(assume_yes):
        print("Aborted: FREE/DEMO mode was not confirmed.")
        return 1

    sync_playwright = _require_playwright()
    assert_demo_mode(url)
    spec = load_spec(spec_path)
    layout = load_layout(layout_path)  # raises early if the file is missing
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        page = browser.new_page()
        base = _auto_reader_for(spec, page)
        base.attach(url)
        input(
            "\nGet the demo to the BETTING TABLE (Play for free, place one bet so "
            "'repeat' works), then press ENTER to start AUTO-PLAY..."
        )
        driver = AutoPlayDriver(page, layout)  # validates the layout is playable
        reader = AdvancingReader(base, driver)
        session = run_live_session(spec, reader, SilentPlacer(), limits, table_url=url)
        browser.close()
    path = save_session(session)
    _print_summary(session, path)
    return 0


def _print_summary(session, path):
    print(f"\nSession ended: {session.stop_reason}")
    print(f"  rounds: {len(session.rounds)}  net: {session.net_units:+.1f}u")
    print(f"  saved -> {path}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="casinoai.live.operator")
    ap.add_argument("spec", help="Path to an approved spec YAML")
    ap.add_argument("--url", default=None, help="Demo table URL")
    ap.add_argument("--mode", choices=["manual", "auto", "autoplay", "capture"], default="manual")
    ap.add_argument("--seconds", type=int, default=60, help="capture duration")
    ap.add_argument("--max-bet", type=float, default=8.0)
    ap.add_argument("--max-rounds", type=int, default=200)
    ap.add_argument("--stop-loss", type=float, default=40.0)
    ap.add_argument("--headless", action="store_true", help="Run browser without a window")
    ap.add_argument("--chips", default=None, help="Table chip denominations, e.g. 1,5,25,100,500")
    ap.add_argument("--table-min", type=float, default=None, help="Table minimum bet")
    ap.add_argument("--table-max", type=float, default=None, help="Table maximum bet")
    ap.add_argument("--skip-table-check", action="store_true", help="Skip stake/table verification")
    ap.add_argument("--layout", default=None, help="Calibrated table layout YAML (autoplay)")
    ap.add_argument("--calibrate", action="store_true", help="Calibrate a table layout, then exit")
    ap.add_argument(
        "--i-am-in-free-mode",
        action="store_true",
        help="Confirm FREE/DEMO mode non-interactively (autoplay)",
    )
    args = ap.parse_args(argv)

    limits = SessionLimits(
        max_bet_units=args.max_bet,
        max_total_stake_units=args.max_bet * 2,
        max_rounds=args.max_rounds,
        stop_loss_units=args.stop_loss,
    )
    headed = not args.headless

    if args.mode == "capture":
        if not args.url:
            print("capture mode needs --url", file=sys.stderr)
            return 1
        out = Path("data/results/live/ws_capture.jsonl")
        capture(args.url, args.seconds, out, headed=headed)
        return 0

    if args.calibrate:
        if not (args.url and args.layout):
            print("--calibrate needs --url and --layout", file=sys.stderr)
            return 1
        run_calibrate(args.spec, args.url, args.layout, headed=headed)
        return 0

    # Verify the strategy's stakes fit the table (chips/min/max) before playing.
    chips = [float(x) for x in args.chips.split(",")] if args.chips else None
    if not args.skip_table_check:
        spec = load_spec(args.spec)
        profile = verify_table(
            spec, chips, args.table_min, args.table_max, table_name=args.url or ""
        )
        if profile is None:
            print("Aborted: strategy stakes are not compatible with the table.")
            return 1
        chips = profile.chip_denominations  # reuse the confirmed chips for bet display

    if args.mode == "autoplay":
        if not (args.url and args.layout):
            print("autoplay mode needs --url and a calibrated --layout", file=sys.stderr)
            return 1
        return run_autoplay(
            args.spec,
            args.url,
            args.layout,
            limits,
            headed=headed,
            assume_yes=args.i_am_in_free_mode,
        )
    if args.mode == "auto":
        if not args.url:
            print("auto mode needs --url", file=sys.stderr)
            return 1
        run_auto(args.spec, args.url, limits, headed=headed, chips=chips)
        return 0
    run_manual(args.spec, args.url, limits, headed=headed, chips=chips)
    return 0


if __name__ == "__main__":
    sys.exit(main())
