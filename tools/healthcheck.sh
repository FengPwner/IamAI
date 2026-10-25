#!/usr/bin/env bash
# Health check for IamAI writer + batch committer.
# Exit 0 = healthy, exit 1 = needs attention.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO="$(cd "$HERE/.." && pwd -P)"
WRITER_ID="${IAMAII_WRITER:-qwen}"
WRITER_PID="/tmp/iamai-writer-${WRITER_ID}.pid"
BATCH_PID="/tmp/iamai-batch-${WRITER_ID}.pid"

alive() { [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null; }

ISSUES=()

if ! alive "$WRITER_PID"; then
  ISSUES+=("writer[$WRITER_ID] is NOT running")
fi

if ! alive "$BATCH_PID"; then
  ISSUES+=("batch[$WRITER_ID] is NOT running")
fi

cd "$REPO" || exit 1
PENDING=$(git status --porcelain | wc -l)
if [ "$PENDING" -gt 20 ]; then
  ISSUES+=("$PENDING files uncommitted (backlog)")
fi

if [ ${#ISSUES[@]} -gt 0 ]; then
  echo "ALERT: ${ISSUES[*]}"
  exit 1
else
  echo "OK: writer pid $(cat "$WRITER_PID"), batch pid $(cat "$BATCH_PID"), $PENDING pending"
  exit 0
fi
