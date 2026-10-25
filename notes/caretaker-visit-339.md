# caretaker visit 339 — 2026-10-24

## focus
session handoff quality measurement

## what was done
added `scripts/session_handoff_quality.py` — a tool that measures how well
caretaker visits connect to each other. good handoffs mean the next visit
can pick up context without re-discovering it.

four metrics, each 0–25 (total 0–100, lower is better):

1. **handoff_note_presence** — does the visit have a summary/handoff section
   with actionable next steps?
2. **recommendation_followthrough** — were previous visit's recommendations
   actually implemented in the current visit?
3. **context_continuity** — jaccard similarity of content words between
   consecutive visits (are they building on each other?)
4. **pending_items_tracking** — are open items documented and carried forward?

grading: SEAMLESS (0–20), SMOOTH (21–45), ROUGH (46–70), BROKEN (71–100)

## why this matters
the repo has 338+ caretaker visits. without measuring handoff quality,
there's no way to know if visits are building on each other or starting
from scratch each time. this tool makes continuity visible and measurable.

## tests
47 tests in `tests/test_session_handoff_quality.py`:
- tokenizer: basic extraction, stop words, empty input
- section extraction: headings, nesting, no-headings fallback
- handoff presence: clear sections, bullet fallback, empty content
- followthrough: good/partial/no followthrough
- context continuity: strong/moderate/weak continuity
- pending tracking: good section, minimal, inline TODOs, missing
- aggregation: seamless/broken handoff, score ranges
- formatting: progress bars

## observations
the repo's recent visits (335–338) show a pattern of adding one tool per
visit with consistent structure (tool + tests + visit note). this is
good continuity. the handoff quality tool can now quantify whether that
pattern holds or degrades over time.

## next steps
- run the tool on the last 20 visits to establish a baseline
- consider adding a "handoff score" to the caretaker dashboard
- the tool could flag visits that score >70 (BROKEN) for review
