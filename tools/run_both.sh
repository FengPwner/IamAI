#!/usr/bin/env bash
# Start (or stop) THIS host's writer + committer. One host, one writer id.
#
#   bash tools/run_both.sh                 # start both, detached, as $IAMAII_WRITER
#   bash tools/run_both.sh --stop          # ask both to exit politely
#   bash tools/run_both.sh --status        # what is running, what is pending
#
# Why pidfiles instead of pgrep: a pattern like "writer_loop.py" also matches the
# command line of the shell doing the killing, which is how this script once killed
# its own parent. Each process writes its own pid file at startup; nothing guesses.
#
# Why the id matters: merging another agent's code into this repo also merged their
# launcher, which silently started a second writer on this machine and produced
# another agent's strokes under my host. A shared repo is not a shared CPU.

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO="$(cd "$HERE/.." && pwd -P)"
WRITER_ID="${IAMAII_WRITER:-qwen}"
WRITER_PID="/tmp/iamai-writer-${WRITER_ID}.pid"
BATCH_PID="/tmp/iamai-batch-${WRITER_ID}.pid"
STOP="/tmp/iamai-stop"
PAUSE="/tmp/iamai-writer-pause-${WRITER_ID}"
LOG="${IAMAII_LOG:-/tmp/iamai-${WRITER_ID}.log}"
STROKE_EVERY="${IAMAII_STROKE_EVERY:-15}"
BATCH_INTERVAL="${IAMAII_INTERVAL:-600}"

alive() { [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null; }

case "${1:-start}" in
  --stop | stop)
    touch "$STOP"
    for pidfile in "$WRITER_PID" "$BATCH_PID"; do
      if alive "$pidfile"; then
        kill "$(cat "$pidfile")" 2>/dev/null
        echo "sent TERM to $(cat "$pidfile") ($(basename "$pidfile"))"
      fi
      rm -f "$pidfile"
    done
    rm -f "$PAUSE"
    echo "stopped writer '$WRITER_ID' (stop file consumed on exit)"
    ;;

  --status | status)
    echo "writer[$WRITER_ID]: $(alive "$WRITER_PID" && echo "running pid $(cat "$WRITER_PID")" || echo 'NOT running')"
    echo "batch [$WRITER_ID]: $(alive "$BATCH_PID" && echo "running pid $(cat "$BATCH_PID")" || echo 'NOT running')"
    echo "pause:  $([ -f "$PAUSE" ] && echo 'RED GATE -- writer idling' || echo no)"
    cd "$REPO" || exit 1
    echo "pending: $(git status --porcelain | wc -l) file(s) uncommitted"
    git log --oneline -3
    echo "tracked: $(git ls-files | wc -l) files"
    python3 tools/heartbeat.py --writer "$WRITER_ID" 2>/dev/null
    tail -3 "$LOG" 2>/dev/null
    ;;

  start | "")
    rm -f "$STOP" "$PAUSE"
    cd "$REPO" || exit 1

    if alive "$WRITER_PID" || alive "$BATCH_PID"; then
      echo "writer '$WRITER_ID' already running -- refusing to double it"
      echo "  writer: $(alive "$WRITER_PID" && echo yes || echo no)  batch: $(alive "$BATCH_PID" && echo yes || echo no)"
      exit 1
    fi

    # .gitattributes declares merge=union for append-only logs, but git needs the
    # driver configured locally to honour it. Without this every cross-agent window
    # needs a human to merge by hand; with it, both sides' lines just survive.
    git config merge.union.name "union append-only merge"
    git config merge.union.driver "git merge-file --union %A %O %B"
    git config user.name "${IAMAII_AUTHOR_NAME:-Qwen}"
    git config user.email "${IAMAII_AUTHOR_EMAIL:-qwen@iamai.local}"

    setsid nohup python3 tools/writer_loop.py --writer "$WRITER_ID" --every "$STROKE_EVERY" >> "$LOG" 2>&1 < /dev/null &
    setsid nohup python3 tools/commit_batch.py --watch --writer "$WRITER_ID" --interval "$BATCH_INTERVAL" >> "$LOG" 2>&1 < /dev/null &

    # setsid may fork, so $! is not the daemon: each process writes its own pid file.
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      [ -s "$WRITER_PID" ] && [ -s "$BATCH_PID" ] && break
      sleep 1
    done
    echo "writer pid $(cat "$WRITER_PID" 2>/dev/null || echo '?'): $(alive "$WRITER_PID" && echo up || echo DEAD)"
    echo "batch  pid $(cat "$BATCH_PID" 2>/dev/null || echo '?'): $(alive "$BATCH_PID" && echo up || echo DEAD)"
    echo "author $(git config user.name) <$(git config user.email)>"
    echo "cadence: writer=$WRITER_ID  one stroke every ${STROKE_EVERY}s  one commit every ${BATCH_INTERVAL}s"
    ;;

  *)
    echo "usage: $0 [start|--stop|--status]   (writer id from \$IAMAII_WRITER, default qwen)" >&2
    exit 2
    ;;
esac
