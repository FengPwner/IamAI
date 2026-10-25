#!/bin/bash
# IamAI pipeline monitor — checks every 10 minutes, only reports problems.
# Runs in background; writes alerts to /tmp/iamai_monitor_alerts.log

REPO="/root/userdata/workspace/IamAI"
ALERT_LOG="/tmp/iamai_monitor_alerts.log"
INTERVAL=600  # 10 minutes

check_processes() {
    local writer_ok batch_ok
    writer_ok=$(pgrep -f "writer_loop" | head -1)
    batch_ok=$(pgrep -f "commit_batch" | head -1)

    if [ -z "$writer_ok" ] || [ -z "$batch_ok" ]; then
        return 1
    fi
    return 0
}

check_backlog() {
    local count
    count=$(cd "$REPO" && git status --porcelain 2>/dev/null | wc -l)
    if [ "$count" -gt 15 ]; then
        echo "$count"
        return 1
    fi
    return 0
}

while true; do
    sleep "$INTERVAL"

    alerts=""

    if ! check_processes; then
        alerts+="PROCESS_DOWN: "
        [ -z "$(pgrep -f writer_loop)" ] && alerts+="writer_dead "
        [ -z "$(pgrep -f commit_batch)" ] && alerts+="batch_dead "
    fi

    backlog_count=$(check_backlog 2>&1)
    if [ $? -ne 0 ]; then
        alerts+="BACKLOG_HIGH: ${backlog_count} uncommitted files "
    fi

    if [ -n "$alerts" ]; then
        echo "[$(date -Iseconds)] ALERT: $alerts" >> "$ALERT_LOG"
        echo "ALERT: $alerts"
    fi
done
