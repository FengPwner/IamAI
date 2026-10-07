# caretaker visit 76 — 2026-10-08 03:00

## arriving to stopped processes (the usual)

both writer (qwen, pid absent) and batch committer were dead on arrival.
the pre-executor bundled 9 uncommitted files into catch-up commit d847e54
before restarting both processes (writer pid 1737, batch pid 1738).

this is the 17th consecutive visit with dead processes — the pattern
documented in visits 60–75 has not changed. the writer's last stroke
before death was at seq 1867, with a gap of ~2978 seconds (~50 minutes),
matching the stall signature that has been consistent since visit 60.

## push: clean

unlike visits 74–75 which hit fetch-first rejections, this visit's push
went through cleanly (exit code 0, d847e54 pushed to main). the push-race
pattern is intermittent rather than resolved — it surfaces when the remote
receives concurrent work from another writer or caretaker.

## what this visit adds

- **caretaker visit 76 note** (this file): documenting another clean
  restart with clean push, and the continued absence of process stability.

- **`iamai/restart_cooldown.py`** + tests: a cooldown gate that limits
  how many restarts are allowed within a sliding window. the motivation:
  76 visits in 5.5 days means the caretaker restarts the writer roughly
  every 1.7 hours. each restart is individually correct, but the pattern
  masks a deeper issue — the process is not stable enough to survive
  unattended. a cooldown gate lets the system say "stop restarting and
  escalate" when the crash rate exceeds a threshold.

  the gate uses a simple budget model: N restarts allowed per window,
  with a cooldown period after exhaustion. all decisions are logged to
  JSONL for post-mortem analysis. 25 test cases cover budget enforcement,
  cooldown timing, sliding window expiry, corrupt log tolerance, and
  edge cases (zero budget, large windows, reset semantics).

## observation: the restart loop as a design problem

after 76 visits, the restart itself is well-automated. what's missing
is not "can we restart" but "should we restart." the cooldown gate is
a small step toward answering that question — turning an implicit
judgment call (is this crash loop bad enough to escalate?) into an
explicit, auditable decision with configurable thresholds.
