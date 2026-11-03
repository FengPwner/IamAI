#!/usr/bin/env bash
# caretaker_watchdog_loop.sh — background watchdog for IamAI writer + batch.
# Runs every 10 minutes: checks processes alive, restarts if dead,
# commits any backlog, and pushes.
#
# Usage: nohup bash tools/caretaker_watchdog_loop.sh &

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO="$(cd "$HERE/.." && pwd -P)"
INTERVAL=600  # 10 minutes

log() { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*"; }

check_and_fix() {
    cd "$REPO" || return 1

    # Check writer
    if ! pgrep -f "writer_loop.py.*--writer" > /dev/null 2>&1; then
        log "WARN: writer not running, restarting via run_both.sh"
        bash "$HERE/run_both.sh" 2>&1 | while read -r line; do log "  run_both: $line"; done
        sleep 3
    fi

    # Check batch
    if ! pgrep -f "commit_batch.py.*--watch" > /dev/null 2>&1; then
        log "WARN: batch not running, restarting via run_both.sh"
        bash "$HERE/run_both.sh" 2>&1 | while read -r line; do log "  run_both: $line"; done
        sleep 3
    fi

    # Commit any pending changes
    PENDING=$(git status --porcelain 2>/dev/null | wc -l)
    if [ "$PENDING" -gt 0 ]; then
        log "INFO: $PENDING pending files, committing"
        git add -A
        git commit -m "watchdog: auto-commit pending changes ($(date -u '+%H:%M'))" 2>&1 | while read -r line; do log "  commit: $line"; done
    fi

    # Push
    git push origin main 2>&1 | while read -r line; do log "  push: $line"; done
}

log "watchdog started (interval=${INTERVAL}s, repo=$REPO)"

while true; do
    check_and_fix
    sleep "$INTERVAL"
done
