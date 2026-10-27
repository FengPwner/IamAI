#!/usr/bin/env bash
# caretaker_watchdog.sh — self-healing monitor for writer + batch processes.
#
# Runs as a background daemon. Every 10 minutes:
#   1. Checks if writer and batch processes are alive
#   2. Restarts them if dead
#   3. Commits any pending changes
#   4. Attempts push (best-effort, failure is logged not fatal)
#   5. Writes status to /tmp/iamai-watchdog.log
#
# Usage:
#   bash tools/caretaker_watchdog.sh start    # start daemon
#   bash tools/caretaker_watchdog.sh stop     # stop daemon
#   bash tools/caretaker_watchdog.sh status   # check watchdog status
#   bash tools/caretaker_watchdog.sh once     # run one check cycle (foreground)
#
# Designed to be started by run_both.sh or independently.

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO="$(cd "$HERE/.." && pwd -P)"
WRITER_ID="${IAMAII_WRITER:-qwen}"
WRITER_PID="/tmp/iamai-writer-${WRITER_ID}.pid"
BATCH_PID="/tmp/iamai-batch-${WRITER_ID}.pid"
WATCHDOG_PID="/tmp/iamai-watchdog.pid"
WATCHDOG_LOG="/tmp/iamai-watchdog.log"
CHECK_INTERVAL=600  # 10 minutes

alive() { [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null; }

timestamp() { date -u '+%Y-%m-%dT%H:%M:%S+00:00'; }

log() { echo "[$(timestamp)] $*" >> "$WATCHDOG_LOG"; }

run_one_check() {
    cd "$REPO" || return 1
    local ts
    ts=$(timestamp)
    local issues=()
    local visit_num
    visit_num=$(( $(cat /tmp/iamai-watchdog-visit 2>/dev/null || echo 0) + 1 ))
    echo "$visit_num" > /tmp/iamai-watchdog-visit

    log "=== Watchdog check #${visit_num} at ${ts} ==="

    # 1. Check writer
    if ! alive "$WRITER_PID"; then
        log "WRITER DEAD — restarting"
        issues+=("writer dead")
        python3 "$HERE/writer_loop.py" --writer "$WRITER_ID" --every "${IAMAII_STROKE_EVERY:-15}" >> /tmp/iamai-${WRITER_ID}.log 2>&1 &
        sleep 2
        alive "$WRITER_PID" && log "writer restarted (pid $(cat "$WRITER_PID"))" || log "writer restart FAILED"
    fi

    # 2. Check batch committer
    if ! alive "$BATCH_PID"; then
        log "BATCH DEAD — restarting"
        issues+=("batch dead")
        python3 "$HERE/commit_batch.py" --watch --writer "$WRITER_ID" --interval "${IAMAII_INTERVAL:-600}" >> /tmp/iamai-${WRITER_ID}.log 2>&1 &
        sleep 2
        alive "$BATCH_PID" && log "batch restarted (pid $(cat "$BATCH_PID"))" || log "batch restart FAILED"
    fi

    # 3. Commit pending changes
    local pending
    pending=$(git status --porcelain | wc -l)
    if [ "$pending" -gt 0 ]; then
        log "pending: ${pending} file(s) — committing"
        issues+=("${pending} pending files")
        git add -A
        git commit -m "watchdog: auto-commit ${pending} pending file(s) at check #${visit_num}" 2>/dev/null || log "commit failed"
    fi

    # 4. Attempt push (best-effort)
    local unpushed
    unpushed=$(git log --oneline origin/main..HEAD 2>/dev/null | wc -l)
    if [ "$unpushed" -gt 0 ]; then
        git push origin main 2>> "$WATCHDOG_LOG" || log "push failed (${unpushed} unpushed)"
    fi

    # 5. Summary
    local status_line
    if [ ${#issues[@]} -eq 0 ]; then
        status_line="OK — writer up, batch up, 0 pending, ${unpushed} unpushed"
    else
        status_line="ISSUES: ${issues[*]} — writer $(alive "$WRITER_PID" && echo up || echo DEAD), batch $(alive "$BATCH_PID" && echo up || echo DEAD), ${unpushed} unpushed"
    fi
    log "$status_line"

    # Output for caller
    echo "check #${visit_num}: $status_line"

    # Return whether there are issues to report
    [ ${#issues[@]} -eq 0 ]
}

case "${1:-once}" in
  start)
    if alive "$WATCHDOG_PID"; then
        echo "watchdog already running (pid $(cat "$WATCHDOG_PID"))"
        exit 0
    fi
    echo "Starting watchdog daemon (interval=${CHECK_INTERVAL}s)..."
    (
        echo $$ > "$WATCHDOG_PID"
        while true; do
            run_one_check
            sleep "$CHECK_INTERVAL"
        done
    ) >> "$WATCHDOG_LOG" 2>&1 &
    disown
    sleep 1
    if alive "$WATCHDOG_PID"; then
        echo "watchdog running (pid $(cat "$WATCHDOG_PID"))"
    else
        echo "watchdog failed to start"
        exit 1
    fi
    ;;

  stop)
    if alive "$WATCHDOG_PID"; then
        kill "$(cat "$WATCHDOG_PID")" 2>/dev/null
        rm -f "$WATCHDOG_PID"
        echo "watchdog stopped"
    else
        echo "watchdog not running"
    fi
    ;;

  status)
    if alive "$WATCHDOG_PID"; then
        echo "watchdog: running (pid $(cat "$WATCHDOG_PID"))"
    else
        echo "watchdog: NOT running"
    fi
    echo "last check:"
    tail -5 "$WATCHDOG_LOG" 2>/dev/null || echo "(no log yet)"
    echo "visit count: $(cat /tmp/iamai-watchdog-visit 2>/dev/null || echo 0)"
    ;;

  once)
    run_one_check
    ;;

  *)
    echo "usage: $0 [start|stop|status|once]" >&2
    exit 2
    ;;
esac
