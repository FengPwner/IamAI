# Revision Depth as Editing Philosophy

**Date:** 2026-11-11
**Module:** `iamai/writer_revision_depth.py`
**Tests:** `tests/test_writer_revision_depth.py` (55 tests)

## The Insight

Every writer has an implicit editing philosophy — a ratio between *creating new things* and *polishing existing things*. This ratio isn't just a productivity metric; it reveals how the writer thinks about quality, completion, and the value of iteration.

## The Spectrum

At one extreme, the **Architect** writes once and moves on. Each stroke creates a new file. The codebase grows fast but accumulates rough edges. Architects are prolific but leave technical debt in their wake.

At the other extreme, the **Sculptor** can't stop revising. The same file gets touched over and over — each pass smooths a corner, tightens a phrase, restructures a module. Sculptors produce work of high local quality but risk perfectionism loops where diminishing returns set in.

The productive middle is the **Gardener** — someone who plants new seeds regularly but also tends the existing beds. Gardeners balance growth with maintenance, producing codebases that are both expansive and well-kept.

## Why This Matters for AI Writers

An autonomous writer agent that only generates new content will produce a sprawling, incoherent body of work. One that only revises will stagnate. The `writer_revision_depth` module gives us a way to *measure* and *monitor* this balance, so a caretaker can nudge the writer back toward the gardener zone when it drifts.

## Metrics Worth Watching

- **revision_ratio** is the simplest signal: what fraction of strokes are edits vs. new content?
- **churn_index** catches a subtle anti-pattern: writing something, then immediately fixing it in the next stroke. High churn means the writer isn't thinking before it writes.
- **avg_revision_rounds** tells you whether files get a single polish pass or iterative deepening.

## Connection to Exploration Balance

This module complements `writer_exploration_balance`. Exploration balance asks "is the writer touching new *areas* or familiar *areas*?" Revision depth asks "is the writer creating *new files* or editing *existing files*?" A writer can explore (touch new areas) while still being a sculptor (deeply revising each area it enters). The two dimensions are orthogonal.

## Design Notes

- Classification threshold for generative vs. revisory: more than half the file touches must be new-file creations. Exactly half counts as revisory — a deliberate choice that biases toward detecting revision.
- Churn window defaults to 5 strokes. Shorter windows miss delayed fix-ups; longer windows conflate unrelated revisits.
- Composite score uses four weighted components: revision_ratio (0.40), churn_index (0.25), avg_revision_rounds normalized (0.20), revision_intensity normalized (0.15).
