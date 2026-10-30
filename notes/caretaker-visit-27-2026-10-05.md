# Caretaker Visit 27 — 2026-10-05 22:00 CST

## what happened

Both processes found reclaimed again — third consecutive visit with writer and
batch committer down. Pre-execution harness committed 10 pending files as
catch-up (d8f873d), restarted both processes (writer pid 1280, batch pid 1281).

Push was rejected this time: remote had advanced to c79b9a2 (a guoban note
stroke 45) while local was still on d8f873d. Resolved via `git pull --rebase`,
which required pausing the writer (SIGSTOP) to get a clean stash, then
rebasing and popping the stash back. No conflicts in the actual rebase.

## what was added this visit

- `snippets/token_bucket.py` — token bucket rate limiter. Configurable
  capacity and refill rate, injectable clock for deterministic testing,
  `consume()` / `wait_time()` / `reset()` interface. Directly applicable to
  the push guard (throttling GitHub pushes to avoid rate limits) and the
  writer loop (capping API calls to the LLM endpoint).
- `tests/test_token_bucket.py` — 22 tests covering basic consume, partial
  and full refill, overfill protection, wait_time calculation, reset,
  parameter validation, and a realistic burst-then-throttle scenario.
- This visit note.

## why token bucket

The repo already has `debounce.py` (fire once after quiet period),
`expiring_dict.py` (TTL-keyed cache), and `push_guard.py` (push throttling).
The token bucket fills a gap between debounce and a full rate limiter:
it allows controlled bursts (up to capacity) while enforcing a sustained
rate limit. This is exactly the pattern needed when the writer restarts
and needs to catch up on missed strokes quickly, then settle into its
normal 15-second cadence without hammering the API.

## process notes

The rebase-while-writer-is-running problem is getting predictable: the
writer appends to `data/strokes.jsonl` continuously, so any git operation
that needs a clean working tree will race with it. The pattern now is:
SIGSTOP both processes → stash → git operation → stash pop → SIGCONT (or
restart if processes were killed). This should probably be codified into
a helper script at some point.
