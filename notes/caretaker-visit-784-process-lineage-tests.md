# visit 784 — closing the last test gap: process_lineage

2026-11-22 09:02 CST. morning caretaker check. writer and batch both
dead on arrival after overnight stall (gap 2640s → classified as stall).
7 uncommitted files from the previous session. backlog flushed as
commit f43568e, both processes restarted (writer pid 6362, batch pid
6363). push confirmed to main.

## what this visit adds

`process_lineage.py` was the last module in `iamai/` without a single
test. that is a meaningful gap: this module is the structural memory
for restart chains. every other restart-related module (restart_cost,
restart_latency, restart_debt) treats restarts as scalar events;
`process_lineage` is the only one that models them as a *graph* —
parent → child PID chains with cause-of-death attribution.

if this module silently corrupts (e.g., ancestor walk returns wrong
chain, lifespan aggregation skips generations), every downstream
restart metric inherits the error. the caretaker would see plausible
but wrong numbers.

`test_process_lineage.py` adds 39 tests across eight areas:

1. **Generation dataclass** — lifespan calculation for alive/dead/zero
   cases, is_alive predicate, to_dict serialization with ISO timestamps
   and None field handling.

2. **Basic operations** — empty tree edge cases (depth 0, current_pid
   None), add single/multiple, repr smoke test.

3. **is_orphaned** — the key invariant: a single generation is never
   orphaned; a chain with a missing parent link is. tested with empty,
   single, linked, broken, and deep chains.

4. **ancestors** — PID chain traversal from leaf to root. edge cases:
   root has no ancestors, unknown PID returns empty, broken chain stops
   at the gap (parent_pid=None).

5. **lifespan aggregation** — total and average lifespan, correct
   exclusion of still-alive generations, None return when all alive
   or empty.

6. **restart_causes** — counting by cause, None causes excluded, all-None
   returns empty dict.

7. **serialization** — to_list produces correct dict structure with
   ISO format timestamps.

8. **integration** — realistic 3-generation scenario mirroring the
   actual overnight pattern: container recycle → OOM → caretaker
   restart. verifies depth, current_pid, orphan status, ancestor
   chain, lifespan math, cause distribution, and serialization in one
   end-to-end pass.

## why this matters now

the repo just crossed 783 visits and 400+ strokes per kind. at this
scale, restart lineage is the primary signal for container lifecycle
health. visit 782's overnight stall showed a gap of 3269s — the
lineage tree would record that as a single generation with cause
"container" and a lifespan of ~4 hours before death. without tests,
we cannot be sure the tree is recording this correctly. now we can.
