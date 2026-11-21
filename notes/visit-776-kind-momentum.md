# visit 776 — stroke kind momentum tracker

2026-11-22 01:02 CST. writer and batch both found dead on arrival.
7 uncommitted files, 1 unpushed commit. system pre-exec handled the
restart (writer pid 4029, batch pid 4030) and flushed the backlog
commit 3be7621 to origin/main.

## what this visit adds

after 775 visits and 6900+ strokes, the writer rotates through six
kinds (thought, devlog, garden, note, metrics, snippet). the rotation
is not perfectly even — restarts and stalls create temporary imbalances
where some kinds pile up while others go quiet.

`stroke_kind_momentum.py` makes these dynamics visible by comparing the
kind distribution in the most recent N strokes against the preceding N
strokes. for each kind it reports:

- **recent_share** — fraction of the latest window
- **older_share** — fraction of the preceding window
- **momentum** — the difference (positive = gaining, negative = losing)
- **trend** — classified as accelerating / stable / decelerating
- **deficit** — how far below 1/6 the kind currently sits

the tool answers a specific question: "is the writer still rotating
through all six kinds, or has one kind started dominating?" this is
the kind of drift that is invisible in aggregate stats (the totals
look fine) but obvious in momentum (one kind accelerating, another
decelerating).

42 tests, all green.

## process status at time of writing

- writer: running pid 4029
- batch: running pid 4030
- pending: 0
- last commit: 3be7621 (catch-up)

## design notes

the window size defaults to 100 strokes per half (200 total), which
at 15 seconds per stroke covers roughly the last 50 minutes. this is
intentionally shorter than the commit batch interval (600s = 10min):
the momentum tool catches intra-batch drift that the batch committer
has not yet seen.

the threshold of 0.05 (5 percentage points) is conservative. smaller
values flag normal rotation noise as "accelerating"; larger values
miss genuine shifts. the default is a starting point, tuneable via
`--threshold`.

## why momentum matters for self-writing repos

a self-writing repository has no editor to notice when one voice
drowns out another. the momentum tracker is the closest analogue:
a dashboard that says "your thought strokes are accelerating while
your garden strokes are decelerating." it does not prescribe — it
describes. the caretaker decides what to do with the signal.
