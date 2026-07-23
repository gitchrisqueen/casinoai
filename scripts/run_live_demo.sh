#!/usr/bin/env bash
# Run a live/demo observer session: opens the demo game in a visible browser,
# the oracle prints the bet to place, you place it by hand on the demo table
# and type the winning pocket back. Nothing is wagered automatically.
#
# Demo / free-play tables ONLY. This is human-operated by design.
#
# Usage:
#   ./scripts/run_live_demo.sh                          # defaults below
#   ./scripts/run_live_demo.sh <spec.yaml> <demo-url>   # custom spec + table
#   ./scripts/run_live_demo.sh <spec.yaml> <demo-url> auto   # read off the WebSocket
#
# Examples:
#   ./scripts/run_live_demo.sh
#   ./scripts/run_live_demo.sh strategies/approved/power-pro-roulette-v2.yaml \
#       https://www.roulettesimulator.net/simulators/european-roulette/
set -euo pipefail
cd "$(dirname "$0")/.."

SPEC="${1:-strategies/approved/power-pro-roulette-v2.yaml}"
URL="${2:-https://www.roulettesimulator.net/simulators/european-roulette/}"
MODE="${3:-manual}"

echo "Strategy : $SPEC"
echo "Table    : $URL"
echo "Mode     : $MODE   (demo/free-play only; you operate it)"
echo

uv run python -m casinoai.live.operator "$SPEC" --url "$URL" --mode "$MODE"
