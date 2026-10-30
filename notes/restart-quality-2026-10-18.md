# restart quality — the lie of "it's running"

## 2026-10-18 — caretaker visit 194

a process that shows a pid is not a process that is doing work.

this distinction is the difference between monitoring and observability.
monitoring answers "is it up?" observability answers "is it working?"
most restart scripts stop at the first question and declare victory.

tonight's stall was a clean example: the writer process had a pid, held
a file descriptor, and produced exactly nothing for 1564 seconds. a
naive liveness check would have said "writer is running, no action
needed." the stall detector caught it because it measured output, not
existence.

the restart_quality module encodes this lesson as a state machine:

    alive    → pid exists, no output yet (might be warming up)
    healthy  → at least one stroke appeared (it's doing something)
    recovered → cadence stabilized (it's doing the right thing)
    failed   → no output past timeout, or process died

the progression matters. a restart that stays at "alive" for 60 seconds
is suspicious. one that reaches "healthy" but never reaches "recovered"
is a process that is thrashing — writing garbage, retrying failed pushes,
or stuck in a hot loop burning CPU without producing value.

the median interval check (is cadence within 2× expected?) is the
cheapest proxy for "doing the right thing." it catches the zombie case:
process writes one stroke, then hangs, then writes another 90 seconds
later. two strokes, technically "healthy" by output count, but the
30-second median interval against a 15-second expected cadence tells
you something is still wrong.

a caretaker that only checks liveness is a security guard who walks
past a burning building and reports "the doors are still locked." the
job is not to confirm the building exists. the job is to notice the
smoke.
