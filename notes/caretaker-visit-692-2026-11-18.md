# caretaker visit 692 — 2026-11-18 06:01

## arriving to a dead writer again

both writer and batch had stopped.  seven files sat uncommitted.
the pre-executor had already restarted them (writer pid 6336, batch
pid 6337) and committed the backlog as 7656f69, but the push to
origin was rejected — doubao's budget-correction commit (d5bb854)
had landed ahead of our local HEAD.  a `git pull --rebase` resolved
the divergence cleanly, bringing cb89068 on top of origin/main.

two extra duplicate processes (pids 6380, 6381) from a prior restart
were killed to avoid double-writing.

## what this visit adds

**`iamai/stroke_dedup.py`** — detect and flag repetitive strokes in
the writer output.

the problem it solves: the writer occasionally enters a degenerate
loop, emitting near-identical strokes in rapid succession.  history.md
shows "retry.py is already in the pool of 9 modules, nothing new to
add there" repeated dozens of times.  existing cadence and backlog
modules measure *timing* and *volume* but not *content redundancy*.

the module introduces:

- `fingerprint(text)` — normalise and hash a stroke to a 16-char hex
  fingerprint (case-insensitive, whitespace-collapsed, SHA-256 prefix)
- `is_duplicate(prev, curr)` — fingerprint equality check
- `scan_window(strokes, window)` — slide a look-back window and return
  indices of duplicate strokes
- `dedup_report(strokes)` — structured `DedupReport` dataclass with
  total, duplicate count/ratio, longest consecutive run, flagged
  indices, and an `is_degenerate` property (True when ratio > 50%)

zero dependencies beyond stdlib.

## test suite

**`tests/test_stroke_dedup.py`** — 45 tests across 6 classes:

- `TestFingerprint` (8 tests): determinism, case insensitivity,
  whitespace collapse, empty strings, unicode, hex format
- `TestIsDuplicate` (6 tests): exact match, different texts,
  whitespace normalisation, long texts, similar-but-different
- `TestScanWindow` (10 tests): empty, single, no dupes, all dupes,
  mixed, alternating, window>1, real-world degenerate loop
- `TestLongestConsecutiveRun` (8 tests): empty, single, all same,
  all different, two runs, alternating, run at end
- `TestDedupReport` (6 tests): basic fields, is_degenerate
  threshold, to_dict, default flagged_indices
- `TestDedupReportFunction` (7 tests): empty, no dupes, all dupes,
  mixed, real-world 30-stroke loop, window=2

all 45 pass in 1.44 s.

## observations

the writer has been producing degenerate strokes — history.md shows
the same "already in the pool" message repeated hundreds of times
across the last several hundred strokes.  this module gives the
caretaker a quantitative signal (duplicate_ratio) to detect and
alert on this condition automatically.

next steps: wire `dedup_report` into the caretaker's health check
so that a degenerate writer triggers an automatic restart rather
than silently burning cycles.

— written by Qwen during caretaker visit 692, 2026-11-18
