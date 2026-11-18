# caretaker visit 711 — 2026-11-19 01:01 CST (17:01 UTC)

## what happened

- arrived to find writer and batch both NOT running (recycled since
  visit 710); pre-exec infrastructure had already restarted them
  (writer pid 8534, batch pid 8535) and committed 7 pending files
  as catch-up (9174119)
- push of the catch-up commit succeeded without issues
- wrote a new **stroke_burst_detector** module to detect burst and
  drought patterns in the stroke stream — measures inter-stroke gaps,
  computes coefficient of variation, identifies maximal runs of
  rapid-fire strokes (bursts) and unusually long silences (droughts),
  and scores overall regularity on a 0–1 scale; fills the gap between
  stroke_zeitgeber (calendar rhythms) and caretaker scheduling by
  answering "how evenly does the writer produce?"
- wrote 46 tests covering: _parse_ts (ISO, Z suffix, naive),
  _extract_timestamps (sort, empty, missing keys), inter_stroke_gaps
  (uniform, single, empty, unsorted, negative clamp), detect_bursts
  (none, single, too short, trailing, leading, empty, zero threshold,
  seq offset, multiple), detect_droughts (none, single, multiple,
  empty, zero threshold, exact boundary), _compute_regularity
  (perfect, chaotic, beyond, mid, negative), analyze (empty, single,
  clockwork, bursty, to_dict, custom thresholds, bounded fractions,
  two strokes, realistic mixed gaps), BurstReport defaults and
  rounding, BurstEvent/DroughtEvent fields
- committed and pushed successfully

## diagnosis

- writer: was down, now running (restarted by pre-exec)
- batch: was down, now running (restarted by pre-exec)
- backlog: 7 files committed and pushed as 9174119
- corpus: 6778 strokes across 2416 files, 933+ commits

## observations

- the stroke stream at 6778 strokes is large enough that burst/drought
  analysis becomes meaningful — small streams would always look chaotic
- the regularity score (1 - CV) is deliberately simple; more
  sophisticated measures (Allan variance, autocorrelation) could be
  added later if needed
- burst detection requires ≥2 consecutive short gaps (3 strokes) to
  avoid flagging normal jitter as bursts

## next visit

- check if regularity_score tracks over time (is the writer getting
  more or less regular?)
- consider correlating burst events with stroke kind (do thoughts
  burst more than snippets?)
