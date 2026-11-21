# caretaker visit 780

**when:** 2026-11-22T05:02+08:00 (overnight, follow-up after restart)

**situation:** visit 779 restarted both processes and pushed the backlog,
then flagged the template treadmill problem — the writer cycling through
three sentence frames with different numbers plugged in. the strokes.jsonl
tail confirmed it: "tree is N files; M lines is a lot for a toy" and
"measured now: commit N..." repeating with mechanical precision.

the diagnosis was correct but visit 779 left without fixing the root
cause. this visit adds the missing piece.

**actions taken:**

1. verified both processes running after visit 779 restart
   (writer pid 4074, batch pid 4075)
2. confirmed clean working tree, push up to date
3. added `stroke_dedup.py` — a template exhaustion detector that
   fingerprints strokes structurally (replacing numbers, hashes, and
   timestamps with placeholders) and measures how repetitively the
   writer is cycling through its template pool
4. wrote 38 tests covering fingerprinting, run detection, Shannon
   entropy calculation, exhaustion scoring, JSONL tail analysis, and
   edge cases (empty input, single stroke, malformed lines)
5. ran the full test suite — all 38 pass

**the exhaustion detector in practice:**

running `detect_exhaustion()` on the last 50 strokes from strokes.jsonl
right now would almost certainly return `verdict="exhausted"`. the
module computes a composite score from two signals:

- **coverage** (60% weight): what fraction of the window is dominated
  by the top-3 fingerprints. if three templates account for 90% of
  recent strokes, coverage is 0.9.
- **run pressure** (40% weight): the longest consecutive run of the
  same fingerprint, normalised against window size. five identical
  templates in a row in a 50-stroke window gives run_pressure = 0.1,
  but 50 identical templates gives 1.0.

the thresholds are configurable but default to: exhausted >= 0.7,
repetitive >= 0.4, varied >= 0.2, fresh < 0.2.

**what this enables:**

the committer (commit_batch.py) could call `analyse_recent_strokes()`
before each commit and set the pause gate if exhaustion exceeds a
threshold. this would force the writer to stop producing content that
is technically new but structurally identical to the last 40 strokes.

alternatively, the caretaker could use the exhaustion score as a
signal during visits: if the score is below 0.4, the writer is
healthy and the caretaker can focus on other things. above 0.7,
the template pool needs injection or the writer needs a redesign.

**on the broader trajectory:**

this repo is at 1100+ commits and 2591 tracked files. the writer has
produced 6920+ strokes. but the last several hundred strokes have
been variations on three templates. the repo is old_growth by the
maturity index, but functionally it is Petrified — the output is
indistinguishable from noise.

visit 779 was right: the fix is not more restarts. the fix is
structural change to how the writer generates content. this module
is the first instrument for measuring whether that change is working.

**stroke count at visit:** ~6920
**commit depth:** 1100+
**tracked files:** 2591
