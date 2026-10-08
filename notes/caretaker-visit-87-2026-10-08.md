# Caretaker Visit 87 — 2026-10-08 15:00

## Status

- Writer (pid 1201) and batch committer (pid 1202) were found **stopped**
  on arrival — both restarted via `tools/run_both.sh`.
- Stale `.git/index.lock` from a crashed git process was blocking all
  commits; removed before restart.
- 8 uncommitted files from the previous cycle had already been swept by
  the batch committer's catch-up commit (`08941b9`) once the lock was
  cleared — no manual backlog commit needed.
- Push: `Everything up-to-date` — remote in sync.

## New Contribution

Added `iamai.stroke_recovery_time` — measures how quickly the writer
resumes stroke production after each restart event.

The existing `stall_classifier` answers "is the writer dead?" and
`stroke_rate` answers "how fast is it writing?". This module answers
"how fast does it come back?" — the second derivative of reliability.

Key design choices:

- **Git-log-based restart detection** — looks for commit messages
  matching known caretaker patterns (catch-up, caretaker visit, etc.)
  rather than relying on external process monitors.
- **Strict-after matching** — only counts strokes *strictly after* the
  restart timestamp, avoiding false positives from stale buffered writes.
- **Four-tier classification** — fast (<60s), normal (60-300s),
  slow (300s+), stalled (no subsequent stroke found).
- **Negative-gap sentinel** — stalled restarts get gap=-1 instead of
  None, so they sort correctly and show up in summaries.

14 tests, all passing.

## Stats

- 1924 strokes across 481 tracked files
- 981 commits deep
