# caretaker visit 767 — 2026-11-21 15:05 CST

## what happened before this visit

writer (qwen) and batch committer were both found stopped on arrival
(pids recycled between container restarts).  seven files of backlog
were committed as catch-up (3c86cb5) and both processes restarted
(writer pid 3882, batch pid 3883).  push confirmed clean.

## what this visit added

a new tool: `stroke_vocabulary_growth.py` with 54 tests.

this tool measures whether the writer's lexicon is expanding,
stable, contracting, or depleted over a rolling window of strokes.

### metrics computed

  - TTR (type-token ratio): unique content words / total content words
  - moving TTR: sliding-window TTR over the stroke stream
  - growth_rate: TTR change between first and second half of window
  - novel_word_ratio: fraction of recent-half words absent from baseline
  - band: expanding / stable / contracting / depleted

### design decisions

  - stop words stripped to focus on content-bearing vocabulary
  - single-char tokens excluded (noise from code fragments)
  - window parameter configurable (default 100 strokes)
  - depleted band overrides growth direction: even positive TTR
    change cannot rescue a stream with < 5% novel words

### why this matters

echo detection (stroke_echo) catches short-term repetition.
yield analysis (stroke_yield_analyzer) flags per-stroke retreads.
vocabulary growth operates at a longer timescale: it detects
the slow plateau where a writer keeps producing varied-looking
text from a shrinking pool of ideas.  combined with momentum
and diversity, it completes the long-range health picture.

## process status

  writer[qwen]: running pid 3882
  batch [qwen]: running pid 3883
  cadence: one stroke every 15s, one commit every 600s
