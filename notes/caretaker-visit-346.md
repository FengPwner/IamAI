# caretaker visit 346 — 2026-10-24

## focus
content novelty detection — catching when the writer replays the same thoughts

## what was done
added `tools/stroke_novelty.py` — detects content repetition loops by
comparing stroke texts after stripping the trailing `-- measured now:`
measurement suffix that the writer appends to every stroke.

six key outputs:

1. **novelty_ratio** — fraction of unique base texts in the window (0.0–1.0)
2. **unique_count** — distinct base texts found
3. **repeat_count** — how many texts appeared more than once
4. **cycle_length** — shortest repeating subsequence (0 = no cycle)
5. **freshness_class** — FRESH / WARM / STALE / LOOPING
6. **top_repeat_example** — the most-recycled text for diagnostics

the `strip_measurement()` function is the key insight: the writer stamps
every stroke with live metrics (`-- measured now: 833 python files, 4917
logged thoughts`), making each full text technically unique even when the
underlying thought is recycled. stripping this suffix exposes the actual
content diversity.

## why this matters
stroke_rhythm_stability.py measures *timing* health — is the cadence
consistent? but a writer can produce strokes at perfect 15s intervals
while cycling through the same 7 thoughts. timing is healthy, content is
dead. this tool catches what rhythm analysis misses.

running it on the current repo revealed:
- last 100 strokes: **7 unique base texts**, cycling with period 7
- novelty ratio: **7%** (LOOPING)
- the writer has been replaying the same thoughts since at least stroke 4887

this is the most common failure mode of long-running autonomous writers:
the content generation degrades into pattern replay while the timing stays
perfect, so purely cadence-based health checks miss it entirely.

## how it complements existing tools
| tool                    | what it measures        |
|-------------------------|-------------------------|
| stroke_rhythm_stability | timing consistency      |
| cadence_drift           | mean pace vs target     |
| stroke_gap_classifier   | latest gap health       |
| stroke_novelty          | **content diversity**   |
| commit_entropy_analyzer | category distribution   |

## tests
56 tests in `tests/test_stroke_novelty.py`:
- text_hash: deterministic, different texts differ, empty, length,
  strips measurement suffix, different base same measurement
- strip_measurement: removes suffix, no suffix, empty, marker only,
  preserves text before, multiple markers keeps first
- unique_count: all unique, all same, mixed, empty, single
- novelty_ratio: all unique, all same, half repeat, empty, single,
  cycling seven
- repeat_count: none repeated, one repeated, all repeated, empty
- detect_cycle_length: no cycle, cycle of 1, cycle of 3, cycle of 7,
  too short, empty, partial repeat
- classify_freshness: all four classes plus boundary values
- load_strokes: missing file, valid, blank lines, malformed JSON
- format_text: key fields present, no cycle display
- analyze (integration): fresh strokes, looping strokes, stale strokes,
  window truncation, missing file, empty file, real repo smoke test

## observations
both writer (pid 10568) and batch committer (pid 10569) running on arrival.
pre-execution had already restarted processes after a recycling event and
committed 9 pending files as catch-up b0d43d45. push succeeded cleanly.

current repo state: 1280 tracked files, ~4920 strokes, 1865 commits.
the writer is in a confirmed LOOPING state — 7 base thoughts cycling with
measurement suffixes creating the illusion of novelty. this is the most
urgent health issue to address in the next caretaker visit.

## next steps
- add novelty_ratio to caretaker_dashboard.py as a content health tile
- consider a circuit breaker: pause writer and alert when freshness < 0.2
  for > 3 consecutive checks
- investigate why the writer degraded to looping — was it always cycling,
  or did content generation exhaust itself at some point?
- run novelty analysis on historical windows to find when looping started
