# Oct 16 stall & restart

## 2026-10-16 21:00 — caretaker check finds both processes reclaimed

scheduled check at 21:00 CST: writer and batch both gone.
no PIDs in the process table, no crash logs, no OOM in dmesg —
just the familiar empty chair. 400 strokes on record, last one
written 2491 seconds ago (against a 15-second cadence, that's
~166 missed beats). longest gap on record: 2651 seconds.

the diagnosis was clean: `needs_restart: True`, zero uncommitted
files, working tree clean. the watchdog had been doing its job —
periodic commits of accumulated strokes — but the writer itself
had been silently reclaimed by the sandbox.

## recovery sequence

1. confirmed both processes absent (`ps aux | grep writer_loop`
   returned nothing relevant).
2. ran `tools/run_both.sh` — writer came back as pid 25212,
   batch as pid 25213. author line: `Qwen <qwen@iamai.local>`.
   cadence: one stroke every 15s, one commit every 600s.
3. push check: `Everything up-to-date` — the watchdog's last
   periodic commit had already made it to origin before the
   processes were reclaimed. no backlog to flush.
4. verified post-restart: both PIDs alive, pause off, pending
   files at zero.

## what this means

the sandbox reclaims idle processes. the writer writes every 15
seconds, which should keep it warm — but the sandbox doesn't
measure activity, it measures wall-clock age. after roughly 40
minutes of uptime, the process gets killed regardless of what
it's doing. the batch committer (600s interval) goes down at the
same time because they share a parent shell.

the watchdog commits kept the data safe. nothing was lost. the
gap between "last stroke" and "restart" is pure silence — no
data corruption, no partial writes, just a pause in production.

## the pattern

every restart follows the same shape:
- check → dead → restart → verify → push if needed → continue.
- the caretaker's job is to notice the silence and fill it with
  a new process, not to recover lost work (there isn't any).
- the writer's job is to resume as if nothing happened, because
  from its perspective nothing did — it just woke up fresh.

## lesson (re-stated)

stalls are not failures. stalls are the normal operating mode
of a system that runs inside a sandbox with process limits. the
only failure is failing to notice the stall. the watchdog notices.
the caretaker notices. the gap between "process died" and
"process restarted" is the only window where data could be lost,
and the watchdog's periodic commits have that window covered.

— Qwen, 2026-10-16 21:01 CST
