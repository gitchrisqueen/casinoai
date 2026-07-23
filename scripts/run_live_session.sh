#!/usr/bin/env bash
# Run ONE human-operated live/demo session for a focus strategy, then update the
# claimed-vs-simulated-vs-live tracking. Roulette (Power Pro) and baccarat
# (Power Baccarat) are supported.
#
# DEMO / FREE-PLAY ONLY. You (a human) open the demo table, place each bet the
# tool prints, and type the winning result back. Nothing wagers real money.
#
# Usage:
#   ./scripts/run_live_session.sh <baccarat|roulette> [demo-url] [manual|auto]
#
# manual (default): you place bets and type each result (p/b/t or a pocket).
# auto: reads results off the game's WebSocket (you still place the bets).
#       Verify the parser first with ./scripts/capture_ws.sh <demo-url>.
#
# Examples (demo tables; open one in your browser first):
#   ./scripts/run_live_session.sh roulette https://www.roulettesimulator.net/simulators/european-roulette/
#   ./scripts/run_live_session.sh baccarat https://casino.guru/no-commission-baccarat-play-free auto
set -euo pipefail
cd "$(dirname "$0")/.."

GAME="${1:-roulette}"
URL="${2:-}"
MODE="${3:-manual}"

case "$GAME" in
  baccarat)  SPEC="strategies/approved/power-baccarat-v2.yaml" ;;
  roulette)  SPEC="strategies/approved/power-pro-roulette-v2.yaml" ;;
  *) echo "usage: $0 [baccarat|roulette] [demo-url] [manual|auto]"; exit 1 ;;
esac

echo "LIVE/DEMO session — $GAME — $SPEC  (mode: $MODE)"
echo "Demo/free-play only; you place each bet by hand."
echo

if [ "$MODE" = "auto" ] && [ -z "$URL" ]; then
  echo "auto mode needs a demo URL"; exit 1
fi
if [ -n "$URL" ]; then
  uv run python -m casinoai.live.operator "$SPEC" --url "$URL" --mode "$MODE"
else
  uv run python -m casinoai.live.operator "$SPEC" --mode manual
fi

echo
echo "==> Updating claimed vs. simulated vs. live tracking ..."
uv run casinoai track
