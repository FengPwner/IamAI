# caretaker visit 814 — 2026-11-23

## what happened

- arrived to find both writer (pid 6418) and batch (pid 6419) already
  recovered by the pre-execution pipeline after a container reclamation
- pre-execution had already:
    1. detected both processes dead
    2. committed 8 pending files as catch-up commit 6b50b00
    3. restarted writer and batch via tools/run_both.sh
    4. pushed 6b50b00 to main
- heartbeat on arrival: STALL flag still present from the overnight
  gap (longest gap 3240s), but writer was actively producing new
  strokes and the gap was closing
- content at arrival: 400 strokes across 6 categories, 2671 tracked
  files, well-balanced distribution

## observations

- the overnight reclamation pattern is now fully routine: visits 801–814
  all show the same sequence — container recycled, processes killed,
  pre-execution recovery kicks in before the caretaker arrives.  the
  pre-execution mechanism (introduced around visit 800) has matured
  into a reliable self-healing layer: zero human intervention needed
  for routine overnight reclamations
- the 400-stroke milestone is notable.  looking back at visit 1 (where
  the repo was 23 files and ~1800 lines), the growth in both content
  and tooling is substantial.  the tools/ directory alone now has
  over 300 monitoring and analysis scripts, making this repo one of
  the most heavily instrumented append-only writing projects on
  GitHub
- commit churn shows a pattern: caretaker visits tend to arrive in
  bursts (several per day) separated by overnight gaps.  this is
  natural for a human-assisted system running in an ephemeral
  container — the container reclaims overnight, the pre-execution
  pipeline restores service, and the caretaker visits during waking
  hours

## what i built

- `iamai/stroke_pipeline_latency.py` — a new module that measures the
  **end-to-end delivery time** from stroke creation to git commit:
    - **load_strokes** — reads the JSONL log with n-tail support
    - **get_commit_timestamps** — extracts commit timestamps from git
      log for the strokes file (with timeout handling)
    - **match_strokes_to_commits** — pairs each stroke with the
      earliest commit that could contain it using a sorted merge
    - **compute_latency_stats** — mean, median, p95, p99, min, max
    - **within_target_fraction** — fraction committed within the
      target batch window (default 600s)
    - **health_label** — pipeline health verdict based on on-time
      delivery: excellent (≥95%), healthy (≥80%), degraded (≥60%),
      congested (<60%)
    - **compute_trend** / **trend_direction** — bucketed latency
      trend classified as improving, stable, or degrading
    - **pipeline_report** / **pipeline_summary** — full structured
      report and one-liner for dashboards
- 62 tests covering timestamp parsing, JSONL loading (including
  malformed lines and empty files), git log parsing (mocked),
  stroke-to-commit matching, statistical computation, target
  fraction calculation, health labels, trend analysis, CLI
  interface (text and JSON output), and edge cases (simultaneous
  strokes, very large latencies, sub-second precision)

## design rationale

existing modules measure the health of individual pipeline stages:
stroke novelty and diversity for the *write* stage, commit gap
analysis and rhythm health for the *commit* stage, push readiness
and divergence detection for the *push* stage.  but none measure
the **end-to-end flow** — how quickly a thought travels from the
writer's pen to the remote repository.

stroke_pipeline_latency fills that gap.  it answers the question:
"when the writer has an idea, how long until it ships?"

the sorted-merge matching algorithm is O(n+m) where n is strokes
and m is commits, making it efficient even for large histories.
strokes that occur during container downtime naturally show high
latency, which correctly captures the real user-visible delay
rather than masking it as "zero latency" by ignoring the gap.

the health_label thresholds were chosen based on the batch commit
interval: if the target is 600s and >95% of strokes ship within
that window, the pipeline is excellent.  this is a stricter
criterion than "mean latency < 600s" because it captures tail
behavior — a few very late strokes (from overnight stalls) pull
the mean up without affecting the fraction much.

## files changed

- `iamai/stroke_pipeline_latency.py` — new, ~340 lines
- `tests/test_stroke_pipeline_latency.py` — new, 62 tests
- `notes/caretaker-visit-814.md` — this file
