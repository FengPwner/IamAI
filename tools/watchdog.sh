#!/usr/bin/env bash
# Watchdog for IamAI writer + batch processes.
# Runs every 10 minutes. Restarts if dead, commits backlog, pushes.
# Outputs a status line; only alerts if something needed intervention.

set -euo pipefail
cd "$(dirname "$0")/.."

ALERT=""
WRITER_PID=""
BATCH_PID=""

# --- Check processes ---
WRITER_PID=$(pgrep -f "tools/writer_loop.py --writer qwen" || true)
BATCH_PID=$(pgrep -f "tools/commit_batch.py --watch --writer qwen" || true)

if [ -z "$WRITER_PID" ]; then
    ALERT="${ALERT}[ALERT] Writer process dead, restarting. "
    nohup python3 tools/writer_loop.py --writer qwen --every 15 >/dev/null 2>&1 &
    WRITER_PID=$!
fi

if [ -z "$BATCH_PID" ]; then
    ALERT="${ALERT}[ALERT] Batch process dead, restarting. "
    nohup python3 tools/commit_batch.py --watch --writer qwen --interval 600 >/dev/null 2>&1 &
    BATCH_PID=$!
fi

# --- Check for uncommitted backlog ---
PENDING=$(git status --porcelain 2>/dev/null | wc -l)
if [ "$PENDING" -gt 0 ]; then
    # Remove stale lock if present
    if [ -f .git/index.lock ]; then
        LOCK_AGE=$(( $(date +%s) - $(stat -c %Y .git/index.lock 2>/dev/null || echo 0) ))
        if [ "$LOCK_AGE" -gt 60 ]; then
            rm -f .git/index.lock
            ALERT="${ALERT}[ALERT] Stale lock removed (${LOCK_AGE}s old). "
        fi
    fi

    ALERT="${ALERT}[ALERT] ${PENDING} pending file(s) committed. "
    git add -A
    TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    git commit -m "watchdog: auto-commit ${PENDING} pending files at ${TIMESTAMP}" 2>/dev/null || true
fi

# --- Push ---
PUSH_OUTPUT=$(git push 2>&1) || {
    ALERT="${ALERT}[ALERT] Push failed: ${PUSH_OUTPUT} "
    # Try pull-rebase and push again
    git pull --rebase 2>/dev/null || true
    PUSH_OUTPUT=$(git push 2>&1) || ALERT="${ALERT}[ALERT] Push retry also failed. "
}

# --- Final status ---
WRITER_PID=$(pgrep -f "tools/writer_loop.py --writer qwen" || true)
BATCH_PID=$(pgrep -f "tools/commit_batch.py --watch --writer qwen" || true)

if [ -n "$ALERT" ]; then
    echo "${ALERT}"
    echo "writer: pid ${WRITER_PID:-DEAD}  batch: pid ${BATCH_PID:-DEAD}"
    exit 1  # non-zero = something needed intervention
else
    echo "OK: writer pid ${WRITER_PID} batch pid ${BATCH_PID} — all clear"
    exit 0
fi
