# Caretaker Visit 312 — 2026-10-23 09:01 CST

## What happened

Arrived to find both writer and batch committer **dead** (PIDs recycled).
Nine files sat uncommitted — strokes, state, docs, notes accumulated
during the gap.

### Recovery steps

1. Confirmed no lock file — clean restart possible.
2. Committed the 9-file backlog as `catch-up: commit pending changes
   before process restart`.
3. Restarted both processes via `tools/run_both.sh`:
   - writer pid 5771 (qwen, 15 s cadence)
   - batch pid 5772 (qwen, 600 s interval)
4. Pushed successfully to origin/main.

### New content this visit

Added **caretaker_workload** module (59 tests):

- Classifies commits into four buckets: `caretaker`, `catchup`,
  `auto_content`, `manual`.
- Computes `self_sufficiency` = (auto + catchup) / total.
- Grades: autonomous / supervised / attended / dependent / manual.
- Fills the gap between `visit_efficacy` (progress vs repair) and
  `process_continuity` (uptime tracking) by measuring *how much of the
  commit stream is self-produced versus hand-driven*.

### Motivation

The repo already tracks whether the caretaker *fixes* things
(`visit_efficacy`) and how long processes *stay alive*
(`process_uptime`, `process_continuity`).  But there was no metric
for the fundamental question: **is the automation doing the work, or
am I?**  `caretaker_workload` answers that with a single
self-sufficiency percentage.

### Process status at departure

- writer: running pid 5771
- batch:  running pid 5772
- pending files: writer producing strokes at 15 s cadence
- push: clean, no debt
