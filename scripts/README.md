# CasinoAI scripts

Helper scripts for **live / demo-play testing** (Phase 6 / H3b) — running a
strategy against a free-play casino table and comparing the results to its
Monte Carlo backtest and its promoter's claims.

> **Hard rules (enforced in code):** demo / free-play tables ONLY. You (a human)
> open the table and place each bet by hand — nothing wagers real money, and the
> tools refuse real-money URLs (`realMode=1`, etc.) and enforce bet/round/
> stop-loss caps regardless of the strategy. See `docs/live_adapter.md`.

## The 3-step flow

```
1. setup (once)        ./scripts/setup_live.sh
2. verify a table      ./scripts/capture_ws.sh <demo-url>      # only if you want AUTO mode
3. run a session       ./scripts/run_live_session.sh <game> <demo-url> [manual|auto]
                       ↳ then it auto-runs `casinoai track` to update the scoreboard
```

## Which script do I want?

| I want to… | Script | When |
|------------|--------|------|
| Install the browser the live tools drive | `setup_live.sh` | **Once**, before anything else |
| Run a session for a **focus strategy** (Power Baccarat / Power Pro) and update tracking | `run_live_session.sh` | **Every session** — this is the one you'll use most |
| Discover/verify how a demo game reports results (needed for `auto` mode) | `capture_ws.sh` | **Once per new demo table**, before using `auto` |
| Run a session for **any** approved spec (not just the two focus ones), or use capture mode inline | `run_live_demo.sh` | Occasionally, for arbitrary strategies |
| **Hands-free** play of a FREE/DEMO table to collect sessions fast | `autoplay.sh` | After a one-time per-table calibration |
| Collect **N sessions** for one strategy in one browser | `collect_sessions.sh` | The H3b dataset, one game at a time |
| Collect the **whole H3b dataset** (both strategies) end to end | `collect_all.sh` | The one-command data run |

**Rule of thumb:** `setup_live.sh` once → `run_live_session.sh` for every session.
Add `capture_ws.sh` once per table only if you want the hands-off `auto` mode.
Use `autoplay.sh` once you've calibrated a table and want it fully hands-free.

---

## setup_live.sh — one-time setup

Installs the optional Playwright browser the live tools drive.

```bash
./scripts/setup_live.sh
```

Run this once. (Equivalent to `uv sync --extra live && uv run playwright install chromium`.)

## run_live_session.sh — run one session (the main one)

Runs a single human-operated demo session for a focus strategy, then refreshes
the claimed-vs-simulated-vs-live tracking table.

```bash
./scripts/run_live_session.sh <baccarat|roulette> [demo-url] [manual|auto] [chips]
```

- **game** — `baccarat` uses Power Baccarat; `roulette` uses Power Pro Roulette.
- **demo-url** — a free-play table to open (optional in `manual` mode; required for `auto`).
- **mode** — `manual` (default): the tool prints each bet to place and you type
  the result (`p`/`b`/`t` for baccarat, a pocket number for roulette, `w`/`l`/`push`
  for craps). `auto`: the tool reads results off the game's WebSocket (you still
  place the bets).
- **chips** — the table's chip denominations, e.g. `1,5,25,100,500` (or set `CHIPS=...`).

**Table check runs first.** Before the session the tool enumerates every stake the
strategy can require and checks each is placeable on this table — at/above the
minimum, at/below the maximum, and composable from the chips — so you never assume
a strategy "works" on a table it can't actually be bet on. If you don't pass
`[chips]` you're prompted (min/max auto-fill from the last `capture_ws.sh` run).
A base unit that doesn't divide the chips is exactly the trap this catches: on a
`5,25,100,500` table with no $1 chip, Power Baccarat's $3 Counterstrike bet is
flagged; on the OneTouch demo (min 1, chips include 1) it passes. Pass
`--skip-table-check` to the operator directly to bypass.

Examples:
```bash
# roulette, manual (type each pocket)
./scripts/run_live_session.sh roulette https://www.roulettesimulator.net/simulators/european-roulette/

# baccarat, auto (reads winners off the wire — verify with capture_ws.sh first)
./scripts/run_live_session.sh baccarat https://casino.guru/no-commission-baccarat-play-free auto 1,5,25,100,500
```

Each session is recorded to `data/results/live/` and folded into `casinoai track`.

## capture_ws.sh — verify a table for AUTO mode

Opens a demo game and logs every WebSocket frame, flagging any that look like a
game result. Use it **once per new demo table** to confirm the result parser
works before running `auto` mode. Not needed for `manual` mode.

```bash
./scripts/capture_ws.sh <demo-url> [seconds]
# e.g.
./scripts/capture_ws.sh https://casino.guru/no-commission-baccarat-play-free 90
```

Play a few rounds in the browser window so results flow. Output goes to
`data/results/live/ws_capture.jsonl`. If it flags result frames, `auto` mode is
good to go; if not, the file shows the raw messages so the provider-specific
parser can be adjusted (a small change in `casinoai/live/playwright_adapter.py`).

## run_live_demo.sh — arbitrary strategy (lower-level)

The general runner: any approved spec, any mode. Use it when you want a strategy
other than the two focus ones, or to invoke `capture` inline.

```bash
./scripts/run_live_demo.sh <spec.yaml> <demo-url> [manual|auto|capture]
# e.g.
./scripts/run_live_demo.sh strategies/approved/mini-max-roulette-v2.yaml \
    https://www.roulettesimulator.net/simulators/european-roulette/
```

## autoplay.sh — hands-free demo play (TESTING ONLY)

Fully automates a **FREE/DEMO** table so you can collect live sessions without
placing every bet by hand. The tool prints a TESTING notice and **requires you to
confirm the table is in FREE mode** before it drives anything. Real-money URLs are
refused, and the same hard bet/round/stop-loss caps apply. Physical clicks only
*advance the demo*; the recorded P&L is the strategy applied to the **real
outcomes** read off the wire — identical measurement to manual play.

Because these games render on a canvas inside cross-origin iframes, the click
positions can't be read from the DOM. Instead a **vision model finds them in a
screenshot** and you just confirm the markers. Each table is calibrated once and
stored **keyed by its URL**, so later runs find it automatically:

```bash
# 1) Calibrate (LLM proposes every control; you confirm, and only fill in misses)
./scripts/autoplay.sh baccarat "" calibrate

# 2) Play hands-free (verifies stakes fit the table, confirms FREE mode, then runs)
./scripts/autoplay.sh baccarat "" play 1,5,25,100,500
```

Calibration also covers the **startup** steps — 'Play for free', dialogs, and the
turbo / disable-animations settings — so every later run clicks through them for
you. An uncalibrated **or stale** layout refuses to run (no blind clicking); if a
site redesign breaks the clicks, auto-play marks the layout STALE and tells you to
re-calibrate, keeping the points you already confirmed.

```bash
# what's calibrated, and is it still good?
uv run python -m casinoai.live.operator strategies/approved/power-baccarat-v2.yaml --list-layouts
```

See [configs/table_layouts/README.md](../configs/table_layouts/README.md) for the
control names, `settle_ms` tuning, and the vision-model comparison.

## collect_sessions.sh / collect_all.sh — the H3b data run

Runs N sessions back-to-back for a strategy in **one browser** with **one setup
pause**, so you configure the game (turbo on, animations off) once — not once per
session. Each session gets a fresh oracle and is saved separately, then a batch
rollup prints and tracking refreshes.

```bash
# one game (default: 10 sessions, default demo URL, chips 1,5,25,100,500)
./scripts/collect_sessions.sh baccarat
./scripts/collect_sessions.sh roulette 10

# both strategies end to end
./scripts/collect_all.sh 10
```

Both refuse to start if the table isn't calibrated. Override the table limits with
`TABLE_MIN=`/`TABLE_MAX=` env vars if your table differs from min 1 / max 1000.

**Setup pause:** before any clicking you get an ENTER prompt. If the table's
startup sequence is calibrated it's replayed for you (Play-for-free, dialogs,
turbo) and you only confirm FREE/DEMO; otherwise you get the manual checklist.
Nothing is clicked until you press ENTER. With turbo on, shorten the post-deal wait:

```bash
uv run python -m casinoai.live.operator strategies/approved/power-baccarat-v2.yaml \
  --url "<url>" --mode autoplay --sessions 10 --settle-ms 1500
```

---

## Game coverage

| Game | Manual | Auto (WebSocket) | Focus strategy |
|------|:---:|:---:|----------------|
| Roulette | ✅ | ✅ | Power Pro Roulette |
| Baccarat | ✅ | ✅ | Power Baccarat |
| Craps | ✅ | ✅ | *(no approved craps strategy yet)* |

Craps readers are wired and tested; point the operator at a craps spec when one
is approved. Blackjack live play isn't wired (its play decisions are the engine's
basic strategy, not observable as a single outcome token).

## Related commands (not scripts, but the payoff)

```bash
uv run casinoai track      # claimed vs. simulated vs. live, per strategy
uv run casinoai report     # backtest leaderboard + H2 conformance matrix
uv run casinoai claims     # Phase 8 discovered-strategy scoreboard
uv run casinoai registry   # strategy dedup registry (identity by mechanics)
```

`casinoai track` is the one to watch: as you log live sessions it fills the live
columns and prints whether observed play lands within the Monte Carlo prediction
(the ≥10-session mark is the H3b bar).
