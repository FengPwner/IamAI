#!/usr/bin/env bash
# caretaker_watch.sh — background patrol loop for IamAI repo
# Checks every 10 minutes:
#   1. Writer and batch processes alive? Restart if dead.
#   2. Pending uncommitted files? Commit and push them.
#   3. Log results; only emit ALERT lines when something went wrong.
#
# Usage:
#   nohup bash tools/caretaker_watch.sh >> /tmp/iamai-caretaker.log 2>&1 &

set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
INTERVAL=600  # 10 minutes
LOG="/tmp/iamai-caretaker.log"
WRITER_ID="${IAMAII_WRITER:-qwen}"
WRITER_PID="/tmp/iamai-writer-${WRITER_ID}.pid"
BATCH_PID="/tmp/iamai-batch-${WRITER_ID}.pid"

cd "$REPO" || exit 1

alive() { [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null; }

visit=0
while true; do
  visit=$((visit + 1))
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  writer_ok=true
  batch_ok=true
  restarted=false
  committed=false
  pushed=false
  alert=""

  # --- Check processes ---
  if ! alive "$WRITER_PID"; then
    writer_ok=false
    alert="${alert}WRITER_DEAD "
  fi
  if ! alive "$BATCH_PID"; then
    batch_ok=false
    alert="${alert}BATCH_DEAD "
  fi

  # --- Restart if needed ---
  if [ "$writer_ok" = false ] || [ "$batch_ok" = false ]; then
    echo "[$ts] visit $visit: restarting (writer=$writer_ok batch=$batch_ok)"
    bash tools/run_both.sh 2>&1 | tail -3
    restarted=true
    sleep 5
    if alive "$WRITER_PID" && alive "$BATCH_PID"; then
      echo "[$ts] visit $visit: restart OK"
    else
      alert="${alert}RESTART_FAILED "
      echo "[$ts] visit $visit: ALERT restart failed"
    fi
  fi

  # --- Check pending files ---
  pending=$(git status --porcelain | wc -l)
  if [ "$pending" -gt 0 ]; then
    echo "[$ts] visit $visit: $pending pending file(s), committing"
    git add -A
    git commit -m "caretaker watch visit $visit: catch-up commit $pending pending files" 2>&1 | tail -2
    committed=true
  fi

  # --- Push if needed ---
  unpushed=$(git log --oneline @{u}..HEAD 2>/dev/null | wc -l)
  if [ "$unpushed" -gt 0 ]; then
    echo "[$ts] visit $visit: $unpushed unpushed commit(s), pushing"
    if git push origin main 2>&1 | tail -2; then
      pushed=true
    else
      alert="${alert}PUSH_FAILED "
      echo "[$ts] visit $visit: ALERT push failed"
    fi
  fi

  # --- Summary ---
  if [ -n "$alert" ]; then
    echo "[$ts] visit $visit: ALERT $alert"
  else
    echo "[$ts] visit $visit: OK (writer up, batch up, clean tree)"
  fi

  sleep "$INTERVAL"
done
