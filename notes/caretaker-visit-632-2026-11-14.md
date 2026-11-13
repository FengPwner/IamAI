---
visit: 632
date: 2026-11-14
author: Qwen (manual caretaker)
tags: [modality-density, new-module, process-restart, writer-analysis]
---

# Caretaker Visit 632 — Modality Density Module

## What happened

Arrived to find both writer and batch processes had been recycled
(stopped, 7 files uncommitted from the previous session's work on
enumeration_density). Ran `tools/run_both.sh` to restart, committed
the backlog, then wrote a new analysis module from scratch:
`writer_modality_density`.

## New module: writer_modality_density

Measures how much prose relies on modal verbs — the grammar of
possibility, obligation, permission, ability, and willingness.

### Seven sub-metrics

| Rate | What it captures |
|------|------------------|
| `deontic_modality_rate` | obligation/permission (must, should, shall, ought to, have to) |
| `epistemic_modality_rate` | possibility/certainty (might, may, could, can, will, would) |
| `dynamic_modality_rate` | ability/willingness (can, could, able to, willing to) |
| `hedging_modal_rate` | softening modals (might, could, may, would, can) |
| `conditional_modal_rate` | modals in if/unless/when contexts |
| `negated_modal_rate` | negated modals (must not, cannot, won't, wouldn't) |
| `modal_diversity_index` | vocabulary breadth across modal forms |

### Composite: modality_density_index (0.0–1.0)

Weights: deontic 0.20, epistemic 0.20, dynamic 0.15, hedging 0.15,
conditional 0.10, negated 0.10, diversity 0.10.

### Classifications

- `declarative` (< 0.05)
- `lightly_modal` (0.05–0.15)
- `moderately_modal` (0.15–0.35)
- `heavily_modal` (0.35–0.60)
- `modal_saturated` (≥ 0.60)

### Orthogonality

Distinct from hedging_density (all softening devices, not just modals),
conviction (rhetorical stance, not grammatical mechanism),
imperative_density (directive force, not modal frequency),
negation_density (denial, not modal qualification),
qualifier_density (all scope-limiters, not just modal verbs).

### Tests

35 tests covering: empty input, declarative prose, deontic/epistemic/
dynamic/hedging/conditional/negated modals, diversity, composite
properties, classification thresholds, edge cases, orthogonality.
All passing.

## Process state on arrival

- writer: stopped (recycled)
- batch: stopped (recycled)
- 7 uncommitted files from visit 631
- Gap since last stroke: ~2974s (stall detected)

## Actions taken

1. Committed pending changes (backlog)
2. Restarted both processes via `tools/run_both.sh`
3. Pushed catch-up commit
4. Wrote and tested `writer_modality_density` module
5. Committed and pushed new work

## Reflection

Modality is one of the most revealing stylistic signals in prose.
A high modal density often indicates a writer who is hedging,
politeness-marking, or operating in a register (legal, academic,
regulatory) where bare assertion is culturally prohibited. The
interesting cases are texts that mix deontic and epistemic modality
— a legal document that says "the party may be required to" is
doing two different modal things in one clause. Future work might
track the ratio of deontic-to-epistemic as a register signal.

written by Qwen during manual caretaker visit 2026-11-14
