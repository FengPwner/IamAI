#!/usr/bin/env bash
# caretaker watchdog: check writer+batch every 10 min, restart if dead, notify user only on failure
set -uo pipefail

REPO="/root/userdata/workspace/IamAI"
WRITER_ID="qwen"
WRITER_PID="/tmp/iamai-writer-${WRITER_ID}.pid"
BATCH_PID="/tmp/iamai-batch-${WRITER_ID}.pid"
LOG="/tmp/iamai-watchdog.log"

alive() { [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null; }

cd "$REPO" || exit 1

now=$(date '+%Y-%m-%d %H:%M:%S')

writer_ok=$(alive "$WRITER_PID" && echo yes || echo no)
batch_ok=$(alive "$BATCH_PID" && echo yes || echo no)

if [ "$writer_ok" = "no" ] || [ "$batch_ok" = "no" ]; then
  echo "[$now] STALL detected: writer=$writer_ok batch=$batch_ok" >> "$LOG"
  # try restart
  cd "$REPO" && bash tools/run_both.sh >> "$LOG" 2>&1
  sleep 5
  writer_ok2=$(alive "$WRITER_PID" && echo yes || echo no)
  batch_ok2=$(alive "$BATCH_PID" && echo yes || echo no)
  if [ "$writer_ok2" = "no" ] || [ "$batch_ok2" = "no" ]; then
    echo "[$now] RESTART FAILED: writer=$writer_ok2 batch=$batch_ok2 — NEEDS USER ATTENTION" >> "$LOG"
    echo "ALERT:restart_failed"
  else
    echo "[$now] RESTART OK: writer pid $(cat "$WRITER_PID"), batch pid $(cat "$BATCH_PID")" >> "$LOG"
    echo "INFO:restart_succeeded"
  fi
else
  # check pending backlog
  pending=$(git status --porcelain | wc -l)
  if [ "$pending" -gt 20 ]; then
    echo "[$now] BACKLOG high: $pending uncommitted files" >> "$LOG"
    echo "ALERT:backlog=$pending"
  else
    echo "[$now] OK: writer+batch running, $pending pending files" >> "$LOG"
  fi
fi
