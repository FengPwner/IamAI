#!/usr/bin/env bash
# Background caretaker daemon: runs every 10 minutes
# Usage: nohup bash tools/caretaker_daemon.sh > /tmp/iamai-caretaker-daemon.log 2>&1 &

set -uo pipefail

REPO="/root/userdata/workspace/IamAI"
INTERVAL=600  # 10 minutes

while true; do
    echo "$(date -Iseconds) Starting caretaker check"
    bash "$REPO/tools/caretaker_10min.sh"
    echo "$(date -Iseconds) Sleeping $INTERVAL seconds"
    sleep "$INTERVAL"
done
