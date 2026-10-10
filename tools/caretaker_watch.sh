#!/usr/bin/env bash
# Lightweight caretaker: every 10 minutes, verify writer+batch are alive,
# commit+push any backlog, and restart dead processes.
# Runs in background; logs to /tmp/iamai-caretaker.log.
#
#   bash tools/caretaker_watch.sh &
#   bash tools/caretaker_watch.sh --stop

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO="$(cd "$HERE/.." && pwd -P)"
LOG="/tmp/iamai-caretaker.log"
STOP="/tmp/iamai-caretaker-stop"
WRITER_ID="${IAMAII_WRITER:-qwen}"

rm -f "$STOP"

_log() {
  echo "[$(date -u '+%Y-%m-%d %H:%M:%S')Z] caretaker $*" >> "$LOG"
}

alive_pid() {
  [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null
}

case "${1:-run}" in
  --stop)
    touch "$STOP"
    _log "stop requested"
    exit 0
    ;;
esac

_log "start"

while true; do
  sleep 600

  if [ -f "$STOP" ]; then
    rm -f "$STOP"
    _log "stopped"
    exit 0
  fi

  cd "$REPO" || exit 1

  # Check writer
  WPID="/tmp/iamai-writer-${WRITER_ID}.pid"
  BPID="/tmp/iamai-batch-${WRITER_ID}.pid"

  NEEDS_RESTART=false
  if ! alive_pid "$WPID"; then
    _log "writer dead, restarting"
    NEEDS_RESTART=true
  fi
  if ! alive_pid "$BPID"; then
    _log "batch dead, restarting"
    NEEDS_RESTART=true
  fi

  if [ "$NEEDS_RESTART" = true ]; then
    # Clear stale lock
    rm -f "$REPO/.git/index.lock"
    bash "$HERE/run_both.sh" >> "$LOG" 2>&1
    _log "restarted via run_both.sh"
  fi

  # Commit backlog
  PENDING=$(git status --porcelain 2>/dev/null | wc -l)
  if [ "$PENDING" -gt 0 ]; then
    rm -f "$REPO/.git/index.lock" 2>/dev/null
    git add -A 2>/dev/null
    git commit -m "caretaker auto-commit: $PENDING file(s)" --author="Qwen <qwen@iamai.local>" 2>/dev/null
    _log "committed $PENDING files"
    git push origin main 2>/dev/null
    _log "pushed"
  else
    _log "all clean"
  fi
done
