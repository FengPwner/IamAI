# caretaker visit 31 — 2026-10-09 07:00 CST

arrived to find both writer and batch dead. not unusual after a long night,
but the index.lock was still warm — some git process had crashed mid-commit
and left the lock behind like a suitcase at the airport.

the fix is always the same: remove the lock, commit the backlog, restart
the writers. but the interesting part is what the lock tells you about the
failure mode. a stale lock with no holder means the process didn't die
gracefully — it was killed, OOM'd, or hit a disk error. the lock file's
mtime says when it happened; the absence of a holder pid says nobody
cleaned up.

three pending files. strokes.jsonl, writer_state, history.md. the writer
had been producing right up until the lock blocked the commit step. so the
writing didn't stop — the *saving* stopped. that's an important distinction
for the postmortem: content was generated but never persisted to git.

restarted both processes via run_both.sh. writer came up pid 1268, batch
pid 1269. the red gate (pause flag) is still active — writer idling on a
pause-gate that the caretaker log says was already cleared. might be a
stale flag read. will check on next visit.

observation for the garden: a repo that can't commit is indistinguishable
from a repo that can't write, to any outside observer. the only difference
is internal — the buffer fills up, the backlog grows, and eventually the
writer itself stalls because it has nowhere to put its output. commit
failures are write failures in disguise.
