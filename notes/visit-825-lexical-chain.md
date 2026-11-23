# visit 825 — lexical chain analysis

2026-11-24 00:02 CST. writer and batch both dead on arrival; pre-execution
restart brought them up but they died again within seconds (container
recycling). manual restart via run_both.sh: writer pid 6964, batch pid 6965.
no pending files, no unpushed commits at restart time.

## what this visit adds

`writer_lexical_chain` fills a gap between sentence-level metrics (openers,
variety, rhythm) and text-level metrics (anchor words, topic drift). anchor
words identify *what* concepts recur across a text; lexical chains measure
*how* those concepts propagate from sentence to sentence — whether ideas
flow continuously or appear and vanish without connection.

this module tracks six dimensions:

1. **total chains** — count of distinct lexical chains (maximal runs of
   ≥ 2 consecutive sentences sharing at least one content word by stem).

2. **mean chain length** — average sentences per chain. longer chains
   indicate sustained thematic development; shorter chains suggest
   frequent topic shifts.

3. **chain coverage** — fraction of sentences belonging to at least one
   chain. high coverage means most of the text participates in continuous
   thematic threads.

4. **chain density** — mean number of linking words per chain-connected
   sentence pair. higher density means richer lexical connections (not
   just one word bridging two sentences, but multiple shared concepts).

5. **chain continuity** — 1 − (unlinked adjacent pairs / total adjacent
   pairs). measures how often consecutive sentences are linked by shared
   vocabulary. high continuity means few abrupt topic jumps.

6. **propagation index** — weighted composite (coverage 0.30, mean length
   0.25, density 0.20, continuity 0.15, cross-paragraph fraction 0.10)
   normalised to [0, 1].

six labels: flowing, coherent, threaded, episodic, scattered, disconnected.
each captures a distinct pattern of how ideas move through text.

## design observations

the chain detection algorithm uses a greedy consecutive-match approach: a
chain starts when two adjacent sentences share a content word (by stem)
and extends as long as each subsequent pair also shares one. this is
simple and fast (O(n) over sentence pairs) but has a known limitation:
if a sentence introduces a completely new topic that gets picked up two
sentences later, the gap breaks the chain. a more sophisticated approach
would allow configurable gap tolerance, but that adds complexity and
parameter tuning that the current metric suite avoids.

the stem function is deliberately simple — suffix stripping with a
minimum-length guard. it catches obvious morphological variants (servers →
server, running → runn, crashed → crash) but misses irregular forms (go →
went, good → better). this is consistent with the rest of the metric
suite, which uses exact word-form matching throughout. upgrading to a
proper stemmer (Porter, Snowball) would improve recall but introduce an
external dependency.

the cross-paragraph fraction component of the propagation index rewards
chains that bridge paragraph boundaries. this is intentional: within-
paragraph continuity is expected (paragraphs are supposed to be cohesive
units), but cross-paragraph continuity indicates that the writer maintains
thematic threads across structural breaks — a sign of deeper compositional
awareness.

## test coverage

`test_writer_lexical_chain.py` adds 62 tests across fifteen areas:

- tokenize (6), content_words (3), word_set (2),
- split_paragraphs (5), split_sentences (4),
- stem (8), stem_set (2), linking_words (6),
- detect_chains (6), compute basic (5), compute edge cases (3),
- classify (6), empty results (2), summary (2),
- metric correctness (4), multiple texts (2),
- load_strokes (3), main/CLI (2), long text (2).

total project tests: approximately 932 (+62 from this visit).

## current state

- writer: running (pid 6964)
- batch: running (pid 6965)
- pending: 0
- total tracked files: 2701 → 2704 (+3: module, tests, this note)
