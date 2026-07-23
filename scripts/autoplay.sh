#!/usr/bin/env bash
# Hands-free auto-play of a FREE/DEMO table to collect live (H3b) sessions fast.
#
# TESTING ONLY. FREE / DEMO tables only. The tool prints a notice and requires
# you to confirm FREE mode before it drives anything. Physical clicks only
# advance the demo; the recorded P&L is the strategy applied to the REAL outcomes.
#
# One-time per table you must CALIBRATE the click positions (canvas games can't be
# auto-detected). Calibrate, then play:
#
#   ./scripts/autoplay.sh <baccarat|roulette> <demo-url> calibrate
#   ./scripts/autoplay.sh <baccarat|roulette> <demo-url> play [chips]
#
# `play` first verifies the strategy's stakes fit the table (min/max/chips), then
# confirms FREE mode, then runs. Layouts live in configs/table_layouts/.
set -euo pipefail
cd "$(dirname "$0")/.."

GAME="${1:-}"
URL="${2:-}"
ACTION="${3:-play}"
CHIPS="${4:-${CHIPS:-}}"

case "$GAME" in
  baccarat) SPEC="strategies/approved/power-baccarat-v2.yaml"; LAYOUT="configs/table_layouts/power-baccarat.yaml" ;;
  roulette) SPEC="strategies/approved/power-pro-roulette-v2.yaml"; LAYOUT="configs/table_layouts/power-pro-roulette.yaml" ;;
  *) echo "usage: $0 <baccarat|roulette> <demo-url> [calibrate|play] [chips]"; exit 1 ;;
esac

if [ -z "$URL" ]; then echo "need a demo URL"; exit 1; fi

if [ "$ACTION" = "calibrate" ]; then
  uv run python -m casinoai.live.operator "$SPEC" --url "$URL" --calibrate --layout "$LAYOUT"
  exit 0
fi

CHIP_ARGS=()
if [ -n "$CHIPS" ]; then CHIP_ARGS=(--chips "$CHIPS"); fi

echo "AUTO-PLAY (TESTING) — $GAME — make sure the table is in FREE mode."
uv run python -m casinoai.live.operator "$SPEC" --url "$URL" --mode autoplay \
  --layout "$LAYOUT" "${CHIP_ARGS[@]}"

echo
echo "==> Updating claimed vs. simulated vs. live tracking ..."
uv run casinoai track
