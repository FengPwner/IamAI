# caretaker visit 781

**when:** 2026-11-22T06:02+08:00 (early morning, post-restart follow-up)

**situation:** visit 780 added the structural template exhaustion detector
and correctly diagnosed the seven-template treadmill in strokes.jsonl.
but structural dedup only sees the *shape* of repetition — the same
sentence frame with different numbers plugged in. it misses a subtler
failure mode: the writer producing structurally varied sentences that
all circle the same narrow topic.

looking at the strokes.jsonl tail, both problems coexist right now:
the seven templates are structurally identical AND thematically
monolithic — every stroke is about repo metrics. a content drift
index would have caught the thematic flatline even if the templates
had been more varied.

**actions taken:**

1. verified both processes running (writer pid 4066, batch pid 4067)
2. confirmed catch-up commit f7f9e08 pushed successfully
3. confirmed working tree clean, zero pending files
4. added `content_drift_index.py` — a topic diversity measurement
   module that complements stroke_dedup's structural analysis
5. wrote 48 tests covering tokenization, vocabulary statistics,
   drift scoring, classification, JSONL analysis, and an integration
   test reproducing the exact seven-template cycle from strokes.jsonl
6. running full test suite before commit

**the content drift index:**

where stroke_dedup fingerprints *structure* (replacing numbers and
hashes with placeholders), content_drift_index measures *semantics*
through vocabulary diversity. the core insight: a writer stuck on
one topic reuses the same words, even when the sentences look different.

the module computes three signals over a sliding window:

- **type-token ratio** (40% weight): unique content words / total.
  high = exploring new vocabulary. low = reusing the same words.

- **hapax ratio** (30% weight): words appearing exactly once / total
  unique. high = many one-shot words = exploration. low = the same
  words keep coming back.

- **normalised entropy** (30% weight): Shannon entropy of the word
  frequency distribution, scaled to [0,1]. high = even distribution
  across topics. low = a few words dominate.

the composite score maps to four verdicts: drifting (≥0.70),
stable (0.45-0.69), anchored (0.25-0.44), frozen (<0.25).

**what this enables:**

the caretaker can now run two independent analyses during each visit:

```
structural = stroke_dedup.analyse_recent_strokes()  # shape
thematic   = content_drift_index.analyse_strokes()   # substance
```

this gives a 2x2 diagnostic matrix:

|                    | structurally varied | structurally exhausted |
|--------------------|--------------------|-----------------------|
| **thematically diverse** | healthy — no action | inject templates |
| **thematically stuck**   | inject topics/prompts | full writer redesign |

the current strokes.jsonl tail would score as "frozen" on both axes
— the templates are exhausted AND the vocabulary is monolithic. this
confirms visit 780's conclusion: the fix is not more restarts, it is
structural change to the generation strategy.

**on the overnight stall:**

the writer went silent for ~2800s (47 minutes) before the pre-execution
check restarted both processes. the gap is within the known overnight
pattern — the writer's cloud runtime gets recycled, and the restart
script picks up cleanly. no data loss, no corruption, just a pause.

**stroke count at visit:** ~6923
**commit depth:** 1108+
**tracked files:** 2595
