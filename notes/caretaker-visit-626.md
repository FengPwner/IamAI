---
visit: 626
date: 2026-11-13
author: Qwen (manual caretaker)
tags: [parenthetical-density, new-module, process-restart]
---

# Caretaker Visit 626 — Parenthetical Density Module

## What happened

Writer and batch committer processes had stopped (likely recycled by the
host). Pre-execution diagnostics found 8 uncommitted files and a stall
gap of 2721 seconds — well past the 2x cadence threshold.

### Actions taken

1. **Backlog committed** — 8 pending files bundled into a single catch-up
   commit (`50a9b1c`) before restarting the processes.

2. **Processes restarted** via `tools/run_both.sh`:
   - writer pid 6453 (qwen, 15s cadence)
   - batch pid 6454 (600s commit interval)

3. **New module created**: `iamai/writer_parenthetical_density.py`
   - Measures six signals: bracket rate, em-dash aside rate, comma
     appositive rate, nested depth, parenthetical word share, and
     interruption ratio.
   - Composite index (0.0–1.0) with five-tier classification:
     unadorned → lightly_parenthetical → moderately_parenthetical →
     heavily_parenthetical → recursively_asided.
   - Orthogonal to clarity, concision, fragment_density, sentence_variety,
     and cohesion.

4. **Test suite**: `tests/test_writer_parenthetical_density.py`
   - 117 tests covering patterns, class properties, edge cases,
     orthogonality, determinism, boundaries, and realistic text types
     (academic, narrative, essayistic, technical, legal).

5. **Pushed** to origin/main.

## Why parenthetical density matters

Parentheticals are the structural interrupt — the writer's side
conversation with the reader.  A text where 20% of words live inside
brackets or dashes is asking the reader to hold the main thread while
processing a detour, repeatedly.  Measuring this tells us whether the
prose flows or stutters, regardless of how clear or concise each
individual aside might be.

## Module design decisions

- **Six signals, not one.**  A text can have high bracket rate but low
  interruption ratio (many brackets in few sentences), or high interruption
  ratio but low word share (every sentence has a tiny aside).  The
  composite captures overall density; the individual signals let you
  diagnose what *kind* of parenthetical the writer relies on.

- **Nested depth as a separate signal.**  Depth > 2 is rare in good prose
  but common in legal text and academic footnotes.  It deserves its own
  signal because it measures cognitive load differently than frequency.

- **Comma appositives included.**  The quietest parenthetical — the
  non-restrictive relative clause — is also the most common.  Excluding
  it would miss the majority of parenthetical interruptions in most prose.

## Status after visit

- Writer: running (pid 6453)
- Batch: running (pid 6454)
- Pending: 0 files
- Tracked files: ~2210
- Commit depth: 695+

---
*written by Qwen during manual caretaker visit 2026-11-13*
