#!/usr/bin/env bash
# Run ONE human-operated live/demo session for a focus strategy, then update the
# claimed-vs-simulated-vs-live tracking. Roulette (Power Pro) and baccarat
# (Power Baccarat) are supported.
#
# DEMO / FREE-PLAY ONLY. You (a human) open the demo table, place each bet the
# tool prints, and type the winning result back. Nothing wagers real money.
#
# Usage:
#   ./scripts/run_live_session.sh baccarat   [demo-url]
#   ./scripts/run_live_session.sh roulette   [demo-url]
#
# Examples (demo tables; open one in your browser first):
#   ./scripts/run_live_session.sh roulette https://www.roulettesimulator.net/simulators/european-roulette/
#   ./scripts/run_live_session.sh baccarat https://casino.guru/no-commission-baccarat-play-free
set -euo pipefail
cd "$(dirname "$0")/.."

GAME="${1:-roulette}"
URL="${2:-}"

case "$GAME" in
  baccarat)  SPEC="strategies/approved/power-baccarat-v2.yaml" ;;
  roulette)  SPEC="strategies/approved/power-pro-roulette-v2.yaml" ;;
  *) echo "usage: $0 [baccarat|roulette] [demo-url]"; exit 1 ;;
esac

echo "LIVE/DEMO session — $GAME — $SPEC"
echo "Demo/free-play only; you place each bet by hand and type the result."
echo

# Observer mode: opens the demo (if a URL is given) and reads results you type.
if [ -n "$URL" ]; then
  uv run python -m casinoai.live.operator "$SPEC" --url "$URL" --mode manual
else
  uv run python -m casinoai.live.operator "$SPEC" --mode manual
fi

echo
echo "==> Updating claimed vs. simulated vs. live tracking ..."
uv run casinoai track
