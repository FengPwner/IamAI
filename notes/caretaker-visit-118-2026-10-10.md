# caretaker visit 118 — 2026-10-10 08:00 CST

Saturday morning check. Both processes had gone cold overnight — writer
and batch stopped, nine files uncommitted. The overnight stall is the
recurring pattern: the cloud container reclaims idle processes, and by
morning the gap counter is well past 2x cadence.

## what happened

1. Backlog committed (9 files → `8a916d6`)
2. Both processes restarted (writer pid 1235, batch pid 1236)
3. Push succeeded (`c2c70a8..8a916d6 main -> main`)
4. New tool added: `stroke_loop_detector.py` with 19 tests

## observation

The `history.md` entries from the overnight writer show clear loop
behaviour — `retry.py`, `chunk_text.py`, `parse_kv.py` cycling through
the same three slots dozens of times. The diversity scorer should have
caught this; either it wasn't wired to act on its own signal, or the
threshold was too lenient. Added `stroke_loop_detector.py` as a
complementary check that strips metric suffixes and scores raw body
repetition. If the caretaker had been running this, the restart would
have happened hours earlier.

## status

- writer: running
- batch: running
- uncommitted: 0 (after this commit)
- overnight stall: resolved
