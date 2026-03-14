#!/bin/bash
# ============================================================
# Oracle Cloud Free Tier - Dice Job Monitor Setup
# ============================================================
# Run this script on your Oracle Cloud VM after SSH'ing in:
#   chmod +x deploy/setup.sh && ./deploy/setup.sh
# ============================================================

set -euo pipefail

APP_DIR="$HOME/dice-monitor"
LOG_DIR="$HOME/logs"
PYTHON_MIN="3.11"
REPO_URL="${1:-}"

echo "============================================================"
echo "  Dice Job Monitor - Oracle Cloud Setup"
echo "============================================================"

# ── 1. Detect OS and install Python ────────────────────────────
install_python() {
    if command -v python3.11 &>/dev/null; then
        echo "[OK] Python 3.11 already installed"
        PYTHON_BIN="python3.11"
        return
    fi

    echo "[*] Installing Python 3.11..."

    if [ -f /etc/oracle-linux-release ] || [ -f /etc/redhat-release ]; then
        sudo dnf install -y python3.11 python3.11-pip 2>/dev/null || {
            sudo dnf install -y oracle-epel-release-el8 2>/dev/null || true
            sudo dnf install -y python3.11 python3.11-pip
        }
        PYTHON_BIN="python3.11"
    elif [ -f /etc/debian_version ]; then
        sudo apt update
        sudo apt install -y python3.11 python3.11-venv python3-pip
        PYTHON_BIN="python3.11"
    else
        echo "[ERROR] Unsupported OS. Install Python 3.11+ manually."
        exit 1
    fi

    echo "[OK] Python installed: $($PYTHON_BIN --version)"
}

# ── 2. Set up application directory ────────────────────────────
setup_app() {
    mkdir -p "$APP_DIR" "$LOG_DIR"

    if [ -n "$REPO_URL" ]; then
        echo "[*] Cloning from $REPO_URL..."
        if [ -d "$APP_DIR/.git" ]; then
            cd "$APP_DIR" && git pull
        else
            rm -rf "$APP_DIR"
            git clone "$REPO_URL" "$APP_DIR"
        fi
    else
        echo "[*] No repo URL provided. Copying local files..."
        echo "    Usage: ./setup.sh <git-repo-url>"
        echo "    Or manually copy files to $APP_DIR"
    fi

    cd "$APP_DIR"

    echo "[*] Installing Python dependencies..."
    $PYTHON_BIN -m pip install --user -r requirements.txt

    echo "[OK] Application set up at $APP_DIR"
}

# ── 3. Create .env if not exists ───────────────────────────────
setup_env() {
    if [ -f "$APP_DIR/.env" ]; then
        echo "[OK] .env already exists"
        return
    fi

    echo "[*] Creating .env template..."
    cat > "$APP_DIR/.env" << 'ENVEOF'
# Dice Job Monitor - Oracle Cloud Configuration
# =====================================================

# === REQUIRED ===
DISCORD_ENABLED=true
DISCORD_WEBHOOK_URL=YOUR_WEBHOOK_URL_HERE

# === JOB SEARCH ===
SEARCH_KEYWORDS=Data Analyst,Data Engineer,Business Intelligence Analyst,BI Analyst,BI Developer,Reporting Analyst,Analytics Engineer,CRM Analyst,Salesforce Analyst,Salesforce Administrator,CRM Administrator,Automation Analyst,RPA Developer,ETL Developer,Data Warehouse Engineer,Power BI Developer,Tableau Developer,Marketing Analyst,Operations Analyst,Product Analyst,Financial Data Analyst,SQL Analyst,Process Automation Analyst,HubSpot Analyst
SEARCH_LOCATION=United States

# === DICE-SPECIFIC ===
SEARCH_POSTED_DATE=ONE
SEARCH_PAGE_SIZE=20

# === SEARCH STRATEGY ===
SEARCH_WORKPLACE_TYPES=Remote,On-Site,Hybrid
SEARCH_EMPLOYMENT_TYPES=

# === CONCURRENCY ===
MAX_CONCURRENT_REQUESTS=3
MAX_RETRIES=3
REQUEST_DELAY_SECONDS=3.0

# === FILTERS ===
TITLE_MUST_CONTAIN=
TITLE_EXCLUDE=intern,internship
COMPANY_FILTER=
COMPANY_EXCLUDE=
LOCATION_FILTER=

# === STORAGE ===
SEEN_JOBS_FILE=seen_jobs.json
SEEN_JOBS_RETENTION_DAYS=30
METRICS_FILE=metrics.json

# === ADAPTIVE PAGINATION ===
ENABLE_ADAPTIVE_PAGINATION=true
HIGH_PRIORITY_KEYWORDS=Data Analyst,Data Engineer,BI Analyst,CRM Analyst,Analytics Engineer
HIGH_PRIORITY_PAGES=3
NORMAL_PAGES=2

# === TIME-BASED INTERVALS (for continuous mode) ===
ENABLE_TIME_BASED_INTERVALS=true
BUSINESS_HOURS_START=8
BUSINESS_HOURS_END=18
BUSINESS_HOURS_INTERVAL=5
OFF_HOURS_INTERVAL=10

# === LOGGING ===
LOG_LEVEL=INFO
LOG_FILE=monitor.log
ENVEOF

    echo "[!] IMPORTANT: Edit $APP_DIR/.env and set DISCORD_WEBHOOK_URL"
}

# ── 4. Set up cron job (every 5 minutes) ──────────────────────
setup_cron() {
    local CRON_CMD="*/5 * * * * cd $APP_DIR && $PYTHON_BIN monitor.py --once >> $LOG_DIR/monitor.log 2>&1"

    if crontab -l 2>/dev/null | grep -q "dice-monitor\|DiceAlerts"; then
        echo "[*] Removing existing monitor cron entry..."
        crontab -l 2>/dev/null | grep -v "dice-monitor\|DiceAlerts" | crontab -
    fi

    (crontab -l 2>/dev/null; echo "# dice-monitor: runs every 5 minutes"; echo "$CRON_CMD") | crontab -

    echo "[OK] Cron job installed (every 5 minutes)"
    echo "     Logs at: $LOG_DIR/monitor.log"
}

# ── 5. Set up log rotation ────────────────────────────────────
setup_logrotate() {
    sudo tee /etc/logrotate.d/dice-monitor > /dev/null << LOGEOF
$LOG_DIR/monitor.log {
    daily
    rotate 7
    compress
    missingok
    notifempty
    copytruncate
}
LOGEOF

    echo "[OK] Log rotation configured (7 days, compressed)"
}

# ── 6. Test run ────────────────────────────────────────────────
test_run() {
    echo ""
    echo "============================================================"
    echo "  Running test..."
    echo "============================================================"
    cd "$APP_DIR"
    $PYTHON_BIN monitor.py --once 2>&1 | tail -20
    echo ""
    echo "[OK] Test complete. Check output above for results."
}

# ── Main ───────────────────────────────────────────────────────
install_python
setup_app
setup_env
setup_cron
setup_logrotate

echo ""
echo "============================================================"
echo "  Setup Complete!"
echo "============================================================"
echo ""
echo "  App directory : $APP_DIR"
echo "  Log file      : $LOG_DIR/monitor.log"
echo "  Cron schedule : Every 5 minutes"
echo "  Python        : $PYTHON_BIN"
echo ""
echo "  Next steps:"
echo "  1. Edit .env:  nano $APP_DIR/.env"
echo "     Set DISCORD_WEBHOOK_URL"
echo "  2. Test run:   cd $APP_DIR && $PYTHON_BIN monitor.py --once"
echo "  3. Check logs: tail -f $LOG_DIR/monitor.log"
echo "  4. Verify cron: crontab -l"
echo ""
echo "============================================================"

read -p "Run a test now? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    test_run
fi
