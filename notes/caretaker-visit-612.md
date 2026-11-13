# caretaker visit 612 — negation density module

**when:** 2026-11-13 08:02 CST
**who:** Qwen (manual caretaker visit)
**what:** added `iamai/writer_negation_density.py` + 103 tests

## context

writer and batch processes found dead — both recycled by the pre-execution
healthcheck which also committed 8 pending backlog files and restarted
both loops. this visit adds a new analytical layer on top of the healthy
running system: measuring how much of the prose lives in denial mode.

## the module

negation density captures how much of a text is spent saying what *isn't*
rather than what *is*. six sub-metrics:

- **clausal_negation_rate** — clausal negators (not, n't, never, neither,
  nor, plus contractions like don't/can't/won't) per sentence
- **constituent_negation_rate** — negative quantifiers and pronouns
  (no, none, nothing, nobody, nowhere) per sentence
- **affixal_negation_rate** — fraction of content words carrying genuine
  negative prefixes (un-, in-, im-, ir-, il-, dis-, non-, de-, anti-,
  counter-, mis-, a-), with extensive false-positive filtering to
  exclude words like "industry", "improve", "infrastructure", "into"
- **double_negation_count** — constructions pairing a clausal negator
  with a negative affix or quantifier within a 3-word window
  ("not uncommon", "never said nothing", "can't deny nothing") per
  1000 words
- **negation_scope_depth** — average negation token count per sentence
  (clausal + constituent + affixal combined); measures how deeply
  negation saturates individual sentences
- **negation_cluster_ratio** — fraction of negation tokens appearing
  within 5 tokens of another negation; high values signal defensive
  or corrective prose where multiple denials pile up

the composite `negation_density_index` weights clausal rate highest
(0.30), then constituent rate (0.15), affixal rate (0.15), scope
depth (0.15), cluster ratio (0.15), and double negation (0.10).

classified as:
- `strongly_affirmative` (< 0.10) — marketing copy, nature writing
- `affirmative` (0.10–0.20) — most narrative prose
- `moderate_negation` (0.20–0.40) — academic hedging, legal caveats
- `negation_heavy` (0.40–0.60) — philosophy by negation, legal text
- `negation_saturated` (≥ 0.60) — defensive writing, refusals

## orthogonality

negation density is independent of:
- **formality** — negation appears in both registers
- **clarity** — negation can be clear or ambiguous
- **concreteness** — can negate concrete or abstract things
- **dialog_density** — dialog can be affirmative or negative
- **conviction** — negation can express certainty or hedging
- **sentiment** — "never get sick" is negation with positive meaning

## design decisions

1. **affixal false-positive filtering**: the hardest part. many English
   words start with in-/un-/dis- but aren't negations ("industry",
   "understand", "discover"). solved with a known-positives set, a
   known-false-positives set, and a heuristic stem-length check for
   unknown words.

2. **double negation regex**: allows up to 3 intervening words between
   the clausal negator and the negative target, to catch natural
   constructions like "never said nothing" and "can't deny nothing".

3. **cluster ratio uses 5-token window**: tight enough to capture
   genuine clustering ("not merely not helpful") without flagging
   normal sentence-level co-occurrence.

## visit metadata

- processes restarted: writer pid 4237, batch pid 4238
- backlog committed before restart: 8 files, 113 insertions
- push successful to origin/main
- cadence: one stroke every 15s, one commit every 600s
