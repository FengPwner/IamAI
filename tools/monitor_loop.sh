#!/usr/bin/env bash
# Background monitor loop — check every 10 min, only output on problems
set -uo pipefail

REPO="/root/userdata/workspace/IamAI"
WRITER_ID="qwen"
WRITER_PID="/tmp/iamai-writer-${WRITER_ID}.pid"
BATCH_PID="/tmp/iamai-batch-${WRITER_ID}.pid"
INTERVAL=600  # 10 minutes
ALERT_FILE="/tmp/iamai-monitor-alerts.log"

alive() { [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null; }

echo "[$(date -u +%H:%M:%S)] monitor started, interval ${INTERVAL}s" >> "$ALERT_FILE"

while true; do
    sleep "$INTERVAL"
    cd "$REPO" || continue

    writer_alive=false
    batch_alive=false
    alive "$WRITER_PID" && writer_alive=true
    alive "$BATCH_PID" && batch_alive=true

    pending=$(git status --porcelain | wc -l)
    
    # Try auto-restart if both stopped
    if [ "$writer_alive" = false ] || [ "$batch_alive" = false ]; then
        echo "[$(date -u +%H:%M:%S)] RESTART needed: writer=$writer_alive batch=$batch_alive pending=$pending" >> "$ALERT_FILE"
        bash "$REPO/tools/run_both.sh" >> "$ALERT_FILE" 2>&1
        
        # Commit and push any backlog
        cd "$REPO"
        if [ "$(git status --porcelain | wc -l)" -gt 0 ]; then
            git add -A
            git commit -m "monitor: auto-restart catch-up $(date -u +%H:%M)" >> "$ALERT_FILE" 2>&1
        fi
        git pull --no-rebase origin main >> "$ALERT_FILE" 2>&1
        git push origin main >> "$ALERT_FILE" 2>&1
        echo "[$(date -u +%H:%M:%S)] RESTART done" >> "$ALERT_FILE"
    else
        # Auto-push if there are unpushed commits
        local_head=$(git rev-parse HEAD 2>/dev/null)
        remote_head=$(git rev-parse origin/main 2>/dev/null || echo "unknown")
        if [ "$local_head" != "$remote_head" ]; then
            git pull --no-rebase origin main >> "$ALERT_FILE" 2>&1
            git push origin main >> "$ALERT_FILE" 2>&1
        fi
    fi
done
