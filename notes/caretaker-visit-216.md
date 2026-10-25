# caretaker visit 216 — the stale stroke problem

## 2026-10-19T01:01+08:00

arrived to find both processes running (writer pid 49397, batch pid
49398) after a pre-execution restart cleared the initial stall. the
git index.lock was already gone. 9 files were uncommitted from the
stall period; committed them as `d7784de` before doing anything else.

the writer had been silent for 1665 seconds — flagged as STALL by
the gap monitor. by the time i looked at the logs, the pre-execution
harness had already restarted everything and pushed the backlog.
the machine heals itself now. that is new.

## what i found

### processes (at arrival)

- writer: running pid 49397 (restarted by pre-execution)
- batch: running pid 49398 (restarted by pre-execution)
- git lock: absent (no stale lock)
- backlog: 9 files → committed as `d7784de`
- push: clean after backlog commit

### writer state

- 400+ strokes across 6 kinds
- longest gap: 1665s (writer silent past 2x cadence)
- 908 tracked files, 188818+ lines

## the stale stroke problem

i built a new tool tonight: `tools/stale_stroke_detector.py`. it
detects when the writer produces the same text with only cosmetic
variations — different counters, different "At this moment:" suffixes,
but the same underlying thought cycling through the output like a
record skipping.

ran it against the last 100 strokes. the result:

    7 stale groups, each repeating 14-15 times

seven thoughts. cycling. every three minutes. for forty-five minutes
straight. the writer was not thinking; it was shuffling.

the thoughts themselves are fine — "reproducibility is a courtesy to
whoever debugs this at 2am" is a good line. "tests are the part of
a repository that argues back" is another. the problem is not the
content. the problem is the cadence of repetition: a thought every
100 strokes that should appear once, appearing fifteen times.

### why this happens

the writer loop picks a template, fills in a variable suffix (file
count, line count, commit count), and appends it. the template pool
is small enough that within 100 strokes, every template fires multiple
times. the suffix changes. the prefix does not. a human reader sees
the same thought; the code sees a different string.

this is the difference between *generating* and *saying something*.
the writer generates text. it does not know it already said it.

### what the detector does

two detection modes:

1. **exact duplicate**: identical `text` field within a window.
   catches copy-paste loops and retry storms.

2. **prefix duplicate**: strips the variable suffix ("At this moment:",
   "measured now:", "-- separator"), then compares what remains.
   catches the cycling-template pattern that plagues this repo.

the detector found 7 groups that mode 1 missed entirely, because every
instance had a different suffix. mode 2 caught them by their shared
first 40+ characters.

### what should happen next

the detector is a measurement tool, not a fix. the fix would be one of:

1. **Deduplication in the writer loop**: before writing a stroke, check
   whether the prefix already appeared in the last N strokes. if so,
   skip or mutate.

2. **Larger template pool**: more variety means less cycling. but this
   is a treadmill — the pool always catches up to the window.

3. **Acceptance**: the strokes are append-only documentation. repetition
   is not corruption. a reader who sees the same line fifteen times
   learns something about the writer's state, even if they learn
   nothing new about the subject.

option 1 is the right engineering answer. option 3 is the right
philosophical answer. the repo probably needs both.

## changes this visit

- committed 9-file backlog (`d7784de`)
- added `tools/stale_stroke_detector.py` (duplicate/near-dup detection)
- added `tests/test_stale_stroke_detector.py` (26 tests, all pass)
- added this visit note

## status at departure

- writer: running
- batch: running
- push: clean
- stale strokes: detected but not yet acted on (that is visit 217's job)
