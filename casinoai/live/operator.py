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

Hard rules still apply: demo/free-play only (refuses real-money URLs), human
initiated, hard caps via SessionGuard. Playwright is an optional extra:
    uv sync --extra live && uv run playwright install chromium
"""

import argparse
import json
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


def capture(url: str, seconds: int, out_path: Path, headed: bool = True) -> Path:
    """Log every WebSocket frame the game exchanges, to discover the result
    message format. Writes newline-delimited JSON: {ws_url, dir, payload}."""
    sync_playwright = _require_playwright()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    frames: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        page = browser.new_page()

        # Capture from the page AND any new tab/popup (the game often opens one).
        def hook(pg):
            def on_ws(ws):
                _refuse_if_real_money([ws.url])
                ws.on(
                    "framereceived",
                    lambda payload: frames.append(
                        {"ws_url": ws.url, "dir": "recv", "payload": str(payload)[:1000]}
                    ),
                )
                ws.on(
                    "framesent",
                    lambda payload: frames.append(
                        {"ws_url": ws.url, "dir": "sent", "payload": str(payload)[:1000]}
                    ),
                )

            pg.on("websocket", on_ws)

        hook(page)
        page.context.on("page", hook)
        print(f"Opening {url} — capturing WebSocket frames for {seconds}s ...")
        print(
            "  (if the game opens in a NEW TAB, that's fine — we follow it. "
            "Click 'Play for free' and play a few rounds.)"
        )
        page.goto(url)
        page.wait_for_timeout(seconds * 1000)
        browser.close()

    with out_path.open("w") as f:
        for fr in frames:
            f.write(json.dumps(fr) + "\n")
    hits = [fr for fr in frames if default_result_parser_hits(fr["payload"])]
    print(f"Captured {len(frames)} frames -> {out_path}")
    print(f"  {len(hits)} frame(s) look like they contain a game result:")
    for fr in hits[:5]:
        print(f"    {fr['ws_url'][:60]} : {fr['payload'][:160]}")
    if not hits:
        print(
            "  (none matched the default parser — inspect the file and write a "
            "provider-specific parser)"
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


def run_auto(spec_path: str, url: str, limits: SessionLimits, headed: bool = True):
    """Read outcomes off the WebSocket automatically and run the oracle loop."""
    sync_playwright = _require_playwright()

    spec = load_spec(spec_path)
    assert_demo_mode(url)  # refuses non-demo up front
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        page = browser.new_page()
        reader = _auto_reader_for(spec, page)
        reader.attach(url)
        session = run_live_session(spec, reader, OperatorBetPlacer(), limits, table_url=url)
        browser.close()
    path = save_session(session)
    _print_summary(session, path)


def run_manual(spec_path: str, url: str | None, limits: SessionLimits, headed: bool = True):
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
            spec, _manual_reader_for(spec), OperatorBetPlacer(), limits, table_url=url
        )
    finally:
        if browser:
            browser.close()
    path = save_session(session)
    _print_summary(session, path)


def _print_summary(session, path):
    print(f"\nSession ended: {session.stop_reason}")
    print(f"  rounds: {len(session.rounds)}  net: {session.net_units:+.1f}u")
    print(f"  saved -> {path}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="casinoai.live.operator")
    ap.add_argument("spec", help="Path to an approved spec YAML")
    ap.add_argument("--url", default=None, help="Demo table URL")
    ap.add_argument("--mode", choices=["manual", "auto", "capture"], default="manual")
    ap.add_argument("--seconds", type=int, default=60, help="capture duration")
    ap.add_argument("--max-bet", type=float, default=8.0)
    ap.add_argument("--max-rounds", type=int, default=200)
    ap.add_argument("--stop-loss", type=float, default=40.0)
    ap.add_argument("--headless", action="store_true", help="Run browser without a window")
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
    if args.mode == "auto":
        if not args.url:
            print("auto mode needs --url", file=sys.stderr)
            return 1
        run_auto(args.spec, args.url, limits, headed=headed)
        return 0
    run_manual(args.spec, args.url, limits, headed=headed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
