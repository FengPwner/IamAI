#!/usr/bin/env bash
# The ten-minute heartbeat. Start it once, forget about it, and it keeps feeding
# the repository one commit at a time until something kills it or you stop it.
#
#   bash tools/loop.sh                # foreground, ctrl-c to stop
#   nohup bash tools/loop.sh >/dev/null 2>&1 &   # detached
#   touch /tmp/iamai-stop             # ask it to stop politely

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
INTERVAL="${IAMAII_INTERVAL:-600}"
LOG="$(dirname "$HERE")/writer.log"
STOPFILE="${IAMAII_STOPFILE:-/tmp/iamai-stop}"

echo "loop start pid=$$ interval=${INTERVAL}s log=$LOG" >> "$LOG"
rm -f "$STOPFILE"

while true; do
  if [ -f "$STOPFILE" ]; then
    echo "loop stop: saw $STOPFILE at $(date -u '+%Y-%m-%d %H:%M UTC')" >> "$LOG"
    rm -f "$STOPFILE"
    exit 0
  fi

  sleep "$INTERVAL"

  if bash "$HERE/push_round.sh" >> "$LOG" 2>&1; then
    echo "[$(date -u '+%Y-%m-%d %H:%M UTC')] round ok" >> "$LOG"
  else
    echo "[$(date -u '+%Y-%m-%d %H:%M UTC')] round failed (rc=$?), continuing" >> "$LOG"
  fi
done
