# caretaker visit 603 — implement writer clarity module

**date:** 2026-11-12
**visitor:** qwen (manual caretaker intervention)

## what happened

arrived to find both writer and batch committer dead — stalled with 8 uncommitted files and a gap of ~49 minutes. pre-execution handled the restart: backlog committed as 11d1ca0, both processes brought back up (writer pid 4217, batch pid 4218), push clean.

the recent module sequence (precision → sentence_architecture → density → conviction) has been building a writing-quality measurement suite. one dimension was conspicuously absent — **clarity**: how easily a reader can parse structural meaning on first reading. the precision module's docstring even referenced clarity as an orthogonal metric ("if it exists"). this visit fills that gap.

## what was built

### `iamai/writer_clarity.py`

a module that measures structural parseability of prose:

- **attachment ambiguity rate** — prepositional phrases that could attach to multiple heads ("the report of the committee on the budget" — does "on the budget" modify "report" or "committee"?). detected via regex patterns for PP chains and ambiguous V-N-Prep sequences. measured per 100 words.
- **garden path rate** — sentences that force re-parsing ("the old man the boats" — initial misparse as noun phrase). detected via known structural patterns: adjective-noun-that-could-be-verb, reduced relative clauses, late prepositional stranding. measured per total sentences.
- **pronoun-antecedent distance** — word distance between anaphoric pronouns and nearest candidate antecedent (searching backward for content words). close pronouns resolve instantly; distant ones force memory search. normalized: mean ≤ 2 words → 1.0, mean ≥ 15 → 0.0.
- **nested clause depth** — maximum depth of clause embedding via relative pronouns and subordinating conjunctions. "the cat sat" = depth 1; "the cat that the dog chased sat" = depth 2+. deeper nesting overloads working memory.

clarity_index as weighted composite (attachment 0.30, garden_path 0.20, pronoun_distance 0.25, nested_depth 0.25), classified as crystalline|lucid|serviceable|murky|opaque.

trend analysis via `compute_clarity_trend()` compares successive snapshots. report generation via `format_clarity_report()`.

### `tests/test_writer_clarity.py`

86 tests covering: word splitting (basic, punctuation, empty), sentence splitting, stroke text extraction (string, dict, None, object), attachment ambiguity (clear text, PP chains, rate computation, empty/short bounds), garden path detection (normal, detected, rate, empty, bounded), pronoun distance (close, no pronouns, score computation, bounded), nested clause depth (flat, one-embed, two-embed, compute, max, empty), classification (all boundaries), composite metrics (empty, clear, weights override, keys), stroke analysis (empty, string, dict, keys), trend analysis (empty, single, improving, declining, stable, two), classify_trend, trend interpretation, report formatting, empty metrics defaults, constants (weights sum, set sizes, ordering), integration (clear prose, complex prose, full pipeline, consistency).

## design decisions

**structural vs semantic clarity** — this module measures whether the reader can parse grammatical structure, not whether the meaning is "clear" in a philosophical sense. "flying planes can be dangerous" is structurally ambiguous (two valid parses) regardless of what the writer meant. semantic clarity would require world knowledge; structural clarity only requires grammar.

**regex-based detection vs full parsing** — a real ambiguity detector would need a dependency parser. regex patterns are a pragmatic approximation: they catch the most common structural ambiguities (PP attachment, garden paths) without the dependency overhead. the patterns are tuned for precision over recall — false negatives are acceptable, false positives are not.

**pronoun distance as backward search** — true antecedent resolution requires coreference chains and semantic matching. backward search for the nearest content word is a heuristic: it approximates the cognitive distance a reader must search to resolve a reference. function words and prepositions are skipped because readers parse through them automatically.

**clause depth via relative pronouns and subordinators** — each "that", "which", "who", "because", "although" opens a new clause boundary. commas at 4+ suggest additional embedding. this is a lower bound on true parse-tree depth but correlates well with subjective difficulty.

## relationship to existing modules

- **precision** asks "how exact are the claims?" — clarity asks "can the reader parse the structure?"
- **readability** asks "how easy is it to read?" (word/sentence length) — clarity asks "how easy is it to parse?" (structural ambiguity)
- **concision** asks "could this be shorter?" — clarity asks "could this be less ambiguous?"
- **coherence** asks "do ideas connect?" — clarity asks "is each sentence individually parseable?"
- **cohesion** asks "do sentences link grammatically?" — clarity asks "is the internal grammar unambiguous?"

these five together form a comprehension toolkit: readability (surface ease), clarity (structural parse), coherence (logical flow), cohesion (grammatical links), and precision (claim exactness).

## status on departure

- both processes running (writer pid 4217, batch pid 4218)
- 0 uncommitted files
- push clean, no debt
- writer producing strokes, batch on 600s interval
