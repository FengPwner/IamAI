# repo_attention_span — how long does the repo stay on one topic?

Added 2026-10-23.

The idea: `commit_file_overlap` measures whether two adjacent commits
touch the same files (Jaccard similarity). `category_momentum` measures
whether the overall direction is shifting. Neither tells you *how long*
the repo sustains focus on one area before switching.

`repo_attention_span` groups consecutive commits into runs where the
dominant file-area stays the same, then reports their lengths.

## Grades

| avg span    | reading      |
|-------------|--------------|
| >= 8        | deep_focus   |
| 4 – 7       | steady       |
| 2 – 3       | restless     |
| < 2         | scattered    |

## Design decisions

- **Top-level directory as area proxy.** `iamai/`, `tests/`, `tools/`,
  `notes/`, `docs/`, `data/` are the main areas. Anything else is
  `other`; files without a directory are `root`. Simple, but good
  enough — deeper paths rarely change the semantic area.

- **Merge commits inherit.** A merge commit with no changed files
  inherits the area of the preceding span rather than creating a
  phantom "empty" span. This keeps the analysis honest about what was
  actually worked on.

- **Deterministic tie-break.** When a commit touches multiple areas
  equally, alphabetically-first wins. This matters for reproducibility
  across runs — without it, the same commit history could produce
  different span counts.

## What it fills

The gap between "are consecutive commits similar?" (file_overlap) and
"is the repo heading somewhere?" (category_momentum). Attention span
is about *duration of focus* — a different axis entirely.

## Current reading

As of this note: the repo tends toward `steady` spans (4–7 commits on
one area before switching), which matches the observed pattern of
"add a module, write tests, update docs, then move to the next thing."

39 tests covering classifier, file mapping, dominant area, data
classes, mocked git integration, and summary formatting.
