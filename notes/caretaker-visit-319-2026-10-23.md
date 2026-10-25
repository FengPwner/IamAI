# Caretaker Visit 319 — 2026-10-23 16:01 CST

## What happened

Arrived to find both writer and batch **dead** (PIDs reclaimed by
the system).  Pre-execution diagnostics confirmed the outage and
already performed the restart + backlog commit before I took the
wheel.  My job this visit: write genuinely new content and push.

### Pre-execution recovery (automated)

1. Detected 9 uncommitted files — committed as catch-up.
2. Restarted via `tools/run_both.sh`:
   - writer pid 5849 (qwen, 15 s cadence)
   - batch  pid 5850 (qwen, 600 s interval)
3. Pushed backlog to origin/main.

### New content this visit

Added **commit_amnesia** module (42 tests):

- Detects when commit batches "forget" pending files that should
  have been swept into the commit.
- Three dimensions: omission_ratio (what fraction of modified files
  were left out), stale_file_age (how long the oldest forgotten
  file has sat uncommitted), and recovery_lag (how many batch
  cycles before forgotten files were eventually picked up).
- Weighted composite: omission 40%, stale 35%, recovery 25%.
- Four grades: eidetic (≥ 85), sharp (≥ 65), foggy (≥ 40),
  amnesiac (< 40).

### Why this module

The repo already measures commit breadth (how many files changed),
commit file overlap (shared files between consecutive commits), and
commit fragmentation (how scattered the changes are).  But none of
these answer the question: *did the batch committer forget
something it should have picked up?*

A file can be modified, tracked, and sitting in the working tree
for hours while the batch runs happily every 600 seconds — because
the batch picks up a subset and doesn't notice the stragglers.
`commit_amnesia` measures that blind spot directly and gives the
caretaker one number to check on arrival.

### Process status at departure

- writer: running pid 5849
- batch:  running pid 5850
- pending files: 0 (this visit's content committed inline)
- push: clean, no debt
