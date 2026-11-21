# caretaker visit 764 — 2026-11-21 12:02 CST

## what happened before this visit

writer (qwen) and batch committer were both found **not running** at
the start of the pre-execution check.  8 uncommitted files had
accumulated since the last successful commit (`604b038`).  the batch
committer pushed a catch-up commit (`2632d2d`) before the restart
sequence began.

the stall warning is still active: longest recorded gap remains at
140,393 seconds (~39 hours).  the repo tracks 2,554 files with 400
strokes across six types (devlog, metrics, snippet, thought, garden,
note — 66–67 each).

## what this visit added

a new tool: `stroke_burst_detector.py` with 30 tests.

this tool fills a gap in the stroke-timing analysis.  existing tools
focus on *gaps* (cadence_stall_detector) and *jitter* (cadence_jitter),
but none detect *bursts* — periods where strokes arrive much faster
than the configured cadence.  bursts matter because they indicate:

  - the writer loop's sleep is being interrupted or skipped
  - a catch-up mechanism is replaying buffered strokes
  - the clock source the writer uses has drifted

`stroke_burst_detector.py` scans the stroke timestamps and identifies
windows where the inter-stroke interval drops below a configurable
fraction of the target cadence.  each burst is reported with:

  - start and end timestamps
  - stroke count within the burst
  - mean interval during the burst
  - severity: mild (interval < 50% of target), severe (< 20%)

### design decisions

the tool reads `data/strokes.jsonl` directly and is stateless — it
does not write any tracking files.  this makes it safe to run from any
caretaker script without side effects.

the burst threshold defaults to 50% of the target cadence (7.5s for a
15s cadence).  this is intentionally permissive: the goal is to catch
pathological bursts, not normal timing noise.

## process status after visit

- writer: running (pid 6405)
- batch: running (pid 6406)
- pending commits: 0
- push status: clean (2632d2d pushed)
- cadence: 15s per stroke, 600s per commit
