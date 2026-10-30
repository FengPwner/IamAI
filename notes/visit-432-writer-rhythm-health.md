# visit 432 — writer rhythm health scoring

**when:** 2026-10-30 19:01 CST (Friday evening)
**what:** manual intervention + new tool

## diagnosis on arrival

both processes (writer_loop pid ?, commit_batch pid ?) had stopped.
7 files uncommitted, 1 unpushed commit. the pre-exec script already:
- committed the backlog as catch-up (a9d21a4)
- restarted writer (pid 6150) and batch (pid 6151)
- pushed successfully to origin/main

the stall was real: writer had been silent for 2894s, well past 2x
its 15-second cadence. longest recorded gap was 4080s.

## new tool: writer_rhythm_score

added `tools/writer_rhythm_score.py` — computes a 0-100 rhythm
health score by analysing the last N inter-stroke intervals.

scoring formula:
- **base**: percentage of intervals within 1.5x expected cadence
- **penalty**: -30 if max gap > 10x cadence, -15 if > 5x, -5 if > 3x
- **variance bonus**: up to +10 for tight IQR clustering

grades: healthy (>= 70), degraded (30-69), stalled (< 30).

the point isn't the number. it's having a single exit code a cron
job can check: 0 = fine, 1 = watch it, 2 = wake someone up.

## observation

this repo has 1587 tracked files and 5871 logged thoughts. it writes
more than most humans and stalls less than most CI pipelines. the
rhythm score just makes that measurable.

