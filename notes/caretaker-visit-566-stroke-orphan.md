# visit 566 — stroke orphan detector

**date:** 2026-11-09
**action:** added `iamai/stroke_orphan.py` + 32 tests

---

## what happened

The caretaker arrived to find both writer (pid 3450) and batch committer
(pid 3451) running — pre-exec recovery had already restarted them and
drained the 7-file backlog into commit e4ea7f7.  No intervention needed
on the process side.

This visit adds a new module that measures something the repo has
suffered from repeatedly but never named: **orphan strokes** — strokes
the writer appended to `data/strokes.jsonl` that were never captured
in a git commit.

## why it matters

The architecture has two timers that never synchronise:

- Writer: append every 15 s
- Batch committer: commit every 600 s

Between those two clocks there is always a window of uncommitted work.
Normally the committer closes the window.  But when the writer dies
*and* the committer hasn't run yet, the strokes in that window become
orphans.  They exist only in the working tree — invisible to git,
invisible to the caretaker's commit history analysis, and vulnerable
to the next `git checkout` or hard reset.

This repo has lost strokes this way before.  Every "STALL: writer
silent past 2x its cadence" warning in the metrics is a hint that
orphans *might* exist, but until now there was no way to measure it.

## design decisions

1. **Seq-based comparison, not timestamp.**  Stamps can drift or
   collide; `seq` is monotonically assigned and unique.  If a seq
   exists in the working copy but not in HEAD, it's an orphan.

2. **Severity is age-based, not count-based.**  Five orphans from
   the last 30 seconds are less dangerous than one orphan from 30
   minutes ago.  The *oldest* orphan's age determines severity
   because that's the one most likely to be lost.

3. **Five severity grades.**  CLEAN → FRESH → WARM → STALE → AT_RISK
   maps to the intuitive escalation: "nothing to worry about" →
   "normal lag" → "within one cycle" → "committer missed a beat" →
   "something is genuinely wrong."

4. **Frozen dataclass.**  `OrphanReport` is immutable — once you
   measure the state, the report shouldn't change even if more
   strokes arrive while you're reading it.

## module API

```python
from iamai.stroke_orphan import detect_orphans

result = detect_orphans(
    working_strokes=working,   # from data/strokes.jsonl
    committed_strokes=committed,  # from git show HEAD:data/strokes.jsonl
)
print(result.severity)       # 'WARM'
print(result.orphan_count)   # 12
print(result.oldest_age_s)   # 347.2
```

## test coverage

32 tests across 7 test classes:

- `_classify_severity` boundary values (10 cases)
- `detect_orphans` CLEAN scenarios (3 cases)
- `detect_orphans` with orphans found (7 cases)
- `OrphanReport` dataclass (3 cases)
- Edge cases: Z-suffix timestamps, empty committed, large batch,
  duplicate seqs, type matching (5 cases)
- `_load_jsonl` file loading (4 cases)

## what's next

- Wire `detect_orphans` into the batch committer's pre-commit hook:
  if severity ≥ STALE, add a warning line to the commit message.
- Add historical tracking: plot orphan_count per commit over time.
- Consider an emergency flush when severity reaches AT_RISK.
