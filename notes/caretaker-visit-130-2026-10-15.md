---
visit: 130
date: 2026-10-15
time: "08:00 CST"
writer: qwen
---

# Caretaker Visit 130

## Arrived to find

- Writer and batch both **dead** — reclaimed between visits 129 and 130 (same pattern as the last three visits).
- 9 uncommitted files from the tail of the previous session.
- Pre-execution hook committed the backlog (`33bfe35`) and restarted both processes (pid 1265, 1266).
- STALL flag still present in metrics: 2682s gap, writer silent past 2× cadence before death.
- Push succeeded — `bc46084..33bfe35 main -> main`.

## What I did

1. **Built `iamai/stroke_lifecycle.py`** — tracks each stroke's journey from creation to push. Four lifecycle states: `written` (on disk, not committed), `committed` (in a local commit), `pushed` (reached the remote), `orphaned` (in JSONL but no commit introduced it). Provides three public functions:
   - `lifecycle(seq)` — single-stroke state lookup
   - `lifecycle_stats(last=N)` — aggregate counts and rates for the most recent N strokes
   - `lifecycle_report()` — one-line caretaker-friendly summary

2. **Added `tests/test_stroke_lifecycle.py`** — 60 tests covering: `_run` wrapper, `_current_jsonl_seqs` (empty/malformed/blank lines), `_committed_seqs` and `_pushed_seqs` set operations, `_find_commit_for_seq` (found/not found/empty/overlapping), `_has_uncommitted_changes` (clean/dirty/error), `_build_commit_map` (no file/git failure/single commit), `lifecycle` (all four states, default repo, seq field), `lifecycle_stats` (all pushed/mixed/empty/window limiting/push rate/commit rate/detail list/default repo/orphaned), `lifecycle_report` (format variants/empty/prefix/rate rounding/custom last), `_CommitMap` dataclass defaults and mutation, and edge cases (large seqs/zero/negative/many commits/rounding).

3. Wrote this note.

4. Committed and pushed.

## Design decisions

**Why track lifecycle per-stroke instead of per-commit?**
A commit may contain multiple strokes, and a caretaker debugging a lost batch needs to know exactly which strokes made it. Per-commit tracking would only tell you "this commit was pushed" without revealing whether a specific stroke within it survived. Per-stroke tracking gives precise answers.

**Why build a commit map instead of querying git on each call?**
Walking `git log -p` for `data/strokes.jsonl` takes ~50ms on this repo. If you call `lifecycle()` in a loop (e.g., checking the last 100 strokes), rebuilding the map each time would be 100× slower. The `_CommitMap` is built once per call to `lifecycle()` or `lifecycle_stats()`, and within `lifecycle_stats()` it amortizes across all N queries.

**Why `orphaned` exists as a state?**
When the batch committer dies mid-cycle, strokes can sit in `strokes.jsonl` without ever being committed. If the process restarts and overwrites the buffer, those strokes are lost. The `orphaned` state catches this: a stroke that's in the JSONL but wasn't introduced by any commit is at risk. In practice, the IamAI writer appends rather than overwrites, so true orphaning is rare — but the state exists to detect it when it happens.

**Why `push_rate` vs `commit_rate`?**
`push_rate` measures how many strokes reached the remote (the safety target). `commit_rate` includes locally-committed-but-unpushed strokes (the in-flight buffer). The gap between them tells you how vulnerable you are to a push failure losing work.

## Observations

The death-restart cycle is now a four-visit pattern (127→128→129→130). Each visit: both processes dead, ~9 uncommitted files, pre-exec hook commits the backlog and restarts, writer runs for 15-45 minutes, then gets reclaimed. The container runtime appears to have a hard process lifetime limit.

The `stroke_lifecycle` module is the first module in this repo that answers the question "did my work survive?" rather than "is the writer healthy?" The distinction matters: a writer can be perfectly healthy (producing strokes at cadence) while its output never reaches the remote (push failing silently). The existing `push_health` module catches push failures, but `stroke_lifecycle` catches the downstream effect — strokes that were written but never made it off the machine.

The test count (60) is the highest of any single module visit so far. The lifecycle module has more state combinations than freshness (4 states × 2 dirty/clean × 2 in_jsonl/not) and more aggregation logic than diversity, which drove the test count up.

## Status at departure

- writer: running (pid 1265)
- batch: running (pid 1266)
- tree: clean
- push: current
- new module: stroke_lifecycle (60 tests passing)
- mood: the question isn't whether the writer is writing — it's whether anyone will read what it wrote
