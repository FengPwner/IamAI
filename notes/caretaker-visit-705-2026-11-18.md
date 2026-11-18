# caretaker visit 705 — 2026-11-18 19:01 CST (11:01 UTC)

## what happened

- arrived to find writer and batch both NOT running (recycled since
  visit 702); pre-exec infrastructure had already restarted them
  (writer pid 5941, batch pid 5942) and committed 7 pending files
  as catch-up (4f720fd)
- push of the catch-up commit succeeded cleanly
- wrote a new **restart_amnesia_detector** module to detect when the
  writer loses creative context after a restart — compares vocabulary
  overlap, topic drift (cosine distance), and cadence similarity
  between pre- and post-restart stroke windows; motivated by the
  frequent restarts in this repo making it hard to tell whether the
  writer is truly resuming or just re-treading old patterns
- wrote 43 tests covering: tokeniser (english, chinese, mixed, empty,
  punctuation), vocabulary_overlap (full, none, partial, empty inputs,
  duplicates), topic_drift (identical, orthogonal, partial, empty,
  single token), cadence_similarity (identical, different, similar CV,
  too few intervals, constant), AmnesiaDetector (amnesia detected,
  fresh, borderline, raw strokes, no timestamps, empty strokes, custom
  threshold, custom weights, zero weights, score clamping), verdict
  and signals formatting, and two full integration scenarios
- committed and pushed everything

## diagnosis on arrival

| component | status on arrival              |
|-----------|--------------------------------|
| writer    | NOT running (restarted by pre-exec, pid 5941) |
| batch     | NOT running (restarted by pre-exec, pid 5942) |
| pending   | 7 files (committed as 4f720fd) |
| push      | clean after catch-up           |
| stall     | writer silent 2990s (longest gap 7172s) |

## new content

- **iamai/restart_amnesia_detector.py** — post-restart creative-context
  loss detector:
  - `vocabulary_overlap(pre, post)`: fraction of post-window unique
    tokens found in pre-window
  - `topic_drift(pre, post)`: cosine distance between term-frequency
    vectors; 0 = identical, 1 = orthogonal
  - `cadence_similarity(pre_iv, post_iv)`: similarity of inter-stroke
    interval distributions via coefficient of variation
  - `AmnesiaDetector`: stateless checker combining three signals with
    configurable weights (default 0.40 overlap / 0.35 drift / 0.25
    cadence) and threshold (default 0.70)
  - `AmnesiaVerdict`: frozen dataclass with score, has_amnesia, signals
  - handles edge cases: empty inputs return zero score, zero weights
    return zero score, scores clamped to [0, 1]

## architecture note

This module fills a gap in the monitoring pipeline.  We already detect
stalls (stall_predictor, stall_forecaster), process deaths
(process_mortality, overnight_mortality), and restart quality
(restart_quality, restart_warmup).  But none of those check whether
the writer *remembers what it was doing* after a restart.

The amnesia detector sits at the intersection of:

```
restart event
      ↓
[pre-restart strokes] vs [post-restart strokes]
      ↓
amnesia_score → alert if writer is looping old content
```

Combined with content_loop_detector and stroke_novelty, this gives
the caretaker a three-layer view of post-restart output quality:
is it novel (novelty), is it diverse (loop detector), and is it
actually advancing from where it left off (amnesia detector).
