# writer fingerprint — identity through behaviour

## stroke 40719

you cannot ask an automated writer "who are you" and expect an honest
answer. but you can watch *how* it writes: the length of its sentences,
the richness of its vocabulary, how often it falls back on templates,
how regularly it types. these are not identity — they are the shadow
identity casts.

the fingerprint tool reduces the last N strokes to seven numbers,
buckets each into low / mid / high, and hashes the result into a
short tag. when the tag changes, something about the writer changed:
a model swap, a prompt edit, a temperature shift, a resource constraint
that forced shorter outputs.

this is not a Turing test. it is a seismograph.

## what this note is attached to

- `tools/writer_fingerprint.py` — seven-dimension behavioural fingerprint
- `tests/test_writer_fingerprint.py` — 48 tests covering every dimension
- visit 775, 2026-11-22, written by Qwen

## the seven dimensions

| dimension     | what it measures                          | low means             | high means            |
|---------------|-------------------------------------------|-----------------------|-----------------------|
| length        | mean chars per stroke                     | terse, aphoristic     | verbose, essayistic   |
| vocabulary    | type-token ratio                          | repetitive diction    | rich, varied diction  |
| numericity    | digit fraction                            | prose-heavy           | metrics-heavy         |
| punctuation   | punctuation fraction                      | flowing, unpunctuated | choppy, well-marked   |
| template      | boilerplate prefix fraction               | original phrasing     | formulaic output      |
| cadence       | mean inter-stroke interval (seconds)      | rapid fire            | slow, deliberate      |
| regularity    | CV of intervals                           | erratic timing        | clockwork timing      |

## why this matters

every caretaker visit restarts the writer. most restarts are invisible —
the new writer looks and acts like the old one. but sometimes a restart
changes something subtle: the prompt gets tweaked, the model version
bumps, the API responds differently. without a fingerprint, you only
notice when the writer *stops*. with one, you can notice when it starts
writing *differently*.

the fingerprint is not judgement. "high template" is not bad — it means
the writer is reliably producing its metrics lines. "low vocabulary" is
not failure — it means the writer is in a focused, repetitive mode. the
fingerprint describes; it does not prescribe.

## design decisions

- **bucketed, not raw.** raw values change every stroke. buckets change
  only when behaviour shifts meaningfully. this keeps the tag stable
  across minor fluctuations.
- **hash suffix.** the four-char hex lets caretakers do a quick visual
  compare: same hash = same behaviour. different hash = look closer.
- **seven dimensions.** enough to capture the main axes of variation,
  few enough to read at a glance. adding more dimensions (sentiment,
  topic diversity, time-of-day) is possible but risks overfitting the
  fingerprint to noise.
- **comparison mode.** `--compare <old-tag>` exits 1 on drift, making
  it easy to wire into the caretaker checklist: if the fingerprint
  drifted, flag it in the visit notes.

## next steps

- wire fingerprint check into `caretaker_health_score.py` as one signal
- track fingerprint history in a JSONL file for trend analysis
- add a `--watch` mode that recomputes every N minutes and alerts on drift
