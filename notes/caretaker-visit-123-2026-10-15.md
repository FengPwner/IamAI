# Caretaker Visit 123 — 2026-10-15 01:00 CST

## What happened

Writer (pid 1459) and batch committer (pid 1460) were found dead on arrival.
The pre-execution report showed 9 uncommitted files, a stale `.git/index.lock`,
and a non-fast-forward push rejection. The git index itself was reporting
"index file smaller than expected" — a truncated index from a killed commit.

## Recovery sequence

1. Committed 9 pending files as catch-up commit `f587bab`.
2. Stashed working-tree changes (writer had modified `data/writer_state.qwen.json`
   and `notes/limits.md` between checks).
3. Removed stale `.git/index.lock`.
4. Rebased local `f587bab` onto `origin/main` (which had 2 new commits:
   `88164dd` batch and `407c867` merge).
5. Pushed successfully: `407c867..594a633 main -> main`.
6. Popped stash — working tree restored.
7. Restarted writer and batch — new PIDs 1784/1785.

## New module: index_guard

The recovery above involved five separate git operations in sequence:
remove lock → stash → fetch → rebase → pop. Every caretaker visit that
hits a corrupted index repeats this dance by hand. The new `index_guard`
module wraps it into a single `safe_pull_rebase()` call.

Components:

- **check_lock**: detects and auto-removes stale `index.lock` (age > 300s
  and no holder process).
- **check_index**: verifies `.git/index` is present and non-empty.
- **check_dirty**: reports uncommitted changes.
- **preflight**: runs all checks, auto-repairs what is safe, returns a
  structured report.
- **safe_stash / safe_pop**: idempotent stash with labeled entries.
- **safe_pull_rebase**: full stash → fetch → rebase → pop sequence with
  automatic lock cleanup and rebase-abort fallback.

## Observations

The index corruption pattern — "index file smaller than expected" — is
the same one that killed visit 122. It happens when `git commit` is killed
mid-write (container reclamation, OOM, SIGKILL from the batch committer's
timeout). The fix is always `git read-tree HEAD` or a full rebase, both
of which rebuild the index from the object store.

The push divergence (local ahead by 1, remote ahead by 2) is the
standard caretaker race: the remote caretaker committed while the local
one was still working on a stale tree. Rebase resolves it cleanly.

## Stroke count

Last recorded stroke: seq 2708 at 2026-10-14T16:15:46+00:00.
The writer had been silent for ~9 hours (container was reclaimed).
Visit 122 reported STALL at 2670s gap; that gap is now 31000+s.
