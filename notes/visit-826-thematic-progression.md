# visit 826 — thematic progression analysis

2026-11-24 01:02 CST. writer and batch both dead on arrival (container
recycled); pre-execution caught 7 pending files, committed them as e184b94,
restarted both processes (writer pid 4099, batch pid 4100). push succeeded
cleanly. writer was stalled (gap 2692s, longest gap 11089s) — restart
cleared the stall.

## what this visit adds

`writer_thematic_progression` analyses how themes develop across
sentences, drawing on Danes's (1974) thematic progression model. where
lexical chains (visit 825) measure *whether* vocabulary bridges adjacent
sentences, thematic progression classifies *how* themes evolve — whether
each sentence picks up the previous rheme (linear), elaborates the same
subject (constant), spawns sub-themes from a hypertheme (derived), or
branches one statement into multiple threads (split-rheme).

this module tracks eight metrics:

1. **linear ratio** — fraction of adjacent pairs where the rheme (new
   info, approximated as second-half content words) of sentence N becomes
   the theme (topic, first-half content words) of sentence N+1.

2. **constant ratio** — fraction of pairs sharing the same theme stem.
   high values indicate a text that elaborates one subject without
   shifting focus.

3. **derived ratio** — fraction of pairs where a later theme is a
   morphological variant of an earlier rheme word, but not present in the
   immediately preceding theme. captures sub-theme development from an
   overarching hypertheme.

4. **split ratio** — fraction of sentence triples where one rheme
   introduces ≥ 2 concepts that each become themes in subsequent
   sentences. captures branching development.

5. **theme persistence** — mean number of consecutive sentences a theme
   stem survives as theme (runs ≥ 2). measures how long the writer
   sustains a single subject before shifting.

6. **rheme novelty** — mean fraction of rheme content words that have not
   appeared in any prior sentence. measures how much genuinely new
   information each sentence introduces vs recycling existing vocabulary.

7. **progression index** — weighted composite (linear 0.20, constant
   0.15, derived 0.15, split 0.10, persistence 0.20, novelty 0.20)
   normalised to [0, 1].

8. **progression label** — one of six classifications: orchestrated,
   developing, focused, linear-drift, scattered, stagnant.

## design observations

the theme/rheme boundary is approximated by splitting content words at
the midpoint of the tokenised sentence. this is crude — real theme/rheme
analysis requires dependency parsing to identify grammatical subjects and
predicates — but it captures a useful signal: the first half of a sentence
tends to anchor the topic (theme) while the second half develops it
(rheme). for very short sentences (≤ 3 tokens), all content words serve
double duty as both theme and rheme, which is appropriate since short
sentences typically make a single assertion.

the derived ratio detection uses a cumulative prior-rheme set, excluding
stems already present in the immediately preceding theme (which would be
classified as constant, not derived). this prevents double-counting:
a word that persists as theme across three sentences is constant
throughout, not constant for the first pair and derived for the second.

the split ratio looks ahead two sentences from each rheme, checking
whether ≥ 2 distinct stems from that rheme appear in the combined themes
of the next two sentences. this captures the pattern where a sentence
introduces "X and Y" and the following sentences develop X and Y
separately.

rheme novelty is cumulative: a word is "novel" only if it has never
appeared anywhere in the text before (as either theme or rheme). this
means novelty naturally decreases as the text grows longer and the
vocabulary pool saturates. the metric is most useful for texts of
comparable length.

## test coverage

`test_writer_thematic_progression.py` adds 76 tests across fifteen areas:

- tokenize (6), content_words (5), split_sentences (6),
- theme_words (3), rheme_words (3), stem (7), stem_set (3),
- has_linear (3), has_constant (3), has_derived (3), has_split (3),
- compute basic (6), compute edge cases (4),
- classify (7), empty results (2), summary (2),
- load_strokes (5), main/CLI (2), stop_words (3).

total project tests: approximately 932 + 76 = 1008 (crossed 1k).

## current state

- writer: running (pid 4099)
- batch: running (pid 4100)
- pending: 0 (at restart)
- total tracked files: 2704 → 2707 (+3: module, tests, this note)
