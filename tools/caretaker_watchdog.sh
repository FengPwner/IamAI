#!/usr/bin/env bash
# Caretaker Watchdog — runs every 10 minutes via cron
# Checks: writer alive, batch alive, unpushed commits, uncommitted files
# Only outputs alerts when something needs attention.
set -euo pipefail

REPO="/root/userdata/workspace/IamAI"
SSH_KEY="/tmp/ssh_deploy_key"
export GIT_SSH_COMMAND="ssh -i ${SSH_KEY} -o StrictHostKeyChecking=no"

cd "$REPO"

ALERTS=()

# --- 1. Process health ---
WRITER_PID=$(pgrep -f 'writer_loop.py.*--writer qwen' | head -1 || true)
BATCH_PID=$(pgrep -f 'commit_batch.py.*--watch.*--writer qwen' | head -1 || true)

if [ -z "$WRITER_PID" ]; then
  ALERTS+=("⚠️ Writer 进程已停止，需要重启")
fi

if [ -z "$BATCH_PID" ]; then
  ALERTS+=("⚠️ Batch committer 进程已停止，需要重启")
fi

# --- 2. Uncommitted files ---
PENDING=$(git status --porcelain 2>/dev/null | wc -l)
if [ "$PENDING" -gt 20 ]; then
  ALERTS+=("⚠️ 有 ${PENDING} 个文件未提交（积压过多）")
fi

# --- 3. Unpushed commits ---
UNPUSHED=$(git log origin/main..HEAD --oneline 2>/dev/null | wc -l || echo 0)
if [ "$UNPUSHED" -gt 3 ]; then
  ALERTS+=("⚠️ 有 ${UNPUSHED} 个提交未推送到远程")
  # Try to push
  if git push origin main 2>/dev/null; then
    ALERTS+=("✅ 自动推送成功")
  else
    ALERTS+=("❌ 自动推送失败（可能远程有新提交，需要人工合并）")
  fi
fi

# --- 4. SSH key existence ---
if [ ! -f "$SSH_KEY" ]; then
  ALERTS+=("⚠️ SSH deploy key 不存在 (${SSH_KEY})")
fi

# --- Output: only if there are alerts ---
if [ ${#ALERTS[@]} -gt 0 ]; then
  echo "=== Caretaker Watchdog Alert $(date '+%Y-%m-%d %H:%M') ==="
  for a in "${ALERTS[@]}"; do
    echo "$a"
  done
  echo "writer: ${WRITER_PID:-stopped} | batch: ${BATCH_PID:-stopped} | pending: ${PENDING} | unpushed: ${UNPUSHED}"
else
  echo "WATCHDOG_OK"
fi
