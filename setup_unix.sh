#!/bin/bash
# setup_unix.sh
# One-click setup for macOS / Linux (crontab)
# Usage: chmod +x setup_unix.sh && ./setup_unix.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="$SCRIPT_DIR/feishu_report.py"
LOG_DIR="$SCRIPT_DIR/logs"

mkdir -p "$LOG_DIR"

# Detect Python
PYTHON_CMD=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null && "$cmd" --version 2>&1 | grep -q "Python 3"; then
        PYTHON_CMD="$cmd"
        break
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo "Error: Python 3 not found. Please install Python 3.8+"
    exit 1
fi
echo "Using Python: $PYTHON_CMD"

# Check lark-cli
if ! command -v lark-cli &>/dev/null; then
    echo "Error: lark-cli not found. Run: npm install -g @larksuite/cli"
    exit 1
fi
echo "lark-cli found"

# Check config file
if [ ! -f "$SCRIPT_DIR/config.json" ]; then
    echo "Error: config.json not found. Copy config.example.json and fill in your settings first."
    exit 1
fi

# Write crontab entries
CRON_DAILY="30 18 * * * $PYTHON_CMD $PYTHON_SCRIPT --mode daily >> $LOG_DIR/daily.log 2>&1"
CRON_WEEKLY="0 15 * * 0 $PYTHON_CMD $PYTHON_SCRIPT --mode weekly >> $LOG_DIR/weekly.log 2>&1"

# Keep existing crontab, remove old entries for this script, append new ones
(crontab -l 2>/dev/null | grep -v "feishu_report.py"; echo "$CRON_DAILY"; echo "$CRON_WEEKLY") | crontab -

echo "✅ Daily report scheduled (every day at 18:30)"
echo "✅ Weekly report scheduled (every Sunday at 15:00)"
echo ""
echo "🎉 Setup complete!"
echo "Test daily report:  $PYTHON_CMD $PYTHON_SCRIPT --mode daily"
echo "Test weekly report: $PYTHON_CMD $PYTHON_SCRIPT --mode weekly"
echo "View daily logs:    tail -f $LOG_DIR/daily.log"
echo ""
echo "Note: macOS users may need to grant 'cron'/'Terminal' Full Disk Access"
echo "in System Settings > Privacy & Security for crontab jobs to run reliably."
