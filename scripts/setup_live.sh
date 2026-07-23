#!/usr/bin/env bash
# One-time setup for the CasinoAI live/demo adapter (Phase 6).
# Installs the optional Playwright browser dependency.
#
# Usage:  ./scripts/setup_live.sh
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Installing the 'live' extra (Playwright) ..."
uv sync --extra live

echo "==> Installing the Chromium browser Playwright drives ..."
uv run playwright install chromium

echo
echo "Done. You can now run a live/demo session:"
echo "  ./scripts/run_live_demo.sh                 # manual observer, default demo"
echo "  ./scripts/capture_ws.sh <demo-url>         # discover a provider's result format"
