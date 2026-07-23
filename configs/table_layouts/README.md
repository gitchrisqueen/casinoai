# Table layouts (auto-play calibration)

Auto-play drives a FREE/DEMO table by replaying clicks at fixed viewport pixels.
Because these provider games render on a canvas inside cross-origin iframes, the
control positions can't be auto-detected — you calibrate each table **once**:

```bash
uv run python -m casinoai.live.operator strategies/approved/power-baccarat-v2.yaml \
  --url "<demo-url>" --calibrate --layout configs/table_layouts/power-baccarat.yaml
```

Calibration opens the demo, waits for you to reach the betting table, overlays a
coordinate grid, saves a screenshot, and asks for each control's `x,y`. Then:

```bash
uv run python -m casinoai.live.operator strategies/approved/power-baccarat-v2.yaml \
  --url "<demo-url>" --mode autoplay --layout configs/table_layouts/power-baccarat.yaml
```

Notes:
- A layout with an empty `advance` (the stubs here) **refuses to play** until
  calibrated — no blind clicking.
- `advance` is the ordered list of control names clicked each round to place a
  (repeat) bet and deal. Roulette default: `repeat_bet, spin`. Baccarat default:
  `chip_min, player_box, deal`.
- `settle_ms` is how long to wait after the last click for the result to arrive;
  bump it up if the reader times out.
- Physical clicks only advance the demo; the recorded P&L is the strategy applied
  to the real outcomes read off the wire.
- FREE/DEMO tables only. Auto-play prints a TESTING notice and requires a
  free-mode confirmation before it starts.
