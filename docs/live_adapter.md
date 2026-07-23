# Live / demo-play adapter (Phase 6, H3b)

Goal: measure whether a strategy performs the way the Monte Carlo backtest
predicts, by playing it against **free-play / demo** casino tables and comparing
observed results to the simulation. This is the H3b half of hypothesis 3.

## Hard rules (enforced in code, not just docs)

- **Demo / free-play only.** `SessionGuard` refuses to run unless the table is
  confirmed in demo mode, and `assert_demo_mode()` refuses any launcher URL that
  looks real-money (`realMode=1`, `mode=real`, …) or that can't be proven demo.
- **Human-initiated.** Sessions start from an operator command; the CLI requires
  an explicit `--i-am-playing-a-free-demo-table` flag.
- **Hard limits, spec-independent.** Max bet, max total stake per round, max
  rounds, and an absolute stop-loss are enforced by the guard regardless of what
  the StrategySpec says — a second backstop the strategy can't widen.
- **No real money, ever. No bot-detection evasion.** The adapter only ever
  stops early; it never presses on, never disguises itself.

## What we learned probing the recommended demos

The recommended free demos (casino.guru's Playzido roulette; roulettesimulator's
European table) render the game on **WebGL/canvas inside nested cross-origin
iframes** (e.g. `roulettesimulator.net` → `dirfxx.com/games/iframe.php` →
`twogameslink.com/GameLauncher?...gameCodeName=gpas_ro_g_pop&realMode=0`). Two
consequences:

1. **The winning number is not DOM text.** Page-level JavaScript can't read it
   (cross-origin), and even inside the frame it's painted on a canvas. Scraping
   visible pixels is fragile.
2. **The robust read is off the wire.** The game exchanges structured result
   messages with the provider backend over a WebSocket. Reading those frames
   (Playwright can, page JS can't) gives the authoritative spin outcome as data.
   `realMode=0` in the launcher URL is a clean, programmatic demo-mode signal.

## Two operating modes

- **Observer (default, recommended, usable today).** The human plays the demo by
  hand following the oracle's printed bet instructions and enters each winning
  pocket. No automation touches the casino — maximally ToS-safe and robust.
  Run it now:

  ```bash
  uv run casinoai live strategies/approved/power-pro-roulette-v2.yaml \
      --table-url "https://casino.guru/casino-roulette-play-free" \
      --i-am-playing-a-free-demo-table
  ```

- **Assisted (later, optional extra `live`).** `PlaywrightRouletteReader` reads
  spin outcomes off the game WebSocket; bet placement can be driven via canvas
  coordinates. Fragile and per-site — enable only with explicit go-ahead per
  table. Install with `uv sync --extra live` and supply a provider-specific
  result parser verified against captured traffic.

## Architecture

The reusable logic is pure and fully unit-tested without a browser:

- `guard.py` — `SessionLimits` + `SessionGuard` (the hard caps).
- `reader.py` — `TableReader`/`BetPlacer` protocols; `RecordedTableReader`
  (tape replay) and `ManualTableReader` (human observer) doubles.
- `session.py` — `run_live_session()`: the guarded decide→place→read→settle→
  record loop, emitting the same `RouletteOutcome` the engines do (so the oracle
  can't tell sim from live). `save_session`/`load_sessions` persist tapes to
  `data/results/live/`.
- `compare.py` — `compare()`: observed live vs. simulated backtest, with a
  z-score of the live session-net mean against the simulated distribution.
- `playwright_adapter.py` — the thin, optional browser binding (WebSocket reader,
  demo-mode assertion, observer bet placer).

## Runnable harness

One-time setup (installs the optional Playwright browser):

```bash
./scripts/setup_live.sh
# equivalently: uv sync --extra live && uv run playwright install chromium
```

Watch it run against a demo table (manual observer — always works, ToS-safe):

```bash
./scripts/run_live_demo.sh
# or a specific strategy + table:
./scripts/run_live_demo.sh strategies/approved/power-pro-roulette-v2.yaml \
    https://www.roulettesimulator.net/simulators/european-roulette/
```

The script opens the demo in a visible browser; the oracle prints the bet to
place; you place it by hand and type the winning pocket back. The session is
recorded to `data/results/live/` and can be fed to `compare()`.

Discover a provider's result-message format (for `auto` mode):

```bash
./scripts/capture_ws.sh https://www.roulettesimulator.net/simulators/european-roulette/ 90
# logs every WebSocket frame to data/results/live/ws_capture.jsonl and flags
# any frame that looks like a winning number
```

### Captured protocol (validated)

Running `capture` against the roulettesimulator European table revealed the
real provider stack: a **socket.io** WebSocket to
`gpas-swisscur.twogameslink.com` (Softswiss's "gpas" platform, which powers a
large share of demo games). Messages are framed like `3:::{json}` and carry a
`_type` discriminator (`InitGameSession`, `GetClientStateResponse`, balance
data showing the demo `amount: 1000000` = €10,000 credits, etc.). The parser
(`extract_pockets_from_frame`) handles that socket.io framing. The actual
result message only appears once a spin is placed (canvas interaction), so
`auto` mode's parser is finalized by capturing one real spin and confirming the
`_type` that carries the winning number.

## Exit criterion

>= 10 recorded demo sessions for one strategy with a `compare()` report against
its Monte Carlo prediction. Collecting those sessions is a human-operated step
(by design); everything up to and including recording + comparison is built and
tested.
