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

## Exit criterion

>= 10 recorded demo sessions for one strategy with a `compare()` report against
its Monte Carlo prediction. Collecting those sessions is a human-operated step
(by design); everything up to and including recording + comparison is built and
tested.
