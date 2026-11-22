# visit 789 — test coverage for commit_churn

2026-11-22 14:02 CST. human-requested caretaker check. processes
found dead on arrival (overnight stall continues, gap ~3068s).
backlog of 7 uncommitted files flushed as 4e4e746, processes
restarted (writer pid 6408, batch pid 6409), push confirmed.

## what this visit adds

test_commit_churn_index.py — the last module in iamai/ without
dedicated tests.  after visits 785–788 closed every other gap,
commit_churn remained as the sole untested core metric.  now zero
modules remain without coverage.

### test_commit_churn_index.py (38 tests)

`commit_churn.py` measures how much recent commit activity is
rewriting versus adding new content.  it answers the question:
**is the writer making progress or running in place?**  this is
one of the primary health signals the caretaker uses to decide
whether intervention is needed.

test areas:

1. **_file_overlap** — both empty, current empty, previous empty,
   full overlap, half overlap, disjoint, subset, superset.

2. **_rewrite_ratio** — pure add (ratio 0.0), pure delete (0.0),
   pure rewrite (1.0), mostly add, mostly delete, both zero,
   both one, asymmetric large values.

3. **_per_commit_churn** — no overlap + pure add (score 0.0),
   full overlap + pure rewrite (score 1.0), half overlap + mixed,
   empty commit files, missing dict keys default, weighted blend
   verification with known expected value.

4. **churn_index integration** — empty input returns healthy with
   zero score, single commit, two additive commits with no overlap,
   heavy churn produces stalled band at score 100, mixed pattern
   produces valid score in range, score clamped to 100, healthy
   band verification, summary text contains expected statistics,
   per_commit length matches input, many low-churn commits.

5. **_band threshold boundaries** — 0 → healthy, 29 → healthy,
   30 → churning, 59 → churning, 60 → stalled, 100 → stalled.

6. **CLI integration** — default human output contains expected
   strings, --json produces valid JSON with correct schema,
   --count limits analysis window, exit code matches band
   (healthy=0, churning=1, stalled=2).

7. **Edge cases** — negative insertions/deletions don't crash,
   very large numbers, files as list instead of set (JSON
   deserialization scenario), JSON serializability of result,
   identical consecutive commits, alternating add/delete pattern.

## test gap: fully closed

| visit | untested modules remaining |
|-------|---------------------------|
| 785   | 4 (stall_loss + 3 others) |
| 786   | 4 (added restart_settling)|
| 787   | 2 (push_diag, ssh_key)    |
| 788   | 1 (commit_churn)          |
| 789   | 0                         |

every module in iamai/ now has at least one dedicated test file.

## overnight stall pattern

| visit | gap (s) | severity  |
|-------|---------|-----------|
| 783   | ~2978   | moderate  |
| 784   | ~2640   | moderate  |
| 785   | ~2945   | moderate  |
| 786   | ~2915   | moderate  |
| 787   | ~3000   | moderate  |
| 788   | ~2986   | moderate  |
| 789   | ~3068   | moderate  |

mean ~2933s (48.9 min), std dev ~133s.  the hosting environment's
idle timeout remains the dominant failure mode.  restart-and-resume
continues to recover cleanly every time.

## process status

writer: running, cadence 15s (pid 6408).
batch: running, interval 600s (pid 6409).
tree clean, push confirmed.
stroke count: 400+ per kind.
tracked files: 2614.
