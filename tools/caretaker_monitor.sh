#!/usr/bin/env bash
# Caretaker monitor: check writer/batch health, restart if dead, push if behind.
# Designed to run from cron every 10 minutes.
#
# Exit codes:
#   0 = everything fine, nothing to report
#   1 = intervention needed (output describes what)

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO="$(cd "$HERE/.." && pwd -P)"
WRITER_ID="${IAMAII_WRITER:-qwen}"
WRITER_PID="/tmp/iamai-writer-${WRITER_ID}.pid"
BATCH_PID="/tmp/iamai-batch-${WRITER_ID}.pid"
LOG="/tmp/iamai-monitor-${WRITER_ID}.log"

cd "$REPO" || exit 1

alive() { [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null; }

ISSUES=()
FIXED=()

# 1. Check writer
if ! alive "$WRITER_PID"; then
    ISSUES+=("writer dead")
    bash tools/run_both.sh --stop >/dev/null 2>&1
    sleep 1
    bash tools/run_both.sh >> "$LOG" 2>&1
    if alive "$WRITER_PID"; then
        FIXED+=("writer restarted (pid $(cat "$WRITER_PID"))")
    else
        ISSUES+=("writer restart FAILED")
    fi
fi

# 2. Check batch
if ! alive "$BATCH_PID"; then
    ISSUES+=("batch dead")
    # batch is started by run_both.sh, already handled above if writer was also dead
    if alive "$BATCH_PID"; then
        FIXED+=("batch restarted (pid $(cat "$BATCH_PID"))")
    fi
fi

# 3. Check for uncommitted backlog older than 15 minutes
PENDING=$(git status --porcelain | wc -l)
if [ "$PENDING" -gt 0 ]; then
    # Check if batch is running (it should handle commits)
    if ! alive "$BATCH_PID"; then
        ISSUES+=("$PENDING files uncommitted and batch is down")
        # Manual commit as fallback
        git add -A
        git commit -m "monitor: emergency commit for $PENDING pending files" >> "$LOG" 2>&1
        FIXED+=("emergency commit created")
    fi
fi

# 4. Check for unpushed commits
UNPUSHED=$(git log --oneline origin/main..HEAD 2>/dev/null | wc -l)
if [ "$UNPUSHED" -gt 0 ]; then
    # Try to push
    PUSH_OUT=$(git push origin main 2>&1)
    PUSH_RC=$?
    if [ $PUSH_RC -ne 0 ]; then
        # Try pull-merge-push
        git pull --no-rebase origin main >> "$LOG" 2>&1
        PUSH_OUT=$(git push origin main 2>&1)
        PUSH_RC=$?
    fi
    if [ $PUSH_RC -ne 0 ]; then
        ISSUES+=("push failed after retry: $PUSH_OUT")
    else
        FIXED+=("pushed $UNPUSHED commit(s)")
    fi
fi

# 5. Report
if [ ${#ISSUES[@]} -eq 0 ]; then
    # All clear — silent exit
    exit 0
fi

echo "ALERT at $(date '+%Y-%m-%d %H:%M:%S CST'):"
for issue in "${ISSUES[@]}"; do
    echo "  ISSUE: $issue"
done
for fix in "${FIXED[@]}"; do
    echo "  FIXED: $fix"
done
exit 1
