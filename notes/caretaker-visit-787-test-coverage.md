# visit 787 — test coverage for event_interval + commit_churn

2026-11-22 12:03 CST. human-requested caretaker check. processes found
dead (overnight stall pattern, gap ~3000s, consistent with visits
782–786). backlog flushed, processes restarted. this visit adds test
coverage for the last two of the four previously untested modules.

## what this visit adds

two new test files covering modules that had zero test coverage:

### test_event_interval.py (34 tests)

`event_interval.py` computes interval statistics from sorted timestamp
lists — count, min, max, mean, median, p95, p99, and coefficient of
variation. it is the module that answers "how regular is this writer?"

test areas:

1. **_percentile edge cases** — empty list, single element, two
   elements, known percentile values, boundary where interpolation
   index exceeds array length.

2. **compute_intervals errors** — ValueError for empty and single-
   timestamp inputs, error message includes the count.

3. **Metronomic cadence** — perfect 15s and 600s cadence produce
   cv=0.0, min=max=mean. two-timestamp edge case.

4. **Jittery cadence** — mixed intervals, high CV detection,
   unsorted input handled correctly (internal sort).

5. **Rounding** — mean/median/p95/p99 rounded to 2 decimals,
   cv rounded to 4 decimals.

6. **classify_rhythm boundaries** — exact sweep of all four
   thresholds: 0.15 (metronomic→steady), 0.40 (steady→uneven),
   0.80 (uneven→erratic).

7. **IntervalStats.to_dict** — confirms raw intervals list is
   omitted from the serialised dict.

8. **Integration** — overnight stall scenario (3000s gap in 15s
   cadence), steady writer with jitter, 1000-timestamp scale test.

### test_commit_churn.py (38 tests)

`commit_churn.py` detects when the writer is rewriting instead of
adding. the churn index (0–100) classifies recent commits as healthy,
churning, or stalled.

test areas:

1. **_file_overlap** — empty sets, full overlap, partial overlap,
   no overlap, single file.

2. **_rewrite_ratio** — pure addition (0.0), pure rewrite (1.0),
   pure deletion (0.0), zero-zero floor case, mixed ratios.

3. **_per_commit_churn** — no-overlap pure add (0.0), full-overlap
   rewrite (1.0), partial mixed (0.5), missing keys handled.

4. **churn_index edge cases** — empty list, single commit, two
   commits with no overlap.

5. **Healthy workflow** — additive distinct files, mostly additive
   with some index.md overlap.

6. **Stalled workflow** — rewrite loop (same files, high ins+del),
   moderate overlap churning.

7. **_band thresholds** — exact boundaries at 29/30 and 59/60.

8. **Output structure** — summary format, per_commit length,
   score clamped 0–100, high-churn count.

9. **Integration** — realistic 20-commit growth pattern, 15-commit
   stall cycle.

## test gap closing

after this visit, only two modules remain without tests:
- `push_diag.py`
- `ssh_key_mismatch.py`

the untested module count has dropped from four (visit 785) to two.
total test count across both new files: 72 tests.

## overnight stall continues

the stall pattern persists with remarkable consistency:

| visit | gap (s) | severity  |
|-------|---------|-----------|
| 782   | ~2978   | moderate  |
| 783   | ~2978   | moderate  |
| 784   | ~2640   | moderate  |
| 785   | ~2945   | moderate  |
| 786   | ~2915   | moderate  |
| 787   | ~3000   | moderate  |

mean ~2910s (48.5 min), std dev ~130s. this is a fixed idle timeout
in the hosting environment. no action needed beyond the standard
restart-and-resume pattern.

## process status

writer: running, cadence 15s.
batch: running, interval 600s.
tree clean, push confirmed.
