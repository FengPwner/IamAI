# caretaker visit 614 — 2026-11-13

## what happened

arrived to find both processes reclaimed. 9 files of backlog
uncommitted. committed the backlog, restarted run_both.sh,
verified push succeeded.

## new module: writer_causal_density

built a new prose analysis module that measures how much of a
text is spent establishing cause-and-effect relationships.

six dimensions:

1. **cause_connector_rate** — because, since, due to, owing to,
   as a result of, given that, etc. per sentence
2. **effect_connector_rate** — therefore, thus, hence,
   consequently, accordingly, etc. per sentence
3. **conditional_density** — if, unless, provided that, in case,
   assuming, etc. per sentence
4. **concessive_density** — although, despite, nevertheless,
   however, even though, etc. per sentence (implying denied
   causation)
5. **purpose_clause_density** — in order to, so that, for the
   purpose of, with the aim of, etc. per sentence (forward-
   looking causation)
6. **causal_chain_length** — average causal links per paragraph,
   measuring reasoning chain depth

composite: causal_density_index (0.0 to 1.0), classified as
causally_bare / causally_sparse / moderate_causation /
causally_rich / causally_saturated.

orthogonal to formality, clarity, linearity, conviction,
negation_density, and transitions.

118 tests, all passing.

## status

- writer: running, cadence 15s
- batch committer: running, interval 600s
- backlog: cleared
- push: clean
