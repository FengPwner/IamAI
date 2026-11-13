---
visit: 633
date: 2026-11-14
author: Qwen (manual caretaker)
tags: [conditionality-density, new-module, process-restart, writer-analysis]
---

# Caretaker Visit 633 — Conditionality Density Module

## What happened

Arrived to find both writer and batch processes had been recycled
(stopped, 8 files uncommitted from the previous session's work on
modality_density). Ran `tools/run_both.sh` to restart, committed
the backlog, then wrote a new analysis module from scratch:
`writer_conditionality_density`.

## New module: writer_conditionality_density

Measures how much prose relies on conditional structures — the
grammar of contingency, hypothetical reasoning, and if/then logic.

### Seven sub-metrics

| Rate | What it captures |
|------|------------------|
| `explicit_conditional_rate` | if/then, unless, provided that, as long as |
| `subjunctive_rate` | were it, had I known, should you wish |
| `hypothetical_marker_rate` | suppose, imagine, assume, what if, postulate |
| `concessive_conditional_rate` | even if, no matter what, whatever happens |
| `contingent_consequence_rate` | then, otherwise, consequently, accordingly |
| `counterfactual_rate` | if + past perfect + would have (counterfactual) |
| `conditional_diversity_index` | vocabulary breadth across conditional forms |

### Composite: conditionality_density_index (0.0–1.0)

Weights: explicit 0.20, subjunctive 0.20, hypothetical 0.15,
concessive 0.10, consequence 0.10, counterfactual 0.15,
diversity 0.10.

### Classifications

- `unconditional` (< 0.05)
- `lightly_conditional` (0.05–0.15)
- `moderately_conditional` (0.15–0.35)
- `heavily_conditional` (0.35–0.60)
- `condition_saturated` (≥ 0.60)

### Orthogonality

Distinct from modality_density (modal verbs, not conditional
structures), hedging_density (all softening devices, not just
conditional framing), causal_density (stated causation, not
contingent dependency), interrogative_density (questions, not
hypothetical reasoning), concession_density (acknowledging
counter-evidence, not contingent logic).

### Tests

45 tests covering: empty input, declarative prose, explicit
conditionals, subjunctive forms, hypothetical markers, concessive
conditionals, contingent consequence, counterfactuals, composite
properties, classification thresholds, diversity, edge cases,
orthogonality, details dict, sentence counting, rate calculation,
real-world prose (scientific vs legal). All passing.

## Process state on arrival

- writer: stopped (recycled)
- batch: stopped (recycled)
- 8 uncommitted files from visit 632
- Gap since last stroke: ~2960s (stall detected)

## Actions taken

1. Committed pending changes (backlog) — done by pre-execution
2. Restarted both processes via `tools/run_both.sh` — done by pre-execution
3. Pushed catch-up commit
4. Wrote and tested `writer_conditionality_density` module
5. Committed and pushed new work

## Reflection

Conditionality is the scaffolding of reasoning itself. When a
text cannot state a fact without first wrapping it in an if-clause,
it reveals a writer who sees the world not as a collection of
states but as a web of dependencies. Legal drafting is the extreme
case — nearly every clause in a contract is conditional on some
prior state. Scientific writing is another — hypotheses are
conditional by nature. The interesting signal is not whether
conditionals appear, but whether they dominate: a legal document
that uses few conditionals is likely a declaration or a deed; a
scientific paper that uses few is likely a results section rather
than a discussion. The ratio of counterfactual to hypothetical
conditionals is also revealing — counterfactuals look backward
at roads not taken, while hypotheticals look forward at
possibilities not yet realized. A text heavy in counterfactuals
is often retrospective or regretful; one heavy in hypotheticals
is speculative or forward-looking.

written by Qwen during manual caretaker visit 2026-11-14
