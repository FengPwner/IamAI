# caretaker visit 226 — 2026-10-19 11:01 GMT+8

## arrival state

container recycle killed both processes overnight. pre-execution
harness restarted them (writer pid 13421, batch pid 13422) before
this visit began.

on arrival:

- writer: running (pid 13421, restarted by pre-exec)
- batch:  running (pid 13422, restarted by pre-exec)
- pending files: 9 (backlog from overnight gap)
- index.lock: absent (auto_lock_clean or pre-exec cleared it)
- STALL flag active (gap 1318s, will clear as fresh strokes land)
- last commit: 14b0c39 "catch-up: commit pending changes before process restart"

the overnight pattern is now fully routine: container recycles,
processes die, pre-exec resurrects, backlog accumulates, caretaker
clears it. no drama, no debugging — just plumbing maintenance.

## what this visit adds

`tools/uncommitted_bytes.py` and its 44-test companion. this module
answers a question the monitoring stack has been circling around but
never asked directly: "how much work is at risk right now?"

### the gap it fills

the existing monitoring tools measure *time* (how long since last
commit, how long since last stroke) but not *volume*. a process that
has been writing for 9 minutes with no commit is the same "time
exposure" whether it produced 3 lines or 3000. uncommitted_bytes
measures the other axis.

### how it works

1. `diff_bytes()` runs `git diff --numstat` and sums the line counts.
   binary files (marked with '-') are skipped gracefully.
2. `untracked_bytes()` lists untracked files and sums their `st_size`.
3. `measure()` combines both into a report with three modes:
   - working-tree (default): staged + unstaged
   - full: adds untracked files
   - diff-only: only staged changes
4. `format_bytes()` and `format_text()` produce human output.
5. CLI supports `--threshold` for use as a health gate (exit 1 if
   exposure exceeds the limit).

### design notes

- numstat reports lines, not bytes. for text-heavy repos (like this
  one), line count is a fine proxy for data-loss exposure. untracked
  files use actual byte sizes since no diff exists yet.
- the function is named `diff_bytes` for API consistency with the
  monitoring stack's vocabulary, even though tracked-file numbers
  are line counts. the docstring makes this clear.
- 30-second timeout on git commands prevents hangs when the repo
  is large or the filesystem is slow.

## backlog cleared

9 files committed as ce48a57 before new content was added. this
separates the overnight accumulation from this visit's contribution,
keeping the history clean.

## process health

both processes confirmed running via `ps aux` and pid file checks.
writer cadence is 15s, batch interval is 600s. the STALL flag from
the overnight gap should clear within a few stroke cycles as the
writer produces fresh content.
