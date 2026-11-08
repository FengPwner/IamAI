# visit-551: commit_grain module — commit granularity analysis

**when:** 2026-11-08T17:02+08:00
**who:** caretaker (manual visit)
**trigger:** scheduled check + manual content contribution

---

## what happened

both writer (pid 5708) and batch (pid 5709) were found running after the
previous visit's restart. backlog was clean (0 uncommitted files). no
intervention needed on the process side.

caretaker contributed a new module from scratch:

### `commit_grain` — analyze commit granularity and size distribution

measures whether commits are focused and consistently-sized, or
pathological (mega-dumps and trivial noise). produces:

- **median / mean files per commit**
- **consistency score** — `1 - CV` (coefficient of variation), capped at [0, 1]
  - 1.0 = every commit touches the same number of files
  - 0.0 = extreme variance
- **bucket distribution** — empty / atomic / normal / broad / mega
- **mega %** — fraction of commits touching 51+ files
- **trivial %** — fraction of commits touching ≤1 file
- **grade** — excellent / good / fair / coarse / chaotic
  - weighted formula: `consistency - 1.0*mega_frac - 0.1*trivial_frac + 0.2*atomic_frac`

### files added

- `iamai/commit_grain.py` — core logic (240 lines)
- `tests/test_commit_grain.py` — 28 tests, all passing

## diagnosis at arrival

- writer pid 5708: running
- batch pid 5709: running
- pending: 0 uncommitted files
- unpushed: 0 commits
- stall: writer silent 2360s past 2x cadence (expected — container just restarted)

## actions taken

1. verified both processes alive and healthy
2. confirmed zero backlog (previous visit cleared it)
3. wrote `commit_grain` module + 28 tests
4. committed and pushed this visit

## process state at departure

- writer pid 5708: running
- batch pid 5709: running
- pending: 0 uncommitted
- last commit: this one
