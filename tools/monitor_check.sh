#!/usr/bin/env bash
# IamAI process monitor — check status, only alert if something's wrong
set -uo pipefail

REPO="/root/userdata/workspace/IamAI"
WRITER_ID="qwen"
WRITER_PID="/tmp/iamai-writer-${WRITER_ID}.pid"
BATCH_PID="/tmp/iamai-batch-${WRITER_ID}.pid"

alive() { [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null; }

cd "$REPO" || exit 1

writer_alive=false
batch_alive=false
alive "$WRITER_PID" && writer_alive=true
alive "$BATCH_PID" && batch_alive=true

pending=$(git status --porcelain | wc -l)

# Check if push is needed
local_head=$(git rev-parse HEAD 2>/dev/null)
remote_head=$(git rev-parse origin/main 2>/dev/null || echo "unknown")
needs_push=false
if [ "$local_head" != "$remote_head" ]; then
    needs_push=true
fi

# Determine if alert needed
alert=false
alert_reasons=""

if [ "$writer_alive" = false ]; then
    alert=true
    alert_reasons="${alert_reasons}writer stopped; "
fi
if [ "$batch_alive" = false ]; then
    alert=true
    alert_reasons="${alert_reasons}batch stopped; "
fi
if [ "$pending" -gt 20 ]; then
    alert=true
    alert_reasons="${alert_reasons}backlog=${pending} files; "
fi

if [ "$alert" = true ]; then
    echo "ALERT: ${alert_reasons}"
    echo "pending: ${pending} files"
    echo "writer: $writer_alive  batch: $batch_alive"
    git log --oneline -3
    exit 1
else
    echo "OK: writer=$writer_alive batch=$batch_alive pending=$pending gap=$(python3 tools/heartbeat.py --writer $WRITER_ID 2>/dev/null | grep -o 'gap [0-9]*s' || echo 'unknown')"
    exit 0
fi
