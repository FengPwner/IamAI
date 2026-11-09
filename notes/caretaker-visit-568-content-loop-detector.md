# visit 568 — content loop detector

**date:** 2026-11-09
**action:** added `iamai/content_loop_detector.py` + 34 tests

---

## what happened

The caretaker arrived to find both writer (pid 5662) and batch committer
(pid 5663) running — pre-exec recovery had already restarted them and
drained the 7-file backlog into commit 5b7d248.  Push completed
cleanly (a8ffef5..5b7d248 main → main).

Despite processes being alive, the metrics flagged a STALL: writer
silent past 2x its cadence, with a gap of 2858 seconds against a 15s
target.  The history.md reveals the root cause: the writer's snippet
strokes are stuck in a 3-module rotation (retry.py → chunk_text.py →
parse_kv.py → repeat), and the writer_state.json shows a rigid
6-stroke cycle (thought → devlog → garden → note → metrics → snippet).

This visit adds a new module to detect and measure exactly this kind
of structural repetition.

## why it matters

The existing `stroke_diversity.py` measures *text similarity* — how
alike the stroke bodies are.  But a writer can produce diverse text
while still being trapped in a structural loop: same kinds in the
same order, same files in the same rotation, same template with
different numbers plugged in.

The writer has been in this state for days.  Every visit since ~560
has found the same pattern but lacked a tool to quantify it.  Now we
can say: "period=6, confidence=1.0, severity=SEVERE" instead of "the
writer seems to be repeating itself."

## design decisions

1. **Categorical labels, not text.**  The detector works on sequences
   of discrete symbols (kind names, file paths, truncated text).  This
   makes it orthogonal to stroke_diversity, which operates on token-
   level Jaccard similarity.

2. **Brute-force period search.**  For each candidate period p from 2
   to len/2, try all starting offsets and score match ratio.  O(n²)
   worst case, but n is at most a few hundred strokes — fast enough.

3. **Frozen dataclass.**  LoopReport is immutable, same pattern as
   OrphanReport in visit 566.

4. **Four severity grades.**  NONE → MILD → MODERATE → SEVERE maps
   to the intuitive escalation from "normal variation" to "the writer
   is a deterministic state machine."

5. **Three label extractors.**  kind (stroke category), file (target
   path), text_prefix (truncated body) — covers the three dimensions
   where loops manifest.

## module API

```python
from iamai.content_loop_detector import detect_loop, extract_kind_labels

labels = extract_kind_labels(strokes)
report = detect_loop(labels)
print(report.has_loop)      # True
print(report.period)        # 6
print(report.confidence)    # 1.0
print(report.severity)      # 'SEVERE'
print(report.cycle)         # ('thought', 'devlog', 'garden', 'note', 'metrics', 'snippet')
```

## test coverage

34 tests across 7 test classes:

- `_score_period` low-level scoring (6 cases)
- `detect_loop` basic detection (8 cases)
- `detect_loop` advanced scenarios (6 cases)
- `LoopReport` dataclass + severity (6 cases)
- Label extractors (4 cases)
- File loading (4 cases)
- Integration with realistic data (2 cases)

## what's next

- Wire into the caretaker's health check: if kind-loop severity is
  SEVERE, suggest a writer restart with a shuffled seed.
- Add historical tracking: plot confidence over time to see when
  loops start and how long they persist.
- Consider a "loop breaker" in the writer loop itself: if the last
  N strokes match a known cycle, force a different kind next tick.
