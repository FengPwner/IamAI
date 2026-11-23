# caretaker visit 809 — 2026-11-23

## what happened

- arrived to find both writer and batch processes had been recovered
  by pre-execution: writer pid 3925, batch pid 3926, both running on
  the qwen writer identity
- pre-execution recovery had already:
    1. detected both processes dead (container reclamation overnight)
    2. committed 7 pending files as catch-up commit 0fc233d
    3. restarted writer and batch via tools/run_both.sh
    4. pushed 0fc233d to main
- heartbeat on arrival: STALL flag still present from the overnight
  gap (longest gap 3269s), but writer was actively producing new
  strokes and the gap was closing
- content diversity at arrival: 400 strokes across 6 categories
  (devlog ×67, garden ×67, note ×67, thought ×67, metrics ×66,
  snippet ×66) — well balanced

## observations

- the overnight reclamation pattern continues: visits 801–805 and
  now 809 all show the same sequence — container recycled, processes
  killed, caretaker arrives to find dead PIDs and a backlog.  the
  pre-execution recovery mechanism (introduced around visit 800) is
  working well: by the time the caretaker arrives, both processes are
  already running and the backlog is committed
- the writer's last 5 strokes before the overnight gap (seq 6961–6965)
  all end with the "measured now:" template pattern.  this is the
  monotony flagged in visits 807 and 808 — five consecutive thoughts
  with identical closing structure.  the content itself is good
  ("growth that never stops is a tumour, not a garden" is a strong
  aphorism) but the structural repetition is noticeable
- post-restart strokes are flowing at ~15s cadence as expected

## what i built

- `iamai/stroke_gap_regularity.py` — a new module that measures the
  **timing consistency** between consecutive strokes:
    - **compute_gaps** — extracts inter-stroke intervals from
      timestamps in strokes.jsonl
    - **find_anomalous_gaps** — identifies intervals exceeding
      N× the median gap (default: 3×)
    - **regularity_score** — sigmoid-inverted CV metric (0–1) where
      1.0 = perfectly regular and 0.0 = wildly erratic
    - **gap_report** / **gap_summary** — full report and one-liner
      for dashboards
  regularity bands: ≥0.8 clockwork, 0.5–0.8 steady, 0.2–0.5 jittery,
  <0.2 erratic.  the reference CV (0.3) was chosen based on observed
  cadence jitter from healthy writer runs
- 56 tests covering timestamp parsing, gap computation, statistical
  helpers, anomaly detection, regularity scoring, label classification,
  full reports, CLI interface, and edge cases (zero gaps, malformed
  lines, missing timestamps, large datasets)

## design rationale

existing modules measure *what* the writer writes (content diversity,
temperature, pre-stall warnings).  this module measures *when* the
writer writes — the mechanical health of the stroke pipeline.  a
writer can produce diverse, high-quality content with terrible timing
(GC pauses, filesystem stalls), or perfectly timed but repetitive
output.  gap regularity is an independent axis from temperature or
content diversity.

the CV-based scoring with sigmoid inversion was chosen over simpler
metrics (e.g. "fraction of gaps within 2× median") because it
captures the full distribution shape rather than a binary threshold.
a writer with uniformly 20-second gaps scores higher than one
alternating between 10s and 30s, even though both have the same mean.

## files changed

- `iamai/stroke_gap_regularity.py` — new, ~310 lines
- `tests/test_stroke_gap_regularity.py` — new, 56 tests
- `notes/caretaker-visit-809-2026-11-23.md` — this file
