#!/bin/bash
# ============================================================
# Pull latest code and restart monitor
# Usage: ./deploy/update.sh
# ============================================================

set -euo pipefail

APP_DIR="$HOME/dice-monitor"
PYTHON_BIN="python3.11"

cd "$APP_DIR"

echo "[*] Pulling latest changes..."
git pull

echo "[*] Updating dependencies..."
$PYTHON_BIN -m pip install --user -r requirements.txt

echo "[*] Running test..."
$PYTHON_BIN monitor.py --once 2>&1 | tail -10

echo "[OK] Update complete. Cron will use new code on next run."
