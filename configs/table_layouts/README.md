# Table layouts (auto-play calibration)

Auto-play drives a FREE/DEMO table by clicking calibrated controls, resolved in
three descending preferences:

1. **DOM selector** — deterministic and **resize-proof**, because Playwright
   clicks the element's own centre. Playwright reaches into cross-origin iframes,
   so the aggregator's chrome ('Play for free', cookie dialogs, settings/turbo) is
   usually real DOM. Auto-confirmed, no eyeballing needed.
2. **Vision-proposed pixel** — for the game surface itself when it's drawn on a
   WebGL/canvas and genuinely has no elements. A vision model proposes the centre,
   markers are drawn on the screenshot, and you confirm by eye.
3. **Manual pixel** — read off a coordinate-grid screenshot, for the remainder.

Pixels are **rescaled to the current viewport** at click time, so resizing the
window degrades gracefully instead of silently misclicking.

Layouts are stored **one file per table, keyed by the game URL**, so you calibrate
a table once and every later run finds it automatically. The filename is a slug of
the URL plus a short hash (`casino-guru-no-commission-baccarat-play-free-1a2b3c4d.yaml`);
equivalent URLs (`http` vs `https`, `www.`, trailing slash, query/fragment) map to
the same file, and different tables never collide.

## Calibrate a table

```bash
./scripts/autoplay.sh baccarat "" calibrate
```

What happens:

1. The **startup** controls (`play_for_free`, `close_dialog`, `settings`, `turbo`,
   `close_settings`) are resolved from the DOM across every frame. Whatever the DOM
   can't reach is sent to the vision model.
2. Vision proposals get markers drawn on the screenshot
   (`data/results/live/calibration/`); you get **one** `[Y/n]` to confirm them all.
   DOM hits skip this — they're already deterministic.
3. The startup sequence is replayed to reach the betting table, where the
   **advance** controls are resolved the same way — roulette `repeat_bet, spin`;
   baccarat `chip_min, player_box, deal`; craps `chip_min, pass_line, roll`.
4. Anything still missing falls back to a labelled coordinate-grid screenshot and
   you type `x,y` — **only for the controls that are still unresolved**.

Ambiguous DOM matches (two identical "Deal" buttons) are rejected rather than
guessed, so a wrong element is never auto-selected.

Because `startup` is calibrated too, later runs click through Play-for-free,
dialogs and the turbo/animation settings on their own — no manual setup per run.

## Check status / re-calibrate

```bash
uv run python -m casinoai.live.operator <spec> --list-layouts
```

Each table reports `ready`, `needs N control(s): ...`, or `STALE — re-calibrate`.
If a site redesigns its game the clicks stop landing, no outcome arrives, and
auto-play **marks the layout STALE automatically** and tells you to re-calibrate.
Re-running calibration keeps every point you previously confirmed and only asks
about the ones that moved or are new.

## Notes

- An uncalibrated (or stale) layout **refuses to play** — no blind clicking.
- `settle_ms` is the wait after the last click for the result; with turbo on,
  lower it with `--settle-ms 1500`. `startup_pause_ms` covers dialog animations.
- Vision model: `--model`, or `CASINOAI_VISION_MODEL`. Default
  `ollama-cloud/minimax-m3` (flat-rate). Measured on a mock table it placed all
  three controls within 9–25px — inside every target — with a slight downward
  bias. `qwen3.5:397b` was consistently ~30–50px off (just outside small targets),
  `gemma4:31b` returned out-of-bounds coordinates, and `glm-5.2` rejects images.
- Physical clicks only advance the demo; recorded P&L is the strategy applied to
  the real outcomes read off the wire.
- FREE/DEMO tables only, behind a free-mode confirmation.

## Blackjack (Formula 57): what works, and why full auto-play does NOT

The blackjack pipeline was validated end-to-end against **Pragmatic Play**
"American Blackjack" on casino.guru (6-deck, dealer stands on 17, blackjack pays
3:2 — the exact rule set `casinoai/engines/blackjack.py` assumes). URL:
`https://casino.guru/free-casino-games/blackjack/American-Blackjack-play-free`
(layout id `casino-guru-free-casino-games-blackjack-merican--a1478588`).

**What is verified and working:**

- **Auto-READ.** Pragmatic answers each action over HTTP with a URL-encoded body
  (`doDeal`/`doStand`/`doDouble`/`doInsurance`), settled at `end=1` with a signed
  net `win2` over the base bet `bet2`. `default_blackjack_parser` /
  `_pragmatic_blackjack_net` in `playwright_adapter.py` decode it; win / loss /
  push / dealer-natural are **capture-verified** (real payloads in
  `tests/live/test_live.py::test_pragmatic_blackjack_result_is_parsed` and
  `data/results/live/bj_pragmatic_*.jsonl`).
- **Manual play** (`--mode manual`) — the human plays and types each result.
- **A saved calibrated layout** — `startup` (Play-for-free → game tab) plus a
  minimal `advance` deal loop (`bet_spot`, `deal`, `stand`).

**Why hands-free AUTO-PLAY of Formula 57 is INFEASIBLE as built:** the auto-play
driver replays a *fixed* click sequence every round. Blackjack is not a fixed
loop — after the deal the player must choose **hit / stand / double / split**
based on their cards and the dealer upcard, and Formula 57 explicitly requires
**basic-strategy** play at every level. The calibrated `advance` can only
`bet_spot → deal → stand`, i.e. it stands on every hand regardless of the cards.
That is a legal way to *advance the demo and read outcomes*, but those outcomes do
**not** come from the strategy's assumed basic-strategy play, so an auto session's
numbers would not measure Formula 57 — they would measure "always stand", a
different (worse) game.

**What full auto-play would additionally require:** a real decision layer that
reads the player's two cards and the dealer upcard off the same result stream (the
Pragmatic body already carries them — `cp2` = player cards, `cd`/`sd` = dealer),
maps them through `_basic_strategy()` (already implemented in
`casinoai/engines/blackjack.py`), and clicks Hit/Stand/Double/Split accordingly —
including handling the mid-hand states (soft totals, post-split hands, the
insurance prompt). None of that click-decision logic exists today, and building it
is a materially larger job than the fixed-loop drivers used for roulette/baccarat.
Until it does, run Formula 57 blackjack in **manual** mode.
