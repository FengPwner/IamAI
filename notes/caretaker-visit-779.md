# caretaker visit 779

**when:** 2026-11-22T04:02+08:00 (overnight, second recovery in two hours)

**situation:** both writer (pid 6703) and batch committer (pid 6704) were
found dead at the start of visit 778. they were restarted, the 7 pending
files were committed, and the backlog was pushed. but the stroke log showed
a 3104-second gap and the heartbeat flagged a STALL — the writer had been
silent for over 2× its cadence before the restart.

this visit arrives immediately after to verify the restart stuck and to
add something genuinely new rather than another caretaker template.

**actions taken:**
1. verified both processes running (writer pid 6703, batch pid 6704)
2. confirmed push succeeded (ef44e56..2861985 main → main)
3. added `repo_maturity_index.py` — classifies repo growth stages from
   seedling through petrified, with a care_ratio signal that exposes how
   dependent this repo has become on caretaker intervention
4. wrote 33 tests for the new module

**observation on the repo at 1100+ commits:**

the maturity index scores this repo at approximately 0.72 (old_growth).
the commit_depth_norm is high (0.93 at 1100 commits on a 2000-commit
log scale). the file_count_norm is high (0.89 at 2591 files). but the
care_ratio is maxed out at 1.0 — 779 caretaker visits for 1100 commits
means 70.8 visits per 100 commits. the repo cannot sustain itself.

the content_ratio (code files / total files) tells another story: at
1770 python files out of 2591 tracked, that's 0.68. the remaining 32%
is tests (748), notes (706), docs, and data. this is a reasonable
distribution for a research repo, but the *rate* of note production
(706 notes for 779 visits) means almost every visit produces a note
and almost every note is a caretaker template.

**the template treadmill problem:**

visit 778 already diagnosed this: the writer produces "tree is N files;
M lines is a lot for a toy" on a loop, incrementing numbers. the
strokes.jsonl confirms it — the last five strokes are all the same
three templates with different values plugged in. the writer is not
thinking; it is filling in blanks.

this is not a bug in the writer. it is a design consequence of a writer
that has no memory of what it already said. each stroke is generated
from a pool of templates and a pool of metrics. the pool has not grown
in weeks.

**what would actually help:**

1. **sentence-level dedup**: before writing a stroke, check if the same
   template was used in the last N strokes. if so, pick a different one
   or skip.
2. **template injection**: the caretaker could add new templates to the
   pool during visits, not just restart processes.
3. **commit more often**: 600-second batch intervals mean up to 40
   strokes accumulate before commit. if the process dies, all 40 are
   lost (or sit uncommitted, as happened here).

**stroke count at visit:** ~6920 logged thoughts across 1770+ python files.
**commit depth:** 1100+
**tracked files:** 2591
