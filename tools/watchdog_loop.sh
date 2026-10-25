#!/usr/bin/env bash
# Background watchdog loop: every 10 minutes, check processes and commit+push.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO="$(cd "$HERE/.." && pwd -P)"
WRITER_ID="${IAMAII_WRITER:-qwen}"
WRITER_PID="/tmp/iamai-writer-${WRITER_ID}.pid"
BATCH_PID="/tmp/iamai-batch-${WRITER_ID}.pid"

alive() { [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null; }

while true; do
    sleep 600  # 10 minutes

    cd "$REPO" || continue
    WRITER_UP=$(alive "$WRITER_PID" && echo "yes" || echo "no")
    BATCH_UP=$(alive "$BATCH_PID" && echo "yes" || echo "no")

    if [ "$WRITER_UP" = "no" ] || [ "$BATCH_UP" = "no" ]; then
        echo "[$(date -Iseconds)] watchdog: writer=$WRITER_UP batch=$BATCH_UP — restarting"
        PENDING=$(git status --porcelain | wc -l)
        if [ "$PENDING" -gt 0 ]; then
            git add -A
            git commit -m "watchdog catch-up: commit pending before restart" 2>/dev/null
        fi
        bash "$HERE/run_both.sh" 2>&1
        git pull --rebase --no-edit 2>/dev/null
        git push 2>&1
        echo "[$(date -Iseconds)] watchdog: restart complete"
    else
        PENDING=$(git status --porcelain | wc -l)
        if [ "$PENDING" -gt 0 ]; then
            git add -A
            git commit -m "watchdog: periodic commit of accumulated strokes" 2>/dev/null
            git pull --rebase --no-edit 2>/dev/null
            git push 2>&1
        fi
    fi
done
