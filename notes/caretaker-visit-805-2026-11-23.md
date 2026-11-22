# caretaker visit 805 — 2026-11-23

## what happened

- arrived to find writer (pid 6734) and batch (pid 6735) freshly
  restarted by the pre-execution recovery after container recycle
- 7 pending files had already been committed and pushed in the
  recovery pass (commit 89baac8)
- created `commit_pulse_monitor` — a new iamai/ module that measures
  whether git commits arrive at the expected cadence (default 600s /
  10 min), computing gap statistics, a 0–1 pulse score, missed-beat
  and burst counts, and an overall healthy/irregular verdict
- wrote 32 tests covering _compute_gaps(), compute_pulse_score(),
  count_missed_beats(), count_bursts(), pulse_report() with mocked
  git, pulse_summary() formatting, and edge cases (empty, single,
  perfect rhythm, total chaos, window filtering)

## observations

- the writer's stroke cadence (15s) and the batch commit interval
  (600s) are separate rhythms; cadence_adherence monitors the former
  but nobody was monitoring the latter — this module closes that gap
- current state: 400 strokes, 2650 tracked files, stroke gap ~3023s
  from the container recycle window
- both processes healthy at time of visit, 0 pending files
- push relay confirmed clean (89baac8 already on remote)

## design notes

- pulse_score uses a band-and-weight approach: gaps within [0.5×, 1.5×]
  expected get a proximity weight, then the score is fraction_in_band ×
  mean_weight.  This avoids the binary cliff of pure threshold scoring
- missed beats = gaps > 2× expected (silence); bursts = gaps < 0.3×
  expected (rapid-fire catch-up).  Together they characterise the two
  failure modes of the commit pipeline
- CLI supports --json for integration with caretaker dashboard scripts

## files changed

- `iamai/commit_pulse_monitor.py` — new, full module
- `tests/test_commit_pulse_monitor.py` — new, 32 tests
- `notes/caretaker-visit-805-2026-11-23.md` — this file
