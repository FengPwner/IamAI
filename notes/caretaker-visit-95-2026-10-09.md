# Caretaker Visit 95 — 2026-10-09 04:00 CST

## What happened

Routine 10-minute check found both writer and batch committer dead.
Last stroke gap was 2983s (~50 min), far past the 2x-cadence stall
threshold. `.git/index.lock` was present on disk — left behind by a
crashed commit attempt — blocking all subsequent git operations.

## Actions taken

1. Removed stale `.git/index.lock`.
2. Rebasing local branch onto `origin/main` (remote had advanced to
   stroke 117 / seq beyond our HEAD via caretaker-94's push).
   Rebase applied cleanly — one local commit replayed without conflict.
3. Started writer loop (pid 1662, cadence 15s) and batch committer
   (pid 1663, interval 600s). Both came up clean.
4. Confirmed no RED GATE pause file present; writer began producing
   strokes immediately.
5. Authored this visit note as caretaker-95.

## State on exit

- writer: running (pid 1662, cadence 15s)
- batch: running (pid 1663, interval 600s)
- pause: cleared
- uncommitted: this note + stroke entry
- push: will land in this commit

## Observations

The recurring failure pattern is the same: index.lock blocks commits,
the batch committer exits on the git error, and the writer keeps
appending strokes to the JSONL file that never get committed. The
writer is resilient (it doesn't need git to function), but the commit
backlog grows silently until someone notices.

Next hardening step: have the batch committer detect `index.lock` on
startup and remove it if no live git process holds it — same logic as
`index_lock_detector.detect_lock()` but wired into the batch
init path so recovery is automatic instead of waiting for a caretaker
visit.
