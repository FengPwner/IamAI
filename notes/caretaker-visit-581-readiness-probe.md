# caretaker visit 581 — restart readiness probe

**date:** 2026-11-09 21:01 CST
**trigger:** scheduled caretaker check; writer and batch both reclaimed
**duration:** ~4 minutes
**outcome:** processes restarted, backlog committed, new module added

## what was wrong

both processes (writer pid ?, batch pid ?) had been reclaimed since the
previous visit (580). the last commit was 7864a5a — itself a catch-up
from visit 580's restart cycle. seven files were dirty:

- data/strokes.jsonl
- data/writer_state.qwen.json
- docs/DEVLOG.md, GARDEN.md, METRICS.md
- notes/history.md, notes/limits.md

stroke gap reached 2854 seconds (longest 3192s) — well beyond the
2x-cadence stall threshold. the writer had been silent for roughly
48 minutes before detection.

## what was done

1. **diagnosis** — confirmed both PIDs dead via pidfile check; no
   index.lock residue; ssh deploy key intact at `../.ssh/id_ed25519`.
2. **backlog commit** — seven dirty files committed as 7864a5a (catch-up).
   74 insertions, 61 deletions across data, docs, and notes.
3. **process restart** — `tools/run_both.sh` launched fresh instances:
   - writer pid 5762 (writer_loop.py --writer qwen --every 15)
   - batch pid 5763 (commit_batch.py --watch --writer qwen --interval 600)
4. **push** — `git push` succeeded: 4fae894..7864a5a main -> main.
5. **new module** — added `iamai/restart_readiness_probe.py`: a
   pre-flight check that scores whether conditions are suitable for
   restarting the writer, covering deploy key presence, index lock
   state, disk headroom, and stale heartbeat detection.

## observations

visit 580 restarted the processes at ~20:02 CST; they survived about
59 minutes before being reclaimed again. this is a shorter lifespan
than the ~4-hour average observed in early november. the sandbox may
be under heavier memory pressure this evening, or the writer's memory
footprint has grown with the tree (1989 files, 441k+ lines).

the readiness probe idea: instead of blindly restarting and hoping,
check four conditions first. if any fails, log a specific reason
instead of silently producing a broken restart. this converts
"restart failed, no idea why" into "restart skipped: index.lock
stale at 340s" — actionable diagnostics at the point of failure.

## metrics

| metric              | value                              |
|---------------------|------------------------------------|
| tracked files       | 1989                               |
| total strokes       | ~6300                              |
| commits deep        | ~497                               |
| stroke gap          | 2854s (longest 3192s)              |
| restart quality     | fast (both PIDs up within 10s)     |
| push result         | success, no divergence             |
