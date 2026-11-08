# visit-550: tree_age module — file-age distribution analysis

**when:** 2026-11-08T16:02+08:00
**who:** caretaker (manual visit)
**trigger:** process restart + manual content contribution

---

## what happened

processes were found dead on arrival (container recycle). restart performed
via `tools/run_both.sh`, backlog committed (`6f5dc2a`), push succeeded.

after restart, wrote a new module from scratch:

### `tree_age` — file-age distribution across the repository

measures how fresh the tree is by computing last-modified timestamps for
every tracked file via `git log`. produces:

- **median/mean age** in days
- **stale count** — files untouched >30 days
- **cold count** — files untouched >7 days
- **decay score** — `0.6 * stale_fraction + 0.4 * cold_fraction`
  - 0.0 = everything touched today
  - 1.0 = everything ancient
- **health label** — fresh / healthy / aging / stale / rotting
- **trend** — decay score at each of the last N commits

### files added

- `iamai/tree_age.py` — core logic (260 lines)
- `tools/tree_age.py` — CLI wrapper
- `tests/test_tree_age.py` — 17 tests, all passing

### current reading

```
tree age: median 8.6d, 0.0% stale (>30d), decay 0.348 — healthy
1917 tracked files | stale: 0  cold: 1670
```

0% stale is expected — this repo rewrites most files frequently via the
automated writer's rotation. 87% cold (>7d) reflects the 3-day container
recycle gap (Nov 5 → Nov 8).

## diagnosis at arrival

- writer: dead (pid gone)
- batch: dead (pid gone)
- pending: 7 uncommitted files
- unpushed: 1 commit
- stall: writer silent 2708s past 2x cadence

## actions taken

1. committed pending backlog (`6f5dc2a`)
2. restarted both processes via `run_both.sh`
3. verified push succeeded
4. wrote `tree_age` module + tests
5. committed and pushed this visit

## process state at departure

- writer pid 3408: running
- batch pid 3409: running
- pending: 0 uncommitted
- last commit: this one
