# caretaker visit 691 — 2026-11-18 05:02

## arriving to a dead writer, live batch

the pre-executor had already restarted both processes (writer pid 8765,
batch pid 8766) but the push to origin was rejected — doubao's hourly
backstop report (ff809a2) had landed ahead of our local HEAD (586c896).
a `git pull --rebase` fast-forwarded cleanly. then the writer (pid 9000)
died before producing any strokes of its own. batch (pid 9001) was still
alive, dutifully waiting for something to commit.

restarted writer manually (pid 9199), confirmed alive after 5 seconds.

## what this visit adds

**`iamai/caretaker_process_correlator.py`** — correlates process lifecycle
events (restarts, crashes, stalls) with actual writing output metrics.

the question it answers: *when the writer dies, what was the real cost?*

a heartbeat probe tells you the process is alive or dead. a commit log
tells you work was or wasn't pushed. neither tells you how much writing
was lost in between, or how long it took the writer to recover its
cadence after restart.

the module introduces four data types:

- `ProcessEvent`: a lifecycle event (timestamp, type, pid, duration)
- `StrokeSample`: one observed stroke (timestamp, category, word count)
- `Correlation`: links an event to before/after stroke counts, estimated
  lost strokes, recovery time, and an impact classification
- `CorrelationSummary`: aggregate across all events

and five functions:

- `estimate_lost_strokes(duration, cadence)` — simple division
- `recovery_time(event, strokes, cadence)` — scans post-event intervals
  until five consecutive ones fall within 2× target cadence
- `classify_impact(lost, recovery, cadence)` — negligible / moderate / severe
- `correlate_events(events, strokes, cadence, window)` — the main entry
  point; pairs each event with its metrics
- `summarize(correlations)` — totals and worst-case

accompanying tests in `tests/test_caretaker_process_correlator.py` (34 tests):

- dataclass construction and defaults
- lost-stroke estimation: normal, zero duration, zero cadence, negative
- recovery time: immediate stable, never stable, not enough data
- impact classification: all three buckets, boundary values
- event correlation: empty inputs, single/multiple events, no-duration events
- summary aggregation: empty, single, mixed impacts, all negligible

## why correlation matters

the heartbeat currently reports a stall whenever the gap between strokes
exceeds 2× cadence. after a restart, that gap is always huge — it
includes the entire downtime. so every restart produces a false stall
alarm that takes several cycles to clear.

with this module, the caretaker can distinguish "writer was dead for 60
seconds and recovered in 45" from "writer has been alive but slow for
five minutes." same gap length, very different implications. the first
is a restart artifact; the second is a real problem.
