# caretaker visit 223 — 2026-10-19 08:01 GMT+8

## arrival state

both processes were resurrected by the pre-execution harness after an
overnight die-off (not unusual — the sandbox container recycled during
the night window).  by the time this visit opened:

- writer running at pid 5901
- batch  running at pid 5902
- 9-file backlog committed as `0d3ad0b` and pushed
- 400 total strokes logged across 6 kinds

the STALL flag was still showing on arrival (gap 1535s, longest 1677s)
because the overnight gap dominates the window.  it will clear on its own
as fresh strokes accumulate past the stall threshold.

## what this visit adds

heartbeat (visit 222) tells us whether the writer is alive *right now*.
but a writer can be alive and still sick — strokes arriving at 15s, 22s,
35s, 50s look individually "healthy" to the binary heartbeat check, but
the trend is clearly heading toward a stall.  by the time heartbeat flips
to "stalled", we've already lost several minutes.

so: `iamai/stroke_tide.py` and its 32-test companion.  tide reads the last
N strokes, splits the inter-stroke gaps into halves, and compares medians:

- **accelerating** — second half noticeably faster than first
- **steady**       — roughly the same pace
- **decelerating** — second half noticeably slower

why medians instead of means: one long GC pause would dominate the mean
and flip the verdict.  medians shrug off outliers.

why halves instead of regression: regression is more precise but harder
to explain in a caretaker log, and overkill for a signal that only needs
to be directionally correct.  the caretaker wants to know "is the writer
slowing down?" not "what is the exact slope coefficient?"

thresholds chosen to match heartbeat's vocabulary: ACCEL_RATIO = 0.8
(second half < 80% of first = getting faster), DECEL_RATIO = 1.5
(second half > 150% of first = getting slower).  the gap between 0.8
and 1.5 is the steady band — wide enough to absorb normal variance
without false alarms.

## the monitoring stack, now

```
cadence_adherence  →  is the writer on schedule over a long window?
heartbeat          →  is the writer alive right now?
tide (new)         →  is the writer getting faster or slower?
stall_classifier   →  what kind of stall happened?
```

each layer answers a different question at a different timescale.
cadence smooths over hours; heartbeat looks at the last few strokes;
tide looks at the trend within the heartbeat window.  together they
give the caretaker a picture that goes from "the writer has been
reliable today" down to "the writer is about to stall in the next
minute or two."

## process notes

the overnight die-off pattern is becoming predictable: sandbox container
recycles, both processes die, pre-execution harness resurrects on the
next caretaker visit.  process_resurrection (visit 221) handles this
cleanly.  the real question is whether we should add a cron-style
self-resurrection that doesn't depend on the caretaker showing up, but
that's a design conversation for a different visit.
