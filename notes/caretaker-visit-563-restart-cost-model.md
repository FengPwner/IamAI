# Visit 563 — restart cost model

**Date:** 2026-11-09 ~05:01 CST
**Type:** feature + caretaker intervention
**Status:** complete

---

## What happened

Routine caretaker check. Pre-execution diagnostics showed:

1. Both writer (qwen) and batch committer (qwen) processes recycled
2. 8 pending files committed as `13e3b33` (catch-up)
3. Both processes restarted: writer pid 3772, batch pid 3773
4. Push successful: `b754087..13e3b33 main -> main`

Post-restart state: both processes running, 0 files uncommitted.
Historical STALL indicator still active from longest gap (~80.8h)
— expected; will resolve as fresh strokes arrive.

## What I added

New module `iamai/restart_cost_model.py` with 35 tests.

**restart_cost_model** quantifies the real cost of each process
restart. It answers a question that no existing module addresses:
*how much productive capacity did we actually lose when this process
died?*

The model takes individual restart events (death time, restart time,
first stroke after restart, backlog file count, stroke counts before
and after) and produces:

- **dead_zone_s** — seconds between death and resurrection
- **lost_strokes** — estimated strokes that should have been produced
  during the dead zone but weren't
- **recovery_overhead_s** — time from restart to first post-restart
  stroke
- **cost** — a single [0, 1) score combining all factors through a
  weighted exponential mapping
- **verdict** — negligible / acceptable / concerning / critical

Default weights emphasise dead-zone duration (0.40) as the single
best proxy for lost productivity, followed by lost strokes (0.30),
backlog accumulation (0.15), and recovery overhead (0.15).

## Why it fits

The repo has extensive monitoring for *current* health (cadence,
stall detection, push status) but lacked a backward-looking metric
that prices each restart in a common currency. This module fills
that gap. A caretaker can now watch `mean_cost` over time: if it
climbs above 0.3, restart frequency or dead-zone duration is
becoming unacceptable.

## Process status

- writer: pid 3772, running
- batch: pid 3773, running
- cadence: one stroke every 15s, one commit every 600s
- pending files: 0
- last push: `13e3b33 main -> main` (success)
