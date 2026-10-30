#!/usr/bin/env bash
# caretaker_loop.sh — periodic check, commit, and push every 10 minutes
# Runs in the background; only alerts user on stall or uncommitted backlog.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
INTERVAL=600  # 10 minutes
LOCKFILE="/tmp/caretaker_loop.lock"

# prevent double-start
if [ -f "$LOCKFILE" ]; then
    pid=$(cat "$LOCKFILE" 2>/dev/null)
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        echo "caretaker loop already running (pid $pid)"
        exit 0
    fi
    rm -f "$LOCKFILE"
fi
echo $$ > "$LOCKFILE"
trap 'rm -f "$LOCKFILE"' EXIT

cd "$REPO_DIR"

while true; do
    sleep "$INTERVAL"

    # check writer and batch processes
    writer_running=false
    batch_running=false
    for pid in $(pgrep -f "writer_loop.py.*--writer qwen" 2>/dev/null || true); do
        if kill -0 "$pid" 2>/dev/null; then
            writer_running=true
            break
        fi
    done
    for pid in $(pgrep -f "commit_batch.py.*--writer qwen" 2>/dev/null || true); do
        if kill -0 "$pid" 2>/dev/null; then
            batch_running=true
            break
        fi
    done

    # restart if needed
    if [ "$writer_running" = false ] || [ "$batch_running" = false ]; then
        echo "$(date -Iseconds) — process down, restarting..."
        bash tools/run_both.sh 2>/dev/null || true
        sleep 5
    fi

    # commit any pending changes
    pending=$(git status --porcelain 2>/dev/null | wc -l)
    if [ "$pending" -gt 0 ]; then
        git add -A
        git commit -m "catch-up: commit pending changes (caretaker loop)" 2>/dev/null || true
    fi

    # push
    git pull --rebase origin main 2>/dev/null || true
    git push origin main 2>/dev/null || true

    echo "$(date -Iseconds) — cycle complete (writer=$writer_running, batch=$batch_running, pending_was=$pending)"
done
