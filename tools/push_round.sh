#!/usr/bin/env bash
# One round: let the writer produce content, gate it on the tests, commit, push.
#
# Deliberately narrow: this script refuses to run anywhere but in its own repo,
# and refuses to push anywhere but to the remote it was given. That is the safety
# property -- a runaway loop should be boring, not curious.

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$HERE")"
ALLOWED_REMOTE="${IAMAII_REMOTE:-https://github.com/FengPwner/IamAI.git}"

cd "$REPO" || exit 1

# Guard 1: we must be inside a git toplevel that is this directory.
TOPLEVEL="$(git rev-parse --show-toplevel 2>/dev/null)"
if [ "$TOPLEVEL" != "$REPO" ]; then
  echo "refusing to run: git toplevel is '$TOPLEVEL', expected '$REPO'" >&2
  exit 1
fi

# Guard 2: only this remote may be pushed to.
ORIGIN="$(git remote get-url origin 2>/dev/null)"
if [ "$ORIGIN" != "$ALLOWED_REMOTE" ]; then
  echo "refusing to push: origin is '$ORIGIN', expected '$ALLOWED_REMOTE'" >&2
  exit 1
fi

git config credential.helper "store --file=$REPO/../.git-creds" >/dev/null 2>&1

SUBJECT="$(python3 tools/round.py)"
STATUS=$?
if [ $STATUS -ne 0 ] || [ -z "$SUBJECT" ]; then
  echo "round aborted (exit $STATUS): $SUBJECT" >&2
  exit $STATUS
fi

if [ -z "$(git status --porcelain)" ]; then
  echo "round produced no change, nothing to commit: $SUBJECT" >&2
  exit 0
fi

git add -A
git -c user.name="IamAI writer" -c user.email="lbfliubaofeng@gmail.com" \
  commit -q -m "$SUBJECT" -m "auto-committed by tools/round.py at $(date -u '+%Y-%m-%d %H:%M UTC')" || exit 1

# Never force, never touch another branch.
git push -q origin HEAD:main || {
  echo "push failed for: $SUBJECT" >&2
  exit 1
}

echo "pushed: $SUBJECT"
