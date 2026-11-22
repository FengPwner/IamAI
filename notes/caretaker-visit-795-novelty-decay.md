# visit 795 — novelty decay detector

2026-11-22 18:03 CST. human-requested caretaker check.

## context

writer (pid 6440) and batch (pid 6441) were found dead on arrival
during the pre-execution sweep. both had been recycled by the hosting
environment's idle timeout. backlog of 7 files flushed as 5600d10
(rebased to 25cbff8 after pull), processes restarted. push initially
rejected (remote had stroke 314 ahead), resolved via rebase.

## what this visit adds

a new module — `tools/stroke_novelty_decay.py` — that measures how
fast the writer's vocabulary shrinks over time.

### why it matters

the repo already tracks stalls (is the writer running?) and content
loops (is the writer repeating the same stroke?). but there was no
tool answering a subtler question: **is the writer still saying
something new, or just reshuffling old words?**

novelty = fraction of tokens in a window that don't appear in any
earlier stroke. a declining novelty curve is a leading indicator of
content-mode collapse — the writer types, but has nothing to say.

### stroke_novelty_decay.py

core types and functions:

- `NoveltyPoint` — frozen dataclass for one window measurement:
  index, ratio, novel_count, total_count. has a `band()` method.

- `NoveltyDecay` — sliding-window analyzer. takes ordered stroke
  texts, window size (default 50), step (default 10). exposes:
  - `points()` — all computed NoveltyPoints
  - `latest()` — most recent point
  - `trend()` — improving / steady / declining / collapsed
  - `summary()` — complete dict for JSON/CLI output

- `novelty_report()` — one-line human-readable summary.

novelty bands:

| band    | range     | meaning                        |
|---------|-----------|--------------------------------|
| fresh   | >= 0.40   | lots of new vocabulary         |
| stable  | 0.25-0.40 | normal repetition + novelty    |
| stale   | 0.10-0.25 | vocabulary shrinking           |
| decayed | 0.03-0.10 | almost no new words            |
| frozen  | < 0.03    | near-verbatim repetition       |

trend classification skips the first data point (always 1.0 because
no prior vocabulary exists — an artefact, not a signal).

### test_stroke_novelty_decay.py (42 tests)

test areas:

1. **_tokenize** — basic splitting, punctuation, CJK chars, empty,
   numbers.

2. **NoveltyPoint** — all fields, all five bands, boundary values
   (0.40, 0.25, 0.10, 0.03), frozen immutability.

3. **NoveltyDecay points** — empty input, single stroke, basic
   window count, two windows, zero novelty when no new words,
   positive novelty when new words, latest(), latest None on empty,
   window equals data length, step=1.

4. **Trend** — insufficient data, steady (consistent novelty),
   declining (unique→repetitive), improving (repetitive→unique).

5. **Summary** — key completeness, empty input, value consistency.

6. **novelty_report** — basic format, insufficient data, single
   stroke, percentage format.

7. **Edge cases** — identical strokes, completely unique strokes,
   mixed content, window larger than data, zero total tokens.

## first measurement

ran the detector against the full strokes.jsonl (6942 strokes):

```
novelty: 6.0% (decayed), trend=steady, 690 windows
```

the writer's vocabulary is firmly in the "decayed" band — only 6%
of tokens in each window are genuinely novel. the trend is "steady"
rather than "collapsed", which means this is the writer's stable
operating mode, not a recent degradation. the high repetition is
structural: the writer draws from a fixed pool of aphorisms and
measurements, which is by design for this project.

## process status

writer: running, cadence 15s (pid 6440).
batch: running, interval 600s (pid 6441).
tree clean after commit, push confirmed.
tracked files: 2628 (added stroke_novelty_decay.py, test, this note).
