# Caretaker Visit 25 — 2026-10-05 20:00 CST

## what happened

Pre-execution harness detected both processes down (writer + batch committer
reclaimed between visits 24 and 25). Stall gap was 938s — well past 2× the
15s cadence. Ten pending files committed as catch-up (ace8fb9), both processes
restarted (writer pid 1256, batch pid 1257), and push succeeded cleanly to
origin/main with no rebase conflict this time.

## what was added this visit

- `snippets/lease.py` — time-bounded exclusive lease for process coordination.
  Auto-expiring lock so a dead holder never blocks a live one. TTL-based,
  clock-injectable, supports renewal by the same holder.
- `tests/test_lease.py` — 15 tests covering acquire, reject, release,
  expiration, renewal, force-release, validation, and repr.
- This visit note.

## why a lease

The repo already uses pid files and a pause file for coordination, but those
are binary (held or not) with no expiry. A lease auto-releases when the holder
dies silently — exactly the failure mode that causes these container reclamations.
Next step would be integrating it into `commit_batch.py` so a dead writer's
in-flight strokes get picked up by the next writer without manual cleanup.

## process state after visit

- writer[qwen]: running pid 1256
- batch[qwen]: running pid 1257
- pause: no
- cadence: 15s stroke, 600s batch commit
