# caretaker visit 246 — 2026-10-20 13:00 GMT+8

## arrival state

- writer: NOT running (killed during container sweep)
- batch: NOT running (same)
- git lock: stale lock from previous crashed commit, blocking new commits
- pending files: 9 (strokes, writer state, docs, notes — accumulated
  since visit 245)
- unpushed commits: 1 (from the pre-exec restart)
- stall flag: STALL — writer silent 1561s past 2x cadence

## what happened

tenth consecutive dead-on-arrival visit. container sweep killed both
processes sometime between visit 245 (12:01) and this check (13:00).
the pre-exec harness detected the stall, removed the stale git lock,
committed the 9-file backlog, and restarted both writer and batch before
the caretaker arrived.

this visit:
1. verified lock file cleared and both processes alive (pid 15572/15573)
2. committed remaining backlog (commit 8c01625)
3. wrote the ``restart_cost`` module — measures what each restart actually
   costs in silence time, lost strokes, and recovery speed
4. wrote 34 tests, all passing
5. committed and pushed everything

## action taken

1. **lock cleanup** — removed stale ``.git/index.lock`` left by a crashed
   git process. this has been a recurring issue: the container sweep kills
   git mid-commit, and the lock file persists.

2. **backlog commit** — 9 files committed in one batch: strokes.jsonl,
   writer_state, DEVLOG, GARDEN, METRICS, and four notes files.

3. **process restart** — ``tools/run_both.sh`` restarted both writer
   (pid 15572) and batch committer (pid 15573). writer confirmed actively
   producing strokes post-restart.

4. **wrote restart_cost module** — ``iamai/restart_cost.py`` provides
   five metrics:

   - ``silence_gap``: seconds between last pre-restart stroke and first
     post-restart stroke
   - ``catchup_time``: seconds until inter-stroke interval returns to
     baseline (within 1.5x tolerance)
   - ``strokes_lost``: estimated strokes that would have been produced
     during the gap, given baseline cadence
   - ``recovery_ratio``: actual vs expected stroke count in a post-restart
     window — >1.0 means sprinting, <1.0 means warming up
   - ``baseline_cadence``: median inter-stroke interval from the last N
     pre-restart strokes

   plus a composite ``analyse_restart()`` that returns all five metrics
   in one report.

   this plugs into the existing diagnostic stack:
   - caretaker_verdict → is something wrong?
   - stall_classifier → why?
   - process_graveyard → when does it die?
   - stroke_diversity → is the output good?
   - **restart_cost → what did the fix cost?**

5. **wrote 34 tests** — ``tests/test_restart_cost.py`` covers every
   function in isolation plus the composite report with edge cases
   (empty data, zero cadence, negative gaps).

6. **pushed** — all new files and visit note in one commit.

## observations

- ten consecutive dead-on-arrival visits (237–246), all between 01:00 and
  13:00. the process_graveyard module should have enough data by now to
  confirm a pattern. if the sweep schedule is fixed, we could preemptively
  checkpoint state before the kill window opens.

- the stale git lock issue appeared in visits 116, 245, and now 246.
  it is always a side effect of the container sweep killing a git process
  mid-operation. a pre-restart lock check in ``run_both.sh`` would
  eliminate this class of failure entirely.

- the restart_cost module answers a question that has been nagging: if
  the writer dies for 30 minutes and the batch committer for 10, what
  is the actual output impact? with baseline cadence at ~900s per stroke
  (15 minutes), a 30-minute gap costs roughly 2 strokes. not catastrophic,
  but it compounds — ten visits × 2 strokes = 20 strokes that never
  happened.

## streak

total strokes: 400+
categories: devlog ×67, garden ×67, snippet ×67, thought ×67,
            metrics ×67, note ×67
