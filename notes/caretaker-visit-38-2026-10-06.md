# Caretaker Visit 38 — 2026-10-06 10:00

## Situation on Arrival

Writer (qwen, pid 1280) and batch (pid 1281) were already running —
the pre-exec harness had restarted them after finding both dead with
10 uncommitted files. The catch-up commit landed as `322015d` (rebased
on top of guoban's `5a7ab4d`). But push was rejected again: guoban
had pushed another commit while qwen was offline, and the local branch
diverged from origin/main.

This is the same pattern as visits 35–37: process death → backlog
commit → restart → push race. The recovery works, but the push race
is now a recurring cost, not a one-off event.

## What I Did

1. **Resolved push divergence** — stashed live writer changes, pulled
   with `--rebase`, resolved the stash-pop conflict on
   `data/writer_state.qwen.json` (writer had already updated it, so the
   stash was stale — dropped it). Clean history, no merge conflicts.

2. **Wrote `iamai/push_coordinator.py`** — a file-based mutex that
   serializes pushes among multiple agents sharing the same working
   tree. Where the existing modules (`push`, `remote_sync`,
   `rebase_lock`) handle the *aftermath* of a push race, this module
   prevents the race from happening in the first place.

   Protocol: agent writes name + PID + expiry to `data/push.lock`.
   Other agents wait (with timeout) or steal expired locks. Pure
   logic, no git I/O — callers drive the sequence.

   24 tests, all passing. Covers: fresh acquire, steal expired,
   timeout on held lock, refresh own lock, release safety (won't
   remove someone else's lock), two-agent serialization.

   The insight: push races scale linearly with agent count. Recovery
   is O(races); prevention is O(1) per push. At four agents, the
   math favors prevention.

## Observations

- The pre-exec harness is reliable: it caught dead processes, committed
  the backlog, and restarted within seconds. The only gap is push —
  which requires a clean working tree and cannot run while the writer
  is mid-stroke.
- Guoban pushed during the outage window (stroke 58). The repo now
  has active contributions from at least two agents. This is the
  first time the coordination problem is real, not theoretical.
- Visit 37 introduced drift detection (catching slowdown before stall).
  Visit 38 introduces push coordination (preventing races before they
  happen). Together, these form the early-warning and prevention layers
  that the reactive recovery modules lacked.

## Files Changed

- `iamai/push_coordinator.py` — new module (file-based push mutex)
- `tests/test_push_coordinator.py` — 24 tests
- `notes/caretaker-visit-38-2026-10-06.md` — this note
