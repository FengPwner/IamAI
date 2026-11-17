#!/usr/bin/env bash
# push_recover.sh — recover from a push rejection (remote divergence)
#
# Flow: stash dirty tree → pull --rebase → stash pop → push
# Handles: dirty working tree, rebase conflicts, push retry with backoff.
#
# Usage:
#   tools/push_recover.sh              # default: push to origin main
#   tools/push_recover.sh upstream dev # custom remote/branch
#
# Exit codes:
#   0 — push succeeded
#   1 — rebase conflict (aborted, working tree restored)
#   2 — push failed after all retries
#   3 — stash pop conflict (manual resolution needed)
#
# Written by Qwen during caretaker visit 670, 2026-11-17.

set -euo pipefail

REMOTE="${1:-origin}"
BRANCH="${2:-main}"
MAX_RETRIES=3
BACKOFF_BASE=5  # seconds

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "ERROR: not inside a git repository" >&2
  exit 2
}
cd "$REPO_ROOT"

log() { echo "[push_recover] $*"; }

# ── 1. detect dirty tree ──────────────────────────────────────────
STASHED=0
if ! git diff --quiet || ! git diff --cached --quiet; then
  log "dirty working tree — stashing"
  git stash push -m "push_recover auto-stash $(date -Iseconds)" --quiet
  STASHED=1
fi

# ── 2. pull --rebase ──────────────────────────────────────────────
log "pulling --rebase from $REMOTE/$BRANCH"
if ! git pull --rebase "$REMOTE" "$BRANCH" 2>&1; then
  log "rebase conflict detected — aborting rebase"
  git rebase --abort 2>/dev/null || true
  if [ "$STASHED" -eq 1 ]; then
    log "restoring stashed changes"
    git stash pop --quiet
  fi
  echo "ERROR: rebase conflict, working tree restored. Manual resolution needed." >&2
  exit 1
fi

# ── 3. restore stash ──────────────────────────────────────────────
if [ "$STASHED" -eq 1 ]; then
  log "restoring stashed changes"
  if ! git stash pop --quiet 2>&1; then
    log "stash pop conflict — leaving stash intact for manual resolution"
    echo "ERROR: stash pop conflict. Run 'git stash pop' manually." >&2
    exit 3
  fi
fi

# ── 4. push with retry ───────────────────────────────────────────
for attempt in $(seq 1 "$MAX_RETRIES"); do
  log "push attempt $attempt/$MAX_RETRIES to $REMOTE/$BRANCH"
  if git push "$REMOTE" "$BRANCH" 2>&1; then
    log "push succeeded on attempt $attempt"
    exit 0
  fi

  if [ "$attempt" -lt "$MAX_RETRIES" ]; then
    DELAY=$(( BACKOFF_BASE * (2 ** (attempt - 1)) ))
    log "push failed — waiting ${DELAY}s before retry"
    sleep "$DELAY"

    # remote may have advanced again; rebase before retry
    if [ "$STASHED" -eq 1 ] && (! git diff --quiet || ! git diff --cached --quiet); then
      log "new dirty tree before retry — stashing again"
      git stash push -m "push_recover retry-stash $(date -Iseconds)" --quiet
      STASHED=1
    fi

    log "re-pulling --rebase before retry"
    if ! git pull --rebase "$REMOTE" "$BRANCH" 2>&1; then
      git rebase --abort 2>/dev/null || true
      log "rebase conflict on retry — giving up"
      if git stash list | head -1 | grep -q "push_recover"; then
        git stash pop --quiet 2>/dev/null || true
      fi
      exit 1
    fi

    if git stash list | head -1 | grep -q "push_recover.*retry-stash"; then
      git stash pop --quiet 2>/dev/null || true
    fi
  fi
done

echo "ERROR: push failed after $MAX_RETRIES attempts" >&2
exit 2
