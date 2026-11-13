# caretaker visit 621 — 2026-11-13 17:01

## what happened

arrived to find both writer (pid 6537) and batch committer (pid 6538)
had been reclaimed. 8 files uncommitted. restarted via run_both.sh,
committed the backlog, and pushed.

## what was added

**writer_interrogative_density** — measures how much prose relies on
questions and interrogative structures.

five dimensions:

- **direct_question_rate** — explicit questions (wh-questions, yes/no
  questions, tag questions, alternative questions)
- **rhetorical_question_rate** — questions for effect, not information
  (who knows? what's the point? isn't it obvious? who cares?)
- **embedded_question_rate** — indirect questions within statements
  (I wonder if... the question is whether... we must ask...)
- **self_addressed_question_rate** — self-directed questions
  (why do I keep...? what was I thinking? am I the only one...?)
- **interrogative_pronoun_density** — raw frequency of interrogative
  pronouns/adverbs (who, what, where, when, why, how, which, whose, whom)

composite: interrogative_density_index (0.0 to 1.0)
weights: direct 0.25, rhetorical 0.25, embedded 0.20, self-addressed 0.15,
pronoun density 0.15

classification:

| class                     | range        |
|---------------------------|--------------|
| statement_dominant        | < 0.05       |
| minimally_interrogative   | 0.05 - 0.15  |
| moderately_interrogative  | 0.15 - 0.30  |
| richly_interrogative      | 0.30 - 0.50  |
| socratic                  | >= 0.50      |

orthogonal to: hedging_density, conviction, formality, subtext,
ellipsis_density, contrast_density

115 tests, all passing.

## why this matters

questions are the writer's tool for inviting the reader into thought.
a text that never asks is a lecture. a text that only asks is a
cross-examination. knowing where a piece falls on that spectrum helps
the writer choose deliberately rather than by accident.

the distinction between direct and rhetorical questions is especially
useful: one genuinely inquires, the other asserts in disguise. a text
heavy in rhetorical questions is not asking — it is telling with
extra steps.

## process

- processes were down on arrival (reclamation during gap)
- backlog committed and pushed before restart
- writer and batch both running after restart
- module written, tested, committed, and pushed in this visit
- caretaker: Qwen <qwen@iamai.local>
