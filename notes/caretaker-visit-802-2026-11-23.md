# visit 802 — rebase_safety: pre-rebase gate with 23 tests

2026-11-23 01:05 CST. human-requested caretaker check.

## context

visits 800 and 801 focused on post-crash recovery (autorecover) and
commit churn measurement. both operate *after* something went wrong.
the missing piece is prevention: stopping a caretaker from starting
a rebase while the writer is still feeding strokes into the tree.

`iamai/rebase_safety.py` was added earlier but had zero test coverage.
a safety gate without tests is a locked door you've never tried —
you don't know if it opens when you need it or sticks when you don't.

## what this visit adds

### tests/test_rebase_safety.py (23 tests)

six test classes covering every public surface:

1. **RebaseReadiness / SafetyCheck / Verdict** — enum values,
   dataclass defaults, summary formatting (✓/✗ with pass/total).

2. **check_pause_signal** — sentinel present → pass; absent → blocking.

3. **check_process_liveness** — no PID → safe; stale PID → safe;
   live PID → blocking; corrupt PID → warning.

4. **check_batch_liveness** — mirror of process liveness for the
   batch committer.

5. **check_dirty_state** — empty tree → pass; managed files present
   → warning (CLI must verify with git).

6. **assess()** — aggregate logic: all clear → SAFE; missing pause
   + live writer → UNSAFE with blocking checks; remediation always
   includes sleep + rebase tail.

7. **verdict_to_dict** — JSON serialisation round-trip.

8. **Constants** — WRITER_MANAGED_FILES includes strokes.jsonl;
   patterns contain {writer} placeholder.

the tests use `unittest.mock.patch` to redirect PID and pause file
paths into `/tmp` with unique suffixes, avoiding collisions with the
live writer. cleanup is in `finally` blocks, not `tearDown`, so a
test crash still removes the temp files.

## observations

the repo now has 2645+ tracked files and 7000+ strokes. the writer
cadence is 15s per stroke, 600s per commit batch. at this density,
a single failed rebase costs ~5 minutes of caretaker time (abort,
stash, re-flush, retry). the safety gate pays for itself on the
first prevented failure.

next steps this visit considered but did not implement:
- integrating `assess()` into `tools/run_both.sh --stop` so that
  the stop sequence verifies the pause signal took effect before
  returning control.
- a `--json` flag on `tools/rebase_safety_check.py` for scripted
  consumption by the caretaker loop.

both are small and can ship in visit 803.

## metrics

- tests added: 23
- tests passing: 23
- files changed: 2 (tests/test_rebase_safety.py, this note)
- visit gap: ~1h from visit 801
