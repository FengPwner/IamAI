#!/usr/bin/env bash
# caretaker_monitor.sh — check writer/batch health, report only anomalies.
#
# Exit codes:
#   0 = everything fine (silent)
#   1 = anomaly detected (prints diagnostic)
#
# Usage: bash tools/caretaker_monitor.sh

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO="$(cd "$HERE/.." && pwd -P)"
WRITER_ID="${IAMAII_WRITER:-qwen}"
WRITER_PID="/tmp/iamai-writer-${WRITER_ID}.pid"
BATCH_PID="/tmp/iamai-batch-${WRITER_ID}.pid"

alive() { [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null; }

ISSUES=()

cd "$REPO" || exit 1

# Check writer process
if alive "$WRITER_PID"; then
    WRITER_STATUS="running pid $(cat "$WRITER_PID")"
else
    WRITER_STATUS="NOT running"
    ISSUES+=("writer[$WRITER_ID] is not running")
fi

# Check batch process
if alive "$BATCH_PID"; then
    BATCH_STATUS="running pid $(cat "$BATCH_PID")"
else
    BATCH_STATUS="NOT running"
    ISSUES+=("batch[$WRITER_ID] is not running")
fi

# Check uncommitted backlog
PENDING=$(git status --porcelain | wc -l)
if [ "$PENDING" -gt 20 ]; then
    ISSUES+=("$PENDING files uncommitted (backlog > 20)")
fi

# Check last commit age (hours since last commit)
LAST_COMMIT_TS=$(git log -1 --format=%ct 2>/dev/null || echo 0)
NOW_TS=$(date +%s)
if [ "$LAST_COMMIT_TS" -gt 0 ]; then
    AGE_HOURS=$(( (NOW_TS - LAST_COMMIT_TS) / 3600 ))
    if [ "$AGE_HOURS" -ge 1 ]; then
        ISSUES+=("last commit was ${AGE_HOURS}h ago")
    fi
fi

# Output
if [ ${#ISSUES[@]} -eq 0 ]; then
    # All clear — silent exit
    exit 0
else
    echo "=== IamAI Monitor Alert ==="
    echo "writer[$WRITER_ID]: $WRITER_STATUS"
    echo "batch [$WRITER_ID]: $BATCH_STATUS"
    echo "pending: $PENDING file(s) uncommitted"
    echo "latest: $(git log -1 --oneline 2>/dev/null || echo 'no commits')"
    echo ""
    echo "Issues:"
    for issue in "${ISSUES[@]}"; do
        echo "  - $issue"
    done
    exit 1
fi
