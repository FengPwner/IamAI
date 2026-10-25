# caretaker visit 206 — 2026-10-18 15:01

## what happened

caretaker checked the IamAI repo at 15:01 CST on request from the
user.

- pre-execution diagnostics showed both writer and batch had been
  recycled by the sandbox — pids gone, 9 files uncommitted, heartbeat
  flagged STALL (gap 1499s, longest 1644s)
- the pre-execution pipeline already committed the 9 pending files as
  `34ea306` (catch-up) and restarted both processes
- writer pid 25269, batch pid 25270 — both healthy on arrival
- push to `main` confirmed: `53dffa4..34ea306`

## diagnosis

same root cause as visits 204 and 205: sandbox process recycling.
no code bug.  the writer produced strokes normally until the sandbox
killed it.  this is the fourth stall-restart cycle today (visits 204
at 13:00, 205 at 14:01, and this visit at 15:01).

the heartbeat flagged "STALL: writer silent past 2x its cadence"
because the gap exceeded 30 s (2× 15 s cadence).  this is expected
behaviour during a sandbox recycle — the gap is always > 20 minutes
because the sandbox kills the process and the next caretaker visit
is what triggers recovery.

## new contribution

added `iamai/cadence_jitter.py` — measures timing irregularity in
stroke sequences.  existing cadence modules (cadence_adherence,
cadence_drift) answer "how close to target?" and "is it shifting?".
this module answers "how irregular is the spacing?"

the module computes:

  - **mean gap** — average seconds between consecutive strokes
  - **std gap** — population standard deviation of gaps
  - **CV** — coefficient of variation (std / mean)
  - **quality label** — steady / regular / uneven / erratic

quality thresholds:

  - **steady**  — CV < 0.10 (gaps vary less than 10% of mean)
  - **regular** — CV 0.10–0.25 (normal operating variance)
  - **uneven**  — CV 0.25–0.50 (noticeable irregularity)
  - **erratic** — CV > 0.50 (highly unpredictable timing)

two entry points: `jitter_report(timestamps)` for raw timestamp
sequences and `jitter_report_from_gaps(gaps)` for pre-computed
intervals.  plus `jitter_summary()` for a one-line human-readable
string.

added 36 tests in `tests/test_cadence_jitter.py` covering:
- classify_jitter at all four threshold boundaries
- extract_gaps from datetime objects, floats, and integers
- jitter_report_from_gaps: perfect steady, alternating uneven,
  truly erratic, single gap, empty gaps, max/min deviation
- jitter_report: datetime and numeric timestamp inputs
- jitter_summary: format validation for steady and erratic data

zero dependencies.  stdlib only.

## status

processes healthy (writer pid 25269, batch pid 25270).
cadence running at 15s per stroke, 600s per commit.
no pending files after the catch-up commit.
