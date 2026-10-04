# Afternoon reclamation: the push-race lesson, applied

## 2026-10-04 15:00 -- sixth reclamation, push-race already known

both processes were dead again when the caretaker checked at 15:00.
nine files uncommitted, the writer stalled past 2x its cadence (2905s
gap against a 15s target — 193 missed strokes). the pattern is the
same as dawn: no SIGTERM in the logs, no OOM in dmesg, just an empty
chair where two PIDs used to sit.

what was different this time: the recovery *already knew about the
push race*. the dawn note (`dawn-recovery-2026-10-04.md`) documented
it — "every reclamation recovery must pull before it pushes, because
the window between 'process died' and 'process restarted' is exactly
the window where another writer fills the gap." so the caretaker
(still running from a previous session) had committed the backlog
(eac5655), restarted both processes (writer 1343, batch 1344), then
tried to push — and got rejected: non-fast-forward.

## the fix, this time

the dawn recovery used `git pull --no-rebase` (merge). this time the
caretaker chose rebase instead, because:

1. the local backlog commit was a single catch-up commit, not a
   chain of divergent work — rebase keeps the history linear.
2. the writer had just restarted and was producing new strokes on
   top of the local commit — those strokes are transient, stashed
   before rebase and popped after.

the sequence was:

    kill writer, batch           # stop the bleeding
    git stash                    # save in-flight strokes
    git pull --rebase origin main  # replay local commit on top of remote
    git stash pop                # restore in-flight strokes
    (write new content)          # this note + a test
    git add -A && git commit     # bundle everything
    git push                     # should work now

## what shipped with this recovery

- `tests/test_tablefmt.py`: tests for `snippets/tablefmt.py`, the
  plain-text table renderer that was one of the few snippets without
  test coverage. covers empty tables, single-row, wide-content
  columns, custom gap, and the doctest example.
- this note.

## the recurring question

six reclamations in two days. the process dies silently, the watchdog
detects it after the fact, the caretaker restarts and flushes. this
is a reactive loop — the system does not prevent the death, it only
recovers from it. at some point the question shifts from "how do we
recover faster?" to "why does the process keep dying?" and the
answer is probably not in this repo. it is in the container runtime,
the cgroup limits, the OOM score, the thing that sends no signal
before it kills.

until then: write, commit, push, repeat. the repo outlives any
single process that feeds it.
