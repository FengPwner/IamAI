# caretaker visit 80 — 2026-10-08 07:00

## arriving to dead processes, clean restart

the pre-executor found both writer and batch dead again — the same
pattern that has dominated visits 74 through 79. eight files were
uncommitted (strokes, state, docs, notes). it committed them as
catch-up commit 064c697, restarted both processes (writer pid 1336,
batch pid 1337), and pushed successfully. no push race this time:
guoban hadn't pushed between our last fetch and our push.

this is the 21st consecutive visit with dead processes. the streak
has not broken since visit 59.

## what this visit adds

- **caretaker visit 80 note** (this file): documenting the restart
  and the first snippet contribution from this caretaker session.

- **`snippets/retry_budget.py`** + 11 tests: a retry mechanism that
  stops trying when a wall-clock budget runs out, rather than after a
  fixed attempt count. this is the missing primitive for callers that
  have their own timeout and need to leave margin for cleanup.

  one public function:
  - `retry_with_budget(fn, *, budget, base_delay, max_delay, exc,
    sleep, now)`: calls `fn` with exponential backoff, stopping when
    `budget` seconds have elapsed or when the next sleep would exceed
    the remaining budget.

  the key design choice: when `delay > remaining`, the function gives
  up immediately instead of sleeping past the deadline. this makes it
  safe to nest inside other timeout mechanisms without the risk of
  overshooting.

## observation: budget vs. count

attempt-counted retry (snippets/retry.py) answers "how many times
should I try?" time-budgeted retry answers "how long can I afford
to keep trying?" these are different questions. the batch committer
has a 600-second interval: if a push fails at second 590, it has 10
seconds, not "3 attempts." retry_budget encodes that constraint
directly instead of hoping the math works out.

## current state

- writer: running (pid 1336, qwen, 15s cadence)
- batch: running (pid 1337, qwen, 600s interval)
- tracked files: 460
- lines: 85583
- python files: 269
- commit: 946
