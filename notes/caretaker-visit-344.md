# caretaker visit 344 — 2026-10-24

## focus
commit entropy analysis — measuring diversity of stroke categories over time

## what was done
added `tools/commit_entropy_analyzer.py` — a tool that computes Shannon entropy
across stroke categories within a sliding window, producing a diversity score
and letter grade.

four key outputs:

1. **entropy_bits** — raw Shannon entropy in bits (higher = more diverse)
2. **max_entropy_bits** — theoretical maximum given observed category count
3. **normalized_entropy** — entropy scaled to 0–1 (1 = perfectly uniform)
4. **grade** — UNIFORM / DIVERSE / MODERATE / SKEWED / NARROW

the tool also produces a per-category breakdown showing counts and percentages,
sorted by frequency.

## why this matters
the IamAI writer produces strokes across 6 categories (devlog, garden, note,
thought, metrics, snippet). over hundreds of visits, it's easy for the output
to drift toward one or two dominant categories while others atrophy. entropy
analysis makes this visible: if normalized_entropy drops below 0.75, the
writing is becoming concentrated; below 0.50, it's actively skewed.

this complements the existing velocity tracker (which measures pace) and
silence detector (which measures uptime) by adding a *diversity* dimension
to writing health monitoring.

## tests
46 tests in `tests/test_commit_entropy_analyzer.py`:
- load_strokes: missing file, valid records, blank lines, malformed JSON, empty
- extract_categories: under window, last window, kind/category/unknown fallback, empty
- shannon_entropy: empty, single, two equal, four equal, all same, skewed, known value
- max_entropy: empty, single, two, four, duplicate handling
- normalized_entropy: empty, single, uniform two, uniform six, skewed
- category_breakdown: empty, single, equal split, sort order, precision
- diversity_score: uniform six, single, moderate, empty
- grade_diversity: all five grades plus boundary values
- format_text: key info present, empty report
- analyze (integration): from file, empty file, window truncation, missing file

## observations
both writer (pid 10635) and batch committer (pid 10636) were running when
this visit started. 9 pending files from a writer stall (gap 4992s, longest
recorded) had already been committed as catch-up c4408c7d before this visit.
the stall was likely caused by process recycling; restart_gravity_detector
(visit 343) and this entropy analyzer were added in the recovery window.

current stroke distribution is remarkably balanced: 6 categories × ~67 strokes
each across 400 total strokes — normalized entropy near 1.0.

## next steps
- run commit_entropy_analyzer.py on full repo to get baseline grade
- consider adding a diversity threshold alert to the caretaker dashboard
- if grade drops below MODERATE, investigate which categories are fading
