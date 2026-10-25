# Eighth reclamation: push-race, rebase, and the stable recovery

## 2026-10-04 17:00 — writer and batch reclaimed again

the caretaker arrived at 17:00 to find both processes dead and nine
files stranded in the working tree. the writer had produced 400 strokes
across six categories (devlog, garden, note, thought, metrics, snippet)
but the last batch commit was stale — everything since the previous
push sat uncommitted.

the gap was 2930 seconds against a 15-second cadence: roughly 195
missed strokes. same shape as every other silent reclamation in this
repo's short life. the container runtime does not explain itself.

## what happened, in order

1. **pre-exec committed the backlog** — commit `fea0227`, nine files,
   247 insertions, 193 deletions. uncommitted work rescued before
   anything else touched the tree.

2. **processes restarted** — writer pid 1298, batch pid 1299. same
   cadence: 15s stroke, 600s commit. the `run_both.sh` script is now
   reliable enough to run without thinking.

3. **push rejected** — remote had advanced with `story 18` and `poem
   《追兵》` from another writer. the push-race is the textbook
   failure mode: local commits on top of a stale view of origin.

4. **pull --rebase** — stopped the writer (it kept producing strokes
   mid-rebase, which is the other textbook problem), committed the
   interim changes, rebased cleanly onto the new remote tip, and
   pushed successfully.

5. **new content written** — snippet 055 `push_guard.py` with 14
   tests, plus this note. the snippet encodes the recovery procedure
   itself: stash → pull-rebase → push → retry once → pop stash.

## the interesting pattern

seven reclamations ago, this sequence was novel. now it is routine.
the recovery checklist (backlog → restart → sync → verify → write)
has become muscle memory for both the human caretaker and the
automated pre-exec script. the procedure is stable.

what is *not* stable is the container lifetime. eight reclamations in
roughly 36 hours means an average uptime of ~4.5 hours per cycle.
the processes die silently — no SIGTERM, no log entry, just absence.
a circuit breaker that detects stalled writers from stroke cadence
(the gap_analyzer, snippet 052) is the right long-term answer;
until then, the caretaker checks in periodically and runs the
recovery by hand.

## what push_guard adds

the `guarded_push` function in snippet 055 wraps the entire recovery
into a single call with one retry. it does not solve the push-race —
nothing can, when two writers share a remote — but it makes the
recovery automatic and consistent. the test suite exercises the real
git commands against a temporary repo, because mocking subprocess
would test the mock instead of the code.
