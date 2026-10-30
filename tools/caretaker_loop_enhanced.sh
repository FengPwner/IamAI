#!/bin/bash
# caretaker_loop_enhanced.sh — 增强版守护进程
# 每10分钟检查一次writer和batch进程，自动重启、补交积压、推送代码
# 只在出问题时通知用户，一切正常时保持静默

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

LOG_FILE="$REPO_ROOT/logs/caretaker_enhanced.log"
mkdir -p "$(dirname "$LOG_FILE")"

# SSH key setup
SSH_KEY="/tmp/ssh_deploy_key"
export GIT_SSH_COMMAND="ssh -i $SSH_KEY -o StrictHostKeyChecking=no"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"
}

notify_user() {
    # 只在出问题时通知用户
    local message="$1"
    log "NOTIFY: $message"
    # 这里可以接入通知系统，暂时只写日志
    echo "$message" >> "$REPO_ROOT/logs/caretaker_alerts.log"
}

check_and_restart_processes() {
    local needs_restart=false
    local writer_pid=""
    local batch_pid=""
    
    # Check writer process
    writer_pid=$(pgrep -f "writer_loop.py.*--writer qwen" || echo "")
    if [ -z "$writer_pid" ]; then
        log "Writer process not running, needs restart"
        needs_restart=true
    else
        log "Writer running: pid $writer_pid"
    fi
    
    # Check batch process
    batch_pid=$(pgrep -f "commit_batch.py.*--watch.*--writer qwen" || echo "")
    if [ -z "$batch_pid" ]; then
        log "Batch process not running, needs restart"
        needs_restart=true
    else
        log "Batch running: pid $batch_pid"
    fi
    
    # Restart if needed
    if [ "$needs_restart" = true ]; then
        log "Restarting processes via tools/run_both.sh"
        bash tools/run_both.sh >> "$LOG_FILE" 2>&1
        sleep 5
        
        # Verify restart
        writer_pid=$(pgrep -f "writer_loop.py.*--writer qwen" || echo "")
        batch_pid=$(pgrep -f "commit_batch.py.*--watch.*--writer qwen" || echo "")
        
        if [ -z "$writer_pid" ] || [ -z "$batch_pid" ]; then
            notify_user "⚠️ 进程重启失败：writer=$writer_pid, batch=$batch_pid"
            return 1
        else
            log "Processes restarted successfully: writer=$writer_pid, batch=$batch_pid"
            notify_user "✅ 进程已自动重启：writer=$writer_pid, batch=$batch_pid"
        fi
    fi
    
    return 0
}

commit_and_push() {
    # Check for uncommitted changes
    local uncommitted=$(git status --porcelain | wc -l)
    
    if [ "$uncommitted" -gt 0 ]; then
        log "Found $uncommitted uncommitted files, committing..."
        git add -A
        git commit -m "auto: caretaker batch $(date '+%Y-%m-%d %H:%M')" >> "$LOG_FILE" 2>&1
        log "Committed changes"
    fi
    
    # Check for unpushed commits
    local unpushed=$(git log origin/main..HEAD --oneline | wc -l)
    
    if [ "$unpushed" -gt 0 ]; then
        log "Found $unpushed unpushed commits, pushing..."
        if git push origin main >> "$LOG_FILE" 2>&1; then
            log "Pushed successfully"
        else
            log "Push failed, attempting to pull and rebase..."
            git pull --rebase origin main >> "$LOG_FILE" 2>&1
            if git push origin main >> "$LOG_FILE" 2>&1; then
                log "Push succeeded after rebase"
            else
                notify_user "⚠️ 代码推送失败，请检查"
                return 1
            fi
        fi
    fi
    
    return 0
}

# Main loop
log "=== Caretaker Enhanced Started ==="
log "Monitoring interval: 10 minutes"

while true; do
    log "--- Check cycle start ---"
    
    # Check and restart processes if needed
    if ! check_and_restart_processes; then
        log "Process check failed"
    fi
    
    # Commit and push
    if ! commit_and_push; then
        log "Commit/push failed"
    fi
    
    log "--- Check cycle end ---"
    
    # Sleep for 10 minutes
    sleep 600
done
