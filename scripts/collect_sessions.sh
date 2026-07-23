#!/usr/bin/env bash
# Collect the H3b live-demo dataset: N sessions for a focus strategy, hands-free.
#
# TESTING ONLY — FREE / DEMO tables. You confirm FREE mode, and you get ONE setup
# pause (reach the table, turn ON turbo / turn OFF animations, place one bet) before
# it runs unattended. All N sessions run in a SINGLE browser, so you configure the
# game once. Each session is saved separately; tracking is refreshed at the end.
#
# Usage:
#   ./scripts/collect_sessions.sh <baccarat|roulette> [sessions] [demo-url] [chips]
#
# Defaults: 10 sessions, the casino.guru free tables, chips 1,5,25,100,500.
# Requires a one-time calibration first:
#   ./scripts/autoplay.sh <game> "<demo-url>" calibrate
set -euo pipefail
cd "$(dirname "$0")/.."

GAME="${1:-}"
SESSIONS="${2:-10}"
URL="${3:-}"
CHIPS="${4:-${CHIPS:-1,5,25,100,500}}"
# Table limits for the stake check. Override with env if your table differs.
TABLE_MIN="${TABLE_MIN:-1}"
TABLE_MAX="${TABLE_MAX:-1000}"

case "$GAME" in
  baccarat)
    SPEC="strategies/approved/power-baccarat-v2.yaml"
    LAYOUT="configs/table_layouts/power-baccarat.yaml"
    DEFAULT_URL="https://casino.guru/no-commission-baccarat-play-free"
    ;;
  roulette)
    SPEC="strategies/approved/power-pro-roulette-v2.yaml"
    LAYOUT="configs/table_layouts/power-pro-roulette.yaml"
    DEFAULT_URL="https://casino.guru/casino-roulette-play-free"
    ;;
  *)
    echo "usage: $0 <baccarat|roulette> [sessions] [demo-url] [chips]"; exit 1 ;;
esac

URL="${URL:-$DEFAULT_URL}"

# Refuse to start if the table isn't calibrated (uses the real validator, so this
# can't drift from what the driver actually requires).
if ! uv run python -c "
import sys
from casinoai.live.autoplay import load_layout, resolve_advance
try:
    resolve_advance(load_layout('$LAYOUT'))
except Exception as exc:
    print(exc); sys.exit(1)
" 2>/dev/null; then
  echo "!! $LAYOUT is UNCALIBRATED — nothing would be clicked correctly."
  echo "   Calibrate this table once first:"
  echo "     ./scripts/autoplay.sh $GAME \"\" calibrate"
  exit 1
fi

echo "============================================================"
echo " COLLECTING $SESSIONS SESSIONS — $GAME (TESTING / FREE DEMO)"
echo "   spec:   $SPEC"
echo "   table:  $URL"
echo "   layout: $LAYOUT"
echo "============================================================"

uv run python -m casinoai.live.operator "$SPEC" \
  --url "$URL" --mode autoplay --layout "$LAYOUT" \
  --sessions "$SESSIONS" \
  --chips "$CHIPS" --table-min "$TABLE_MIN" --table-max "$TABLE_MAX"

echo
echo "==> Updating claimed vs. simulated vs. live tracking ..."
uv run casinoai track
