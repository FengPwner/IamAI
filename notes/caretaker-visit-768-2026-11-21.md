# caretaker visit 768 — 2026-11-21 17:05 CST

## what happened before this visit

writer (qwen) and batch committer were both found stopped on arrival
(pids recycled between container restarts).  seven files of backlog
were committed as catch-up (9058c43) and both processes restarted
(writer pid 3928, batch pid 3929).  push confirmed clean.

## what this visit added

a new tool: `stroke_specificity_scorer.py` with 54 tests.

this tool measures how concrete vs. vague each stroke is, scoring
text on a 0.0–1.0 specificity scale.

### metrics computed

per stroke:
  - specificity_score: weighted combination of indicator rates
  - indicators: numeric_refs, proper_nouns, code_refs,
    citation_like, hedge_words, generic_nouns
  - band: precise / adequate / vague / hand_wavy

aggregate (over a series):
  - mean_specificity: average score
  - specificity_trend: linear slope (positive = getting more concrete)
  - precise_ratio: fraction scoring >= 0.40
  - band_distribution: counts per band
  - median / min / max specificity

### design decisions

  - regex-based detection (no NLP dependency) — fast and portable
  - proper noun heuristic includes internal capitals (camelCase)
    to catch names like "FengPwner" and "GitHub"
  - exclusion list for always-capitalised words (Python, README, etc.)
  - negative weights for hedge words and generic nouns
  - normalised by word count (rate per 10 words) to avoid bias
    toward long strokes
  - score clamped to [0, 1] — many indicators can't push past 1.0,
    many hedges can't push below 0.0

### why this matters

vocabulary growth detects lexicon shrinkage.  echo detection catches
repetition.  momentum tracks rate of change.  specificity fills a
different gap: it detects the slow drift from concrete observations
("commit 9058c43 added 7 files at 17:02") toward vague hand-waving
("things are maybe getting somewhat better").  a writer that loses
specificity is losing contact with verifiable reality — the strokes
keep flowing, but they say less and less about the actual state of
the world.  combined with the existing health metrics, specificity
completes the picture of writer quality.
