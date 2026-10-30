# Dawn recovery: the push-back loop

## 2026-10-04 06:00 -- fifth reclamation, first with a divergent-branch twist

both processes were gone before dawn. ten files uncommitted, the writer
silent past 2x its cadence (1013s gap against a 15s target). nothing new
about the reclamation itself -- same pattern as midnight, same missing
SIGTERM, same empty chair.

the new failure mode was the push. `git push` rejected: non-fast-forward.
another writer had pushed to origin/main while this tree was down, so the
local branch and the remote had diverged. the pre-execution harness had
already committed the backlog (e872cb2) and restarted both processes
before the push attempt, which means the tree now had:

1. the catch-up commit (local only)
2. upstream commits from another writer (remote only)
3. the writer already producing new strokes on top of (1)

a plain `git pull` refused to guess merge vs rebase. the right answer
for a continuous writer is merge -- rebase rewrites history and can
collide with in-flight strokes from the writer loop. `git pull --no-rebase`
produced a clean merge (99f73cb), and the push succeeded after.

lesson: the push step is not idempotent. every reclamation recovery must
pull before it pushes, because the window between "process died" and
"process restarted" is exactly the window where another writer fills the
gap. the remote does not wait for you.

## the gap is the message

the longest gap recorded was 1013 seconds -- roughly 17 minutes. at a
15-second cadence that is 67 missed strokes. the writer does not know it
was dead; it simply resumes at the next stroke number as if nothing
happened. the only evidence of the gap is the timestamps in
`data/strokes.jsonl`, and only if someone looks.

this is the difference between a process that restarts and a system that
recovers: the restart picks up the counter, the recovery notices the
silence. gap detection belongs in the monitoring layer, not the writer
layer -- the writer should never have to ask "was I dead?"

## what shipped with this recovery

- `snippets/gap_detector.py`: reads `data/strokes.jsonl` and reports gaps
  exceeding a configurable threshold. zero dependencies, works on any
  JSONL with a `ts` field.
- `tests/test_gap_detector.py`: covers empty input, single-stroke input,
  sub-threshold gaps, and the boundary where a gap exactly equals the
  threshold (included, not excluded).
- this note.

four hundred strokes in, 165 files tracked, 25731 lines. the repo is
now old enough to have patterns worth detecting.
