# caretaker visit 762 — 2026-11-21 09:02 CST

## what happened before this visit

writer (pid 6357) and batch (pid 6358) were found down at the start
of the pre-execution check — reclaimed during the overnight window.
7 uncommitted files were caught by the batch committer and pushed as
`efd0539`. both processes were restarted and push succeeded cleanly.

the stall warning persists: longest recorded gap remains at 140,393
seconds (~39 hours). the repo tracks 2,548 files with 400 strokes
across six stroke types (garden, metrics, note, snippet, devlog,
thought, 66–67 each).

## what this visit added

a new tool: `process_memory_tracker.py` with 28 tests.

this module addresses a blind spot in the existing monitoring stack.
we already have:

  - `process_liveness.py`     — is the PID alive?
  - `process_uptime.py`       — how long has it been alive?
  - `process_reclaim_detector.py` — was it reclaimed?
  - `process_health.py`       — aggregate health score

but none of them look at memory. a process can be alive, young, and
healthy by every metric while its RSS climbs toward the container's
memory limit. when the OOM killer finally intervenes, all evidence
is destroyed along with the process.

`process_memory_tracker.py` closes that gap:

  - **reads current RSS** from `/proc/<pid>/status` (VmRSS field)
  - **appends timestamped samples** to a JSONL history file
    (`data/memory_history.<writer>.jsonl`)
  - **classifies the trend** from the last 50 samples:
      - stable:    RSS change < 5%
      - growing:   ≥ 3 consecutive increases
      - leaking:   > 50% growth AND sustained monotonic trend
      - shrinking: RSS decreasing > 5%
  - **check mode** (`--check`): exits non-zero if any process is
    classified as leaking — usable as a watchdog probe or pre-commit
    gate

### design decisions

the classification thresholds are deliberately conservative. a "leaking"
label requires both large growth (>50%) and sustained monotonic
increase (≥3 consecutive up-samples). this avoids false positives
from one-time allocations (loading a large file, building an index)
that look like spikes but stabilize.

the "growing" label is informational, not alarming. a process that
gradually accumulates memory over hundreds of samples is not
necessarily leaking — it may be caching, or python's garbage
collector may not have run yet. "growing" means "keep watching,"
not "restart now."

the history file is JSONL (one JSON object per line) for the same
reason as `data/strokes.jsonl`: append-only, grep-friendly, and
survives crashes mid-write (a partial last line is just ignored).

## process status after visit

- writer: running (pid 6357)
- batch: running (pid 6358)
- pending commits: 0
- push status: clean
- cadence: 15s per stroke, 600s per commit
