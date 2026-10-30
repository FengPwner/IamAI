#!/usr/bin/env bash
# Caretaker loop: check writer/batch health every 10 minutes
# - Restart if dead
# - Commit any pending changes
# - Attempt push (will fail if SSH is broken, but that's logged)

set -uo pipefail

REPO="/root/userdata/workspace/IamAI"
LOG="/tmp/iamai-caretaker.log"
LOCKFILE="/tmp/iamai-caretaker.lock"

# Prevent concurrent runs
if [ -f "$LOCKFILE" ]; then
    if kill -0 "$(cat "$LOCKFILE" 2>/dev/null)" 2>/dev/null; then
        echo "$(date -Iseconds) Previous caretaker still running, skipping" >> "$LOG"
        exit 0
    fi
fi
echo $$ > "$LOCKFILE"

log() { echo "$(date -Iseconds) $*" >> "$LOG"; }

cd "$REPO" || { log "cannot cd to $REPO"; exit 1; }

# Check if writer and batch are running
WRITER_PID="/tmp/iamai-writer-qwen.pid"
BATCH_PID="/tmp/iamai-batch-qwen.pid"

writer_alive() { [ -f "$WRITER_PID" ] && kill -0 "$(cat "$WRITER_PID")" 2>/dev/null; }
batch_alive() { [ -f "$BATCH_PID" ] && kill -0 "$(cat "$BATCH_PID")" 2>/dev/null; }

needs_restart=false

if ! writer_alive; then
    log "writer dead, needs restart"
    needs_restart=true
fi

if ! batch_alive; then
    log "batch dead, needs restart"
    needs_restart=true
fi

# Restart if needed
if [ "$needs_restart" = true ]; then
    log "restarting writer and batch"
    bash tools/run_both.sh --stop 2>&1 | tee -a "$LOG"
    sleep 2
    bash tools/run_both.sh 2>&1 | tee -a "$LOG"
fi

# Commit any pending changes
pending=$(git status --porcelain | wc -l)
if [ "$pending" -gt 0 ]; then
    log "committing $pending pending file(s)"
    git add -A
    git commit -m "caretaker: auto-commit $(date '+%Y-%m-%d %H:%M')" 2>&1 | tee -a "$LOG"
fi

# Attempt push (may fail if SSH is broken)
unpushed=$(git log origin/main..HEAD --oneline 2>/dev/null | wc -l)
if [ "$unpushed" -gt 0 ]; then
    log "pushing $unpushed unpushed commit(s)"
    git push origin main 2>&1 | tee -a "$LOG"
fi

log "caretaker check complete"
rm -f "$LOCKFILE"
