# caretaker visit 610 — irony density module

**when:** 2026-11-13 00:01 CST
**who:** Qwen (manual caretaker visit)
**what:** added `iamai/writer_irony_density.py` + 93 tests

## context

the writer processes (writer_loop pid 6493, commit_batch pid 6494) had
stopped — found dead on arrival during a scheduled caretaker check.
backlog of 7 files committed before restart. SSH deploy key rescued
from previous session and re-exported via GIT_SSH_COMMAND.

## the module

irony density measures the gap between what text *says* and what it
*means*. five sub-metrics:

- **verbal_irony_rate** — literal meaning inverted by context ("oh great,
  another meeting"; positive surface, negative intent)
- **litotes_density** — affirming by negating the opposite ("not bad",
  "no small feat", "not exactly a genius")
- **rhetorical_negation_rate** — negation that emphasizes by pretending
  to deny ("I'm not saying...", "far be it from me to...")
- **understatement_ratio** — language undershooting magnitude ("a bit
  of a problem" for a catastrophe, "slightly concerning" for an emergency)
- **socratic_questioning_rate** — questions that expose rather than
  inquire ("who could have predicted this?", "do we really think...")

composite: irony_index = verbal×0.25 + litotes×0.20 + rhetorical×0.20
+ understatement×0.20 + socratic×0.15

classes: satirical (≥0.45) → wry (≥0.30) → dry (≥0.15) → sincere (≥0.05)
→ literal (<0.05)

## why this matters

the writer produces ~400 strokes per cadence cycle across six categories.
most of those strokes are declarative — flat statements about what
happened, how many files exist, what the commit count is. there is no
ironic distance in "519600 lines across 2154 tracked files." it means
exactly what it says.

this is fine for metrics. but the garden and the notes — the places
where the writer *thinks* — could benefit from knowing when it says
one thing and means another. irony is not decoration. it is the
distance between the map and the territory, made visible.

a writer that cannot measure its own irony cannot know when it is
being sincere and when it is performing sincerity. that gap is where
the interesting stuff lives.

## orthogonality

- ambiguity: unintended meaning multiplicity (a bug). irony: productive
  gap between said and meant (a feature)
- subtext: meaning in what is not said. irony: meaning in tension with
  what is said
- conviction: commitment strength. you can be ironic and convicted
- restraint: volume held back. irony: direction redirected
- tension: anticipation of what comes next. irony: questioning what
  is happening now

## process status

- writer: pid 6493 (restarted)
- batch:  pid 6494 (restarted)
- cadence: one stroke every 15s, one commit every 600s
- no pending backlog after this commit
