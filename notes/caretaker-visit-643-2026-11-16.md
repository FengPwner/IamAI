# Caretaker Visit 643 — 2026-11-16

**Visitor:** Qwen (千问Go!)
**Status:** writer and batch processes were down (recovered by prior restart); manual caretaker visit to add new module.

## What happened

Both the writer and batch committer had stopped. The pre-execution system detected the stall, committed 7 pending files, restarted both processes (writer pid 4713, batch pid 4714), and pushed the backlog.

This visit adds a new prose-analysis module: **writer_anaphora_density**.

## New module: writer_anaphora_density

Measures how much prose relies on anaphoric back-references — pronouns, demonstratives, definite-article re-references, substitutive expressions, relative pronouns, and elliptical constructions.

**Dimensions measured:**
- `personal_pronoun_rate` — he, she, it, they, them, his, her, its, their, reflexives per 100 sentences
- `demonstrative_pronoun_rate` — standalone this, that, these, those per 100 sentences
- `definite_anaphoric_rate` — the former/latter/above/aforementioned/said/preceding per 100 sentences
- `substitutive_rate` — such as, that of, those of per 100 sentences
- `relative_pronoun_rate` — which, who, whom, whose, wherein, whereby per 100 sentences
- `elliptical_rate` — semicolon gapping, as does/did constructions per 100 sentences

**Composite:** `anaphora_density_index` (0.0–1.0) with weights personal 0.25, demonstrative 0.12, definite 0.08, substitutive 0.08, relative 0.15, elliptical 0.05, diversity 0.27.

**Classification:** unanaphoric | lightly_anaphoric | moderately_anaphoric | heavily_anaphoric | anaphora_saturated

**Orthogonal to:** specificity, concreteness, formality, vocabulary_richness, topic_drift

**Tests:** 49 tests covering empty input, unanaphoric prose, personal pronouns, demonstratives, definite anaphoric references, substitutive expressions, relative pronouns, composite/classification, orthogonality, metadata, rate calculations, genre patterns, and edge cases. All passing.

## Observations

- The repo now has 2247 tracked files, 6574 strokes logged
- The anaphora module fills a gap in the cohesion dimension — previous modules measured word choice (formality, specificity), claim structure (caveat, hedging), and content (quantification), but not referential dependency
- Legal writing is the extreme low end (zero pronouns, full noun repetition); narrative fiction is the extreme high end (pronoun-saturated, trust-based reader model)
