#!/usr/bin/env bash
# post_restart_push_fix.sh — resolve push divergence after a restart.
#
# When the writer restarts after a stall, the remote may have advanced
# (another writer landed strokes while we were down). A plain push will
# be rejected. This script:
#
#   1. fetches the remote
#   2. if diverged, merges with -X theirs (remote wins on conflicts)
#   3. pushes
#
# Exit codes:
#   0 — push succeeded (with or without merge)
#   1 — merge had conflicts that -X theirs couldn't resolve
#   2 — push failed for a non-divergence reason (network, auth, etc.)
#
# Usage:
#   bash tools/post_restart_push_fix.sh                     # default: origin main, IamAI repo
#   bash tools/post_restart_push_fix.sh --repo /path/to/repo # override repo path
#   bash tools/post_restart_push_fix.sh origin main          # explicit remote/branch

set -uo pipefail

# Parse arguments
REPO=""
REMOTE="origin"
BRANCH="main"

while [ $# -gt 0 ]; do
  case "$1" in
    --repo)
      REPO="$2"
      shift 2
      ;;
    *)
      if [ -z "$REPO" ] && [ "$REMOTE" = "origin" ] && [ "$BRANCH" = "main" ] && [ $# -ge 1 ]; then
        # Positional: first non-flag arg is remote, second is branch
        REMOTE="$1"
        shift
        if [ $# -gt 0 ]; then
          BRANCH="$1"
          shift
        fi
      else
        shift
      fi
      ;;
  esac
done

# Default repo if not specified
if [ -z "$REPO" ]; then
  REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
fi

cd "$REPO" || exit 2

# --- step 1: fetch ---
if ! git fetch "$REMOTE" 2>/dev/null; then
  echo "fetch failed — network or auth issue"
  exit 2
fi

# --- step 2: check divergence ---
LOCAL_AHEAD=$(git rev-list --count "$REMOTE/$BRANCH..HEAD" 2>/dev/null || echo 0)
REMOTE_AHEAD=$(git rev-list --count "HEAD..$REMOTE/$BRANCH" 2>/dev/null || echo 0)

if [ "$LOCAL_AHEAD" -eq 0 ] && [ "$REMOTE_AHEAD" -eq 0 ]; then
  echo "in sync — nothing to do"
  exit 0
fi

if [ "$LOCAL_AHEAD" -eq 0 ] && [ "$REMOTE_AHEAD" -gt 0 ]; then
  # local behind but nothing to push — just fast-forward
  git merge --ff-only "$REMOTE/$BRANCH" 2>/dev/null
  echo "fast-forwarded to $REMOTE/$BRANCH (was $REMOTE_AHEAD behind)"
  exit 0
fi

if [ "$REMOTE_AHEAD" -eq 0 ]; then
  # local ahead, remote clean — just push
  echo "local ahead by $LOCAL_AHEAD, remote clean"
fi

# both sides have commits — merge needed
echo "diverged: local +$LOCAL_AHEAD / remote +$REMOTE_AHEAD"
echo "merging with -X theirs (remote wins on conflicts)..."

# stash any uncommitted changes first
STASHED=0
if [ -n "$(git status --porcelain)" ]; then
  git stash push -m "post_restart_push_fix auto-stash $(date +%s)" 2>/dev/null
  STASHED=1
fi

if git merge -X theirs "$REMOTE/$BRANCH" --no-edit 2>/dev/null; then
  echo "merge clean"
else
  echo "merge conflict — aborting"
  git merge --abort 2>/dev/null
  [ "$STASHED" -eq 1 ] && git stash pop 2>/dev/null
  exit 1
fi

# --- step 3: push ---
if git push "$REMOTE" "$BRANCH" 2>&1; then
  echo "push succeeded"
  # restore stash if we made one
  if [ "$STASHED" -eq 1 ]; then
    git stash pop 2>/dev/null || echo "stash pop failed — check git stash list"
  fi
  exit 0
else
  echo "push failed after merge — check network/auth"
  [ "$STASHED" -eq 1 ] && git stash pop 2>/dev/null
  exit 2
fi
