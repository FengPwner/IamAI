#!/usr/bin/env bash
# caretaker_watchdog_10min.sh — background loop: check every 10 minutes.
# only prints output (alert) when something is wrong.
# silent = healthy.

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SSH_KEY="/tmp/ssh_deploy_key"
export GIT_SSH_COMMAND="ssh -i ${SSH_KEY} -o StrictHostKeyChecking=no -o IdentitiesOnly=yes"

cd "$REPO" || exit 1

while true; do
    sleep 600

    # 1. check writer process
    writer_pid=$(pgrep -f "writer_loop.py --writer qwen" | head -1)
    if [ -z "$writer_pid" ]; then
        echo "[ALERT $(date -Iseconds)] writer process DEAD — restarting"
        bash "$REPO/tools/run_both.sh" 2>&1
        echo "[RESTART $(date -Iseconds)] writer restarted via run_both.sh"
    fi

    # 2. check batch committer
    batch_pid=$(pgrep -f "commit_batch.py --watch --writer qwen" | head -1)
    if [ -z "$batch_pid" ]; then
        echo "[ALERT $(date -Iseconds)] batch committer DEAD — restarting"
        bash "$REPO/tools/run_both.sh" 2>&1
        echo "[RESTART $(date -Iseconds)] batch restarted via run_both.sh"
    fi

    # 3. check uncommitted backlog
    uncommitted=$(git status --porcelain | wc -l)
    if [ "$uncommitted" -gt 0 ]; then
        echo "[ALERT $(date -Iseconds)] $uncommitted uncommitted files — committing"
        git add -A
        git commit -m "watchdog: auto-commit backlog at $(date -Iseconds)" 2>&1
    fi

    # 4. check unpushed commits and push
    unpushed=$(git log origin/main..HEAD --oneline 2>/dev/null | wc -l)
    if [ "$unpushed" -gt 0 ]; then
        echo "[ALERT $(date -Iseconds)] $unpushed unpushed commits — pushing"
        git push origin main 2>&1
    fi
done
