#!/usr/bin/env bash
# Discover a demo game's result-message format: opens the game and logs every
# WebSocket frame to data/results/live/ws_capture.jsonl, flagging any frame that
# looks like it carries a winning number. Use this to write/verify a parser for
# `auto` mode. No betting happens.
#
# Usage:
#   ./scripts/capture_ws.sh <demo-url> [seconds]
#
# Example:
#   ./scripts/capture_ws.sh \
#       https://www.roulettesimulator.net/simulators/european-roulette/ 90
set -euo pipefail
cd "$(dirname "$0")/.."

URL="${1:?usage: ./scripts/capture_ws.sh <demo-url> [seconds]}"
SECONDS_ARG="${2:-60}"

echo "Capturing WebSocket frames from: $URL  (${SECONDS_ARG}s)"
echo "Play a few spins in the browser window so results flow across the wire."
echo

uv run python -m casinoai.live.operator \
  strategies/approved/power-pro-roulette-v2.yaml \
  --url "$URL" --mode capture --seconds "$SECONDS_ARG"
