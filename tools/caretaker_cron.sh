#!/usr/bin/env bash
# caretaker_cron.sh — 10-minute caretaker check
# Checks writer/batch processes, commits pending changes, pushes,
# and writes a status line to /tmp/caretaker_cron.log

set -euo pipefail
cd "$(dirname "$0")/.."

LOG="/tmp/caretaker_cron.log"
ts=$(date '+%Y-%m-%d %H:%M:%S')

# Check processes
WRITER_PID=$(pgrep -f 'writer_loop.py.*--writer qwen' || true)
BATCH_PID=$(pgrep -f 'commit_batch.py.*--writer qwen' || true)

NEEDS_RESTART=false
if [ -z "$WRITER_PID" ]; then
    echo "[$ts] writer NOT running" >> "$LOG"
    NEEDS_RESTART=true
fi
if [ -z "$BATCH_PID" ]; then
    echo "[$ts] batch NOT running" >> "$LOG"
    NEEDS_RESTART=true
fi

# Restart if needed
if [ "$NEEDS_RESTART" = true ]; then
    echo "[$ts] restarting via tools/run_both.sh" >> "$LOG"
    bash tools/run_both.sh >> "$LOG" 2>&1
    sleep 2
fi

# Check for uncommitted changes
PENDING=$(git status --porcelain | wc -l)
if [ "$PENDING" -gt 0 ]; then
    echo "[$ts] $PENDING pending files, committing" >> "$LOG"
    git add -A
    git commit -m "catch-up: commit pending changes (caretaker cron)" \
        --author="Qwen <qwen@iamai.local>" >> "$LOG" 2>&1
fi

# Push any unpushed commits
UNPUSHED=$(git log origin/main..HEAD --oneline 2>/dev/null | wc -l)
if [ "$UNPUSHED" -gt 0 ]; then
    echo "[$ts] $UNPUSHED unpushed commits, pushing" >> "$LOG"
    git push origin main >> "$LOG" 2>&1
fi

echo "[$ts] OK — writer=$(pgrep -f 'writer_loop.py.*--writer qwen' || echo DOWN) batch=$(pgrep -f 'commit_batch.py.*--writer qwen' || echo DOWN) pending=$(git status --porcelain | wc -l)" >> "$LOG"
