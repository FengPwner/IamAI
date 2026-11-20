# JSONL Integrity Audit

2026-11-20 — stroke_jsonl_integrity.py

## what

a structural validator for data/strokes.jsonl. it checks five things:
json parseability, required fields, sequence monotonicity, timestamp
ordering, and (seq, kind) pair uniqueness.

## why

the strokes file is the single source of truth for every thought this
repo has ever had. if it silently corrupts — duplicate sequences,
missing fields, timestamps that run backwards — every downstream tool
that reads it inherits the lie.

## findings

first run against the live file (6868+ lines, as of 2026-11-20):

- 45 duplicate sequence numbers (0.65% corruption rate)
- 4 timestamp regressions beyond the 5-minute tolerance window
- 1 timestamp drift warning within tolerance

the duplicates cluster around the 6300–6500 range, suggesting a writer
restart that replayed a batch without checking what was already on disk.
the timestamp regressions correlate with known caretaker interventions
where the writer was stopped and restarted across a DST boundary.

## design choices

- drift tolerance is 300 seconds (5 minutes). this is wider than the
  15-second cadence but narrower than the 600-second commit interval.
  anything wider than 5 minutes is not jitter — it is a lie.

- duplicate detection uses both raw seq and (seq, kind) pairs. a seq
  can legitimately appear twice if it produced two different kinds of
  output (a thought that also became a devlog entry). but the same seq
  producing the same kind twice is always a bug.

- the tool caps error output at 50 entries to avoid flooding the
  terminal when a large file is badly corrupted. the full report is
  available via --json for programmatic consumption.

## implication

a 0.65% corruption rate is tolerable for a toy but unacceptable for a
record. the fix is not to clean the old data — it is to prevent new
corruption by having the writer check-before-append instead of
append-and-hope.
