#!/usr/bin/env bash
# Start (or stop) the two long-running processes that keep this repo alive.
#
#   bash tools/run_both.sh                 # start both, detached
#   bash tools/run_both.sh --stop          # ask both to exit politely
#   bash tools/run_both.sh --status        # what is running, what is pending
#
# PIDs go into /tmp rather than being hunted with pkill: a pattern like
# "loop.sh" also matches the killing command's own command line, which is how
# this script once killed its own shell. Pidfiles are boring and correct.

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO="$(cd "$HERE/.." && pwd -P)"
WRITER_PID=/tmp/iamai-writer.pid
BATCH_PID=/tmp/iamai-batch.pid
STOP=/tmp/iamai-stop
LOG="${IAMAII_LOG:-/tmp/iamai-writer.log}"
STROKE_EVERY="${IAMAII_STROKE_EVERY:-15}"
BATCH_INTERVAL="${IAMAII_INTERVAL:-600}"

alive() { [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null; }

case "${1:-start}" in
  --stop|stop)
    touch "$STOP"
    for pid in "$WRITER_PID" "$BATCH_PID"; do
      if alive "$pid"; then
        kill "$(cat "$pid")" 2>/dev/null
        echo "sent TERM to $(cat "$pid") ($pid)"
      fi
      rm -f "$pid"
    done
    rm -f /tmp/iamai-writer-pause
    echo "stopped (stop file consumed on exit)"
    ;;

  --status|status)
    echo "writer:  $(alive "$WRITER_PID" && echo "running pid $(cat "$WRITER_PID")" || echo 'NOT running')"
    echo "batch:   $(alive "$BATCH_PID" && echo "running pid $(cat "$BATCH_PID")" || echo 'NOT running')"
    echo "pause:   $([ -f /tmp/iamai-writer-pause ] && echo 'RED GATE -- writer idling' || echo no)"
    echo "pending: $(cd "$REPO" && git status --porcelain | wc -l) file(s) uncommitted"
    (cd "$REPO" && git log --oneline -3 && echo && git ls-files | wc -l | xargs echo tracked files:)
    tail -4 "$LOG" 2>/dev/null
    ;;

  start|"")
    rm -f "$STOP" /tmp/iamai-writer-pause
    if alive "$WRITER_PID" || alive "$BATCH_PID"; then
      echo "something is already running -- refusing to double the writer"
      echo "writer: $(alive "$WRITER_PID" && echo yes || echo no), batch: $(alive "$BATCH_PID" && echo yes || echo no)"
      exit 1
    fi
    cd "$REPO" || exit 1
    # .gitattributes 声明了 merge=union，但 git 需要本地配置才知道 union 驱动是什么。
    # 少配这一步不会丢数据（退回普通合并 -> 冲突可见），只是每个窗口都要人工合一次。
    git config merge.union.name "union append-only merge"
    git config merge.union.driver "git merge-file --union %A %O %B"
    setsid nohup python3 tools/writer_loop.py --every "$STROKE_EVERY" >> "$LOG" 2>&1 < /dev/null &
    setsid nohup python3 tools/commit_batch.py --watch --interval "$BATCH_INTERVAL" >> "$LOG" 2>&1 < /dev/null &
    # Each process writes its own pid file; pgrep is not used because a pattern like
    # "writer_loop.py" also matches the shell running this script.
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      [ -s "$WRITER_PID" ] && [ -s "$BATCH_PID" ] && break
      sleep 1
    done
    echo "writer pid $(cat "$WRITER_PID" 2>/dev/null || echo '?'): $(alive "$WRITER_PID" && echo up || echo DEAD)"
    echo "batch  pid $(cat "$BATCH_PID" 2>/dev/null || echo '?'): $(alive "$BATCH_PID" && echo up || echo DEAD)"
    echo "cadence: one stroke every ${STROKE_EVERY}s, one commit every ${BATCH_INTERVAL}s"
    ;;

  *)
    echo "usage: $0 [start|--stop|--status]" >&2
    exit 2
    ;;
esac
