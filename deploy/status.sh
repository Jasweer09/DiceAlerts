#!/bin/bash
# ============================================================
# Check monitor health and recent activity
# Usage: ./deploy/status.sh
# ============================================================

APP_DIR="$HOME/dice-monitor"
LOG_DIR="$HOME/logs"

echo "============================================================"
echo "  Dice Job Monitor - Status"
echo "============================================================"
echo ""

# Cron status
echo "--- Cron Schedule ---"
crontab -l 2>/dev/null | grep -A1 "dice-monitor" || echo "  [!] No cron entry found"
echo ""

# Last 5 runs from log
echo "--- Last 5 Runs ---"
if [ -f "$LOG_DIR/monitor.log" ]; then
    grep -E "^\[" "$LOG_DIR/monitor.log" | grep -E "Checking Dice|Done\.|ERROR|WARNING" | tail -10
else
    echo "  [!] No log file found at $LOG_DIR/monitor.log"
fi
echo ""

# State files
echo "--- State Files ---"
for f in "$APP_DIR/seen_jobs.json" "$APP_DIR/metrics.json"; do
    if [ -f "$f" ]; then
        SIZE=$(du -h "$f" | cut -f1)
        MOD=$(stat -c '%y' "$f" 2>/dev/null || stat -f '%Sm' "$f" 2>/dev/null)
        echo "  $(basename $f): $SIZE (modified: $MOD)"
    else
        echo "  $(basename $f): not found"
    fi
done
echo ""

# Seen jobs count
if [ -f "$APP_DIR/seen_jobs.json" ]; then
    COUNT=$(python3.11 -c "import json; print(len(json.load(open('$APP_DIR/seen_jobs.json'))))" 2>/dev/null || echo "?")
    echo "  Total tracked jobs: $COUNT"
fi
echo ""

# Disk usage
echo "--- Disk Usage ---"
du -sh "$APP_DIR" 2>/dev/null
echo ""

# Recent errors
echo "--- Recent Errors (last 24h) ---"
if [ -f "$LOG_DIR/monitor.log" ]; then
    grep -i "error\|warning\|rate.limit\|circuit" "$LOG_DIR/monitor.log" | tail -5 || echo "  None"
else
    echo "  No log file"
fi

echo ""
echo "============================================================"
