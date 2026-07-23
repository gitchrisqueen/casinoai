#!/usr/bin/env bash
# Collect the FULL H3b dataset: N sessions each for Power Baccarat and Power Pro
# Roulette, then print the claimed vs. simulated vs. live verdict.
#
# TESTING ONLY — FREE / DEMO tables. Each game gets ONE setup pause (reach the
# table, turn ON turbo / turn OFF animations, place one bet), then runs unattended.
# Baccarat runs first, then roulette — you'll be prompted between them.
#
# Usage:  ./scripts/collect_all.sh [sessions]      # default 10 each
#
# Calibrate each table ONCE before the first run:
#   ./scripts/autoplay.sh baccarat "" calibrate
#   ./scripts/autoplay.sh roulette "" calibrate
set -euo pipefail
cd "$(dirname "$0")/.."

N="${1:-10}"

echo "############################################################"
echo "  H3b DATA COLLECTION — $N sessions per strategy"
echo "  FREE / DEMO tables only. Testing purposes."
echo "############################################################"
echo

./scripts/collect_sessions.sh baccarat "$N"

echo
read -r -p "Baccarat done. Press ENTER to start ROULETTE (or Ctrl-C to stop)... " _

./scripts/collect_sessions.sh roulette "$N"

echo
echo "############################################################"
echo "  FINAL: claimed vs. simulated vs. live"
echo "############################################################"
uv run casinoai track
