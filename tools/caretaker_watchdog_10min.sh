#!/usr/bin/env bash
# caretaker_watchdog_10min — check writer/batch health every 10 minutes
# Only outputs (alerts) when something is wrong:
#   - writer or batch process is dead
#   - uncommitted files piling up (>20 files or >15min since last commit)
# Silent = healthy.
set -euo pipefail
cd "$(dirname "$0")/.."

while true; do
  sleep 600  # 10 minutes

  ALERT=""

  # Check writer
  WRITER_PID=$(pgrep -f "writer_loop.py.*--writer qwen" 2>/dev/null || true)
  if [ -z "$WRITER_PID" ]; then
    ALERT="${ALERT}⚠ writer process DEAD\n"
  fi

  # Check batch committer
  BATCH_PID=$(pgrep -f "commit_batch.py.*--writer qwen" 2>/dev/null || true)
  if [ -z "$BATCH_PID" ]; then
    ALERT="${ALERT}⚠ batch committer DEAD\n"
  fi

  # Check uncommitted file count
  PENDING=$(git status --porcelain 2>/dev/null | wc -l)
  if [ "$PENDING" -gt 20 ]; then
    ALERT="${ALERT}⚠ $PENDING uncommitted files (threshold: 20)\n"
  fi

  # Check last commit age
  LAST_COMMIT_AGE=$(( $(date +%s) - $(git log -1 --format=%ct 2>/dev/null || echo 0) ))
  if [ "$LAST_COMMIT_AGE" -gt 900 ]; then  # >15 min since last commit
    ALERT="${ALERT}⚠ last commit was ${LAST_COMMIT_AGE}s ago (>15min)\n"
  fi

  # Only output if there's a problem
  if [ -n "$ALERT" ]; then
    echo "=== WATCHDOG ALERT $(date -Iseconds) ==="
    echo -e "$ALERT"
    echo "Attempting restart..."
    bash tools/run_both.sh 2>&1 | tail -5
    echo "=== restart attempted ==="
  fi
done
