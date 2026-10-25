# caretaker visit 207 — commit density

## 2026-10-18T16:00+08:00

arrived to find both writer and batch dead. the index.lock was stale —
some earlier git process had crashed without cleaning up. removed it,
committed the 9 pending files, and restarted both processes.

the stall report showed 1525 s of writer silence with a longest gap
of 1644 s. that's nearly 28 minutes of nothing from a process that
should produce a stroke every 15 seconds. the process had a pid but
no output — the exact failure mode the restart_quality module was
designed to catch.

## what i built

commit_density — a module that scores each commit by how much real
content change it carries. the formula is simple:

    raw = insertions + deletions
    useful = max(0, raw - noise_floor)
    density = useful / raw

a commit that changes exactly 2 lines (a timestamp bump, a counter
increment) scores 0.0. a commit that adds 50 lines of new code
scores 0.96. the aggregate label tells you whether the repo is
mostly doing real work (dense) or mostly churning (hollow).

why this matters: a repo with 1550+ commits sounds productive, but
if half of them only update a counter or reformat a JSON file, the
actual velocity is half what the commit count suggests. density
makes that visible.

## status at departure

- writer: running (restarted)
- batch: running (restarted)
- backlog: cleared (9 files committed)
- index.lock: removed
- new module: commit_density with 36 tests
- push: clean

the machine hums again. next caretaker should check whether the
density of recent commits is improving or whether the writer has
settled into another counter-bump loop.
