# Stroke Resonance — Forward Idea Propagation

**Created:** 2026-11-20
**Module:** `iamai/stroke_resonance.py`
**Tests:** `tests/test_stroke_resonance.py` (59 tests)

## Motivation

Existing trackers measure different facets of the stroke stream:

| Module | What it captures |
|---|---|
| `stroke_persistence` | How long concepts survive across the stream |
| `stroke_diversity` | How varied the stroke-kind mix is |
| `stroke_transition_tracker` | How consecutive strokes connect |

None of these answer a deceptively simple question: **does a given
stroke's content propagate into the strokes that follow?**

## Core Idea

Resonance is the *forward projection* of a single stroke's ideas.
For each stroke, we extract its concept tokens, then scan forward
within a configurable window to measure how much conceptual overlap
persists at each offset.

### Per-stroke metrics

- **forward_echo** — how many subsequent strokes share ≥ 1 concept
- **resonance_score** — mean overlap ratio across the window [0, 1]
- **peak_offset** — where overlap is strongest (immediate echo vs delayed)
- **decay_curve** — overlap at each forward offset
- **half_life** — first offset where overlap drops below 0.5

### Stream-level patterns

Four resonance patterns classify the overall stream:

- **resonant** — most strokes propagate ideas forward steadily
- **cascading** — ideas gain momentum; half-lives increase over time
- **fragmented** — most strokes are dead ends; ideas don't connect
- **pulsing** — alternating high/low resonance; bursty engagement

## Why It Matters

A writer producing resonant strokes is building — each idea seeds the
next. A fragmented stream may indicate surface-level exploration without
deep engagement. Tracking resonance over time reveals whether the
writing practice is becoming more or less coherent.

## Design Decisions

1. **Reuses the same concept extraction as `stroke_persistence`** —
   consistent vocabulary across the tracker family.
2. **Window-based, not global** — measures local propagation, not
   stream-wide persistence (that's what `stroke_persistence` does).
3. **`resonance_delta`** enables temporal comparison — split the stream
   in two halves and see if coherence is improving or declining.
4. **Zero dependencies** — stdlib only, consistent with the rest of
   the iamai tracker family.
