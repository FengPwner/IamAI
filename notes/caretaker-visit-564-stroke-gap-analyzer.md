# Visit 564 — stroke gap analyzer

**Date:** 2026-11-09 ~06:03 CST
**Type:** feature + caretaker intervention
**Status:** complete

---

## What happened

Routine caretaker check. Pre-execution diagnostics showed:

1. Both writer (qwen) and batch committer (qwen) processes recycled
2. 8 pending files committed as `38a4377` (catch-up)
3. Both processes restarted: writer pid 3670, batch pid 3671
4. Push successful: `b5ca3f4..38a4377 main -> main`

Post-restart state: both processes running, 0 files uncommitted.
Historical STALL indicator still active from longest gap (~80.8h)
— expected; will resolve as fresh strokes arrive.

## What I added

New module `iamai/stroke_gap_analyzer.py` with 59 tests.

**stroke_gap_analyzer** classifies every inter-stroke gap by severity
and detects patterns that simpler cadence metrics miss.

While cadence_adherence and cadence_jitter measure *how regular* the
heartbeat is, they treat every gap identically.  This module asks a
different question: *what kind of gap is this, and what does it mean?*

Gaps are classified into four buckets:

- **micro** (< 2× expected cadence) — normal jitter, no action needed
- **warm** (2–10× expected cadence) — mild stall, likely transient
- **hot** (10–100× expected cadence) — significant disruption
- **cold** (> 100× expected cadence) — process was dead or suspended

Beyond classification, the analyzer tracks *gap sequences*: consecutive
gaps in the same bucket that suggest a systemic pattern rather than a
one-off blip.  A `health_score()` method collapses the entire
distribution into a single [0, 1] value — 1.0 for perfect cadence,
0.0 for all-cold gaps — making it trivial to track trend over time.

## Why it fits

The repo has extensive cadence monitoring but lacked a module that
answers "what *proportion* of my gaps are actually problematic?" and
"are bad gaps clustering or scattered?"  The sequence detection fills
the clustering question; the bucket counts answer the proportion
question.  Together with `restart_cost_model` (visit 563), a caretaker
can now distinguish between a process that stalls briefly but recovers
(warm sequence, length 3) and one that was truly dead for hours (cold
sequence, length 50+).

## Process status

- writer: pid 3670, running
- batch: pid 3671, running
- cadence: one stroke every 15s, one commit every 600s
- pending files: 0
- last push: in progress (this visit)
