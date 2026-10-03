#!/usr/bin/env bash
# Keep the Doubao writer + committer alive on this host.
#
# A continuous writer that silently died is how a "commit every ten minutes"
# promise turns into radio silence. This loop checks both pid files once a
# minute and restarts whichever process is missing. It exits when /tmp/iamai-stop
# exists, so the repo's normal stop convention still works.
#
#     bash tools/watch_doubao.sh        # run as a detached watchdog
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
WRITER_PID=/tmp/iamai-writer-doubao.pid
BATCH_PID=/tmp/iamai-batch-doubao.pid
STOP=/tmp/iamai-stop
LOG=/tmp/iamai-doubao.log

alive() { [ -f "$1" ] && kill -0 "$(cat "$1" 2>/dev/null)" 2>/dev/null; }

while true; do
  if [ -f "$STOP" ]; then
    echo "[$(date -u +%FT%TZ)] watchdog: stop requested, exiting" >> "$LOG"
    exit 0
  fi

  if ! alive "$WRITER_PID"; then
    echo "[$(date -u +%FT%TZ)] watchdog: doubao writer dead, restarting" >> "$LOG"
    (cd "$REPO" && setsid nohup python3 tools/doubao_loop.py --every 20 >> "$LOG" 2>&1 < /dev/null &)
  fi

  if ! alive "$BATCH_PID"; then
    echo "[$(date -u +%FT%TZ)] watchdog: doubao committer dead, restarting" >> "$LOG"
    (cd "$REPO" && setsid nohup env IAMAII_WRITER=doubao IAMAII_AUTHOR_NAME=Doubao IAMAII_AUTHOR_EMAIL=doubao@iamai.local \
      python3 tools/commit_batch.py --watch --writer doubao --interval 600 >> "$LOG" 2>&1 < /dev/null &)
  fi

  sleep 60
done
