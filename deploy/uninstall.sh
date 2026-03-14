#!/bin/bash
# ============================================================
# Remove monitor cron job and optionally clean up files
# Usage: ./deploy/uninstall.sh
# ============================================================

set -euo pipefail

APP_DIR="$HOME/dice-monitor"
LOG_DIR="$HOME/logs"

echo "[*] Removing cron entry..."
crontab -l 2>/dev/null | grep -v "dice-monitor\|DiceAlerts" | crontab -
echo "[OK] Cron job removed"

echo "[*] Removing logrotate config..."
sudo rm -f /etc/logrotate.d/dice-monitor
echo "[OK] Logrotate removed"

read -p "Delete application files at $APP_DIR? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    rm -rf "$APP_DIR"
    echo "[OK] Application files deleted"
else
    echo "[SKIP] Application files kept at $APP_DIR"
fi

read -p "Delete log files at $LOG_DIR/monitor.log? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    rm -f "$LOG_DIR/monitor.log"*
    echo "[OK] Log files deleted"
else
    echo "[SKIP] Log files kept"
fi

echo ""
echo "[DONE] Monitor uninstalled."
