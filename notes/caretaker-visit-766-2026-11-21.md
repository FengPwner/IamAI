# caretaker visit 766 — 2026-11-21 14:02 CST

## what happened before this visit

writer (qwen) pid 6424 and batch committer pid 6425 had both been
recycled — found not running on inspection.  visit 765 had added
`stroke_diversity_analyzer.py` with 19 tests.  seven files of backlog
were committed as catch-up and both processes restarted (new pids
6439/6440).

## what this visit added

a new tool: `stroke_momentum_tracker.py` with 22 tests.

this tool tracks whether the writer's stroke production rate is
accelerating, steady, or decelerating.  it divides the timeline into
fixed-width windows (default 1 hour), counts strokes per window, and
fits a linear regression over the last N windows (default 6).

### metrics computed

  - windows: list of {start, end, count} per time window
  - slope: change in strokes-per-window per window (strokes/window²)
  - avg_rate: mean strokes per window over measured range
  - momentum: "accelerating" | "steady" | "decelerating"
  - peak_window: window with highest count
  - trough_window: window with lowest count
  - verdict: human-readable summary

### thresholds

  - accelerating:  slope > +0.5 strokes/window²
  - decelerating:  slope < -0.5 strokes/window²
  - steady:        otherwise

### why this matters

diversity (visit 765) tells you *what* the writer is producing.
momentum tells you *how fast* the writer is trending.  a writer that
is steadily producing is healthy; one that is decelerating may be
running out of ideas or hitting a resource limit; one that is
accelerating may be in a burst that will burn out.  combined with
diversity and burst detection, momentum completes the picture of
writer health.

### exit codes

  0 — steady or accelerating (healthy)
  1 — decelerating (needs attention)
  2 — data file not found
  3 — insufficient data

## process status after restart

  writer[qwen]: running pid 6439
  batch [qwen]: running pid 6440
  cadence: one stroke every 15s, one commit every 600s
