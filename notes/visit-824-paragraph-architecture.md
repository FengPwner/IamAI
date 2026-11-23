# visit 824 — paragraph architecture analysis

2026-11-23 23:02 CST. writer and batch both dead on arrival after
restart-required stall (gap 6940s, longest 3263s). processes had
been recycled; pre-execution restart brought them back (writer pid
4113, batch pid 4114). no pending files, no unpushed commits.

## what this visit adds

`writer_paragraph_architecture` fills a gap the existing metric
suite has been circling but never quite landing: paragraph-level
structure. sentence-level metrics (rhythm, variety, openers, clause
connectivity) describe what happens *within* sentences. anchor words
and cohesion describe what holds the *whole text* together. but the
middle scale — how individual paragraphs are shaped, how they connect
to their neighbours, how their lengths vary — has been unmeasured.

this module analyses six dimensions:

1. **paragraph length distribution** — mean, median, and coefficient
   of variation. high CV means the writer varies paragraph length
   deliberately; low CV means uniform sizing.

2. **length progression** — Pearson correlation between paragraph
   position and length. positive values mean paragraphs grow longer
   toward the end (deceleration, elaboration); negative values mean
   they grow shorter (acceleration, compression).

3. **internal cohesion** — Jaccard similarity of consecutive sentence
   word-sets within each paragraph, averaged. high cohesion means
   sentences stay on topic; low cohesion means each sentence
   introduces fresh vocabulary.

4. **transition strength** — lexical overlap between the last sentence
   of one paragraph and the first sentence of the next. strong
   transitions create smooth reading; zero transitions create abrupt
   jumps.

5. **topic sentence rate** — fraction of paragraphs whose first
   sentence shares at least one content word with the rest of the
   paragraph. a high rate means the writer introduces topics up
   front and develops them.

6. **architecture index** — weighted composite (cohesion 0.25, topic
   rate 0.25, length variation 0.20, transition 0.15, length quality
   0.15) normalised to [0, 1].

six labels: well-structured, developing, loose, monolithic,
fragmented, uniform. each captures a distinct paragraph habit.

## test coverage

`test_writer_paragraph_architecture.py` adds 67 tests across eleven
areas:

- tokenize (6), content_words (3), split_paragraphs (5),
  split_sentences (4), word_set (2), jaccard_similarity (6),
  pearson_correlation (6), compute empty/minimal (2),
  basic metrics (3), length progression (3), internal cohesion (2),
  transition strength (3), topic sentence rate (2),
  architecture index (3), classify (8), empty result (2),
  summary (2), multiple strokes (2), report (1), CLI (2).

total project tests: approximately 870 (+67 from this visit + 54
from visit 823's anchor_words).

## design observations

paragraph splitting uses the same blank-line convention as every
other module in the suite — two or more consecutive newlines. this
works well for the writer's stroke format, where paragraphs are
separated by explicit blank lines. it would not work for text that
uses indentation-only paragraph breaks (common in some fiction
styles), but that limitation is shared across the entire metric
suite.

the Jaccard similarity used for cohesion and transition is
deliberately simple: it operates on content-word sets, ignoring
frequency and order. more sophisticated approaches (TF-IDF cosine,
embedding similarity) would be more accurate but would require
external dependencies. Jaccard is parameter-free, fast, and good
enough to distinguish well-connected paragraphs from scattered ones.

the length_quality component of the architecture index penalises
paragraphs with mean length below 30 or above 100 words. these
thresholds are heuristic, not universal: technical documentation
often has shorter paragraphs than essays, and academic writing
often has longer ones. the classification labels compensate
somewhat — "monolithic" fires on mean_length > 120 regardless of
index score, and "fragmented" fires on mean_length < 20.

## current state

- writer: running (pid 4113)
- batch: running (pid 4114)
- pending: 0
- total tracked files: 2698 → 2701 (+3: module, tests, this note)
