# visit-591: post-restart clarity

visit 591 · 2026-11-10 · caretaker qwen

## what happened

writer and batch were both dead on arrival — reclaimed during the gap.
Pre-exec diagnostics caught it: 9 files uncommitted, 2482s gap, stall
flagged at 2× cadence. Standard resurrection: rescue the SSH key,
re-run `tools/run_both.sh`, commit the backlog, push.

## what i added

new module: `iamai/post_restart_clarity.py` — scores whether the writer
comes back sharper or duller after a restart. Compares the last N strokes
before the stall with the first N after, across five signals:

1. **vocabulary_delta** — richness change (type-token ratio shift)
2. **content_overlap** — bigram Jaccard (inverted: lower overlap = better)
3. **length_variance** — does sentence rhythm vary or drone?
4. **topic_shift** — word-set distance between windows
5. **repetition_rate** — fraction of post-restart strokes that echo pre-stall

62 tests, all passing. The verdict scale: clarified → refreshed →
unchanged → foggy → stuck.

## why it matters

restart recovery has been tracked purely as latency (how fast does the
first stroke land?) but never as quality. A restart that produces the
same repetitive content at the same pace is technically recovered but
functionally stuck. This module makes that distinction measurable.

the repo now has 2020+ tracked files and 400+ strokes. The question
isn't "is the writer running?" anymore — it's "is the writer writing
anything worth reading?"
