# visit 783 — closing the test gap on content loop detection

2026-11-22 08:10 CST. writer and batch both dead on arrival after
overnight stall (gap 3122s, longest 3269s). 7 uncommitted files,
1 unpushed commit. backlog flushed as commit 97b1709, both processes
restarted (writer pid 3920, batch pid 3921).

## what this visit adds

the `content_loop_detector` module has been sitting in `iamai/` without
a single test. that is a risk: this module is the second half of the
stagnation matrix (visit 781's `content_drift_index` handles topic
diversity; the loop detector handles *structural* periodicity). if it
breaks silently, the caretaker loses the ability to distinguish "writer
is cycling through a fixed template set" from "writer is genuinely
exploring new structures."

`test_content_loop_detector.py` adds 40 tests across six areas:

1. **LoopReport dataclass** — severity classification (NONE/MILD/
   MODERATE/SEVERE), boundary values, summary formatting, frozen
   immutability.

2. **Core detection algorithm** — perfect cycles at periods 2, 3, and
   6 (the real repo pattern); no-loop scenarios; constant sequences;
   noisy cycles; short/empty inputs; max_period limiting.

3. **Noise resilience** — the tricky case. the algorithm picks the
   highest-confidence period, which means a *multiple* of the true
   period can win if noise positions happen to align with a single
   candidate slot. the test uses noise at different phase offsets of
   a 7-element cycle to verify the true period is still detected.

4. **Label extractors** — kind, file path, and text-prefix extraction,
   including edge cases (missing fields, empty text, metric suffix
   stripping).

5. **load_strokes** — file I/O, tail mode, malformed line handling,
   nonexistent paths.

6. **Integration** — end-to-end detection with realistic stroke dicts
   simulating the real 6-kind rotation pattern.

## noise and multiples: a design note

during test development, a subtle property of the algorithm surfaced:
for a sequence of length N with period P, if P divides N evenly and
noise falls on a single phase of the cycle, then any multiple of P
that also divides N absorbs the noise perfectly (confidence 1.0) and
beats the true period. example: 90 labels, period 3, noise at
positions {2, 5, 8, ...} (all mod-3 = 2) → period 30 wins with 1.0
while period 3 gets 0.945.

this is not a bug — the algorithm is working as designed — but it
highlights that periodicity detection on discrete categorical sequences
has inherent ambiguity. for the caretaker's purposes, distinguishing
"period 3" from "period 30 that happens to repeat the 3-cycle" does
not matter; both mean "the writer is stuck in a loop." the severity
grade (which depends on confidence, not period length) is what drives
action.

## current state

- writer: running (pid 3920)
- batch: running (pid 3921)
- pending: 0
- total tests: ~791 (+40 from this visit)
- untested modules remaining: commit_churn, event_interval, push_diag,
  ssh_key_mismatch, stall_loss_estimator
