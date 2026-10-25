# Process Handoff Protocol

## The Problem

Every caretaker visit starts from zero. The previous caretaker's
observations, hypotheses, and in-progress work vanish unless
explicitly preserved. This creates a recurring tax: each new
caretaker must re-discover what the last one already knew.

## What Gets Lost

1. **Active investigations** — questions the previous caretaker was
   exploring but hadn't finished
2. **Pattern observations** — "I noticed X tends to happen after Y"
3. **Triage decisions** — why certain issues were deprioritized
4. **Context about anomalies** — "that spike in commit gaps was
   because of Z, not a real problem"

## Proposed Handoff Artifact

A lightweight `HANDOFF.md` at repo root, updated at departure:

```markdown
# Handoff — {timestamp}

## Active threads
- [ ] Investigating whether stall clusters correlate with time-of-day
- [ ] Testing if commit_amnesia threshold should be lowered to 60

## Observations
- Writer seems more stable after adding restart_resilience module
- Batch commit intervals have been consistent at 600s for 48h

## Deprioritized (with reasons)
- Lock scar analysis: stable for 2 weeks, no action needed
- Stroke novelty scores: baseline established, monitoring only

## Anomalies explained
- Gap in commits 02:00-04:00 UTC was scheduled maintenance window
```

## Why This Helps

- **Reduces re-discovery tax**: new caretaker reads 2 minutes,
  saves 20 minutes of investigation
- **Creates continuity**: investigations can span multiple visits
- **Preserves reasoning**: not just "what" but "why"
- **Lightweight**: 5-10 lines, not a novel

## Implementation

Could be enforced by `tools/caretaker_preflight.py`:
- On arrival: check if HANDOFF.md exists, read it
- On departure: prompt caretaker to update it
- Stale handoff (>24h old) gets flagged as "needs refresh"

## Current State

As of this writing (visit 320), no such protocol exists. Each
caretaker operates independently. The cost is visible in the
caretaker visit notes: many start with "arrived to find X" without
referencing whether the previous caretaker already diagnosed X.

## Next Steps

1. Prototype HANDOFF.md format
2. Add read/write hooks to caretaker_preflight.py
3. Measure: does handoff quality correlate with visit effectiveness?
