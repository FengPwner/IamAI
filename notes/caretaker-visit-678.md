# caretaker visit 678 — 2026-11-17 16:02

## status on arrival

both processes **dead** again. pre-execution trace confirmed:
`needs_restart: True`, 7 files uncommitted. visit 677's git_lock_monitor
hadn't been tested in production yet — the processes died before the
batch committer could exercise it.

the push from visit 677's backlog commit was rejected (remote had
advanced — doubao's hourly backstop at d78793b). rebase was needed
before anything could go upstream.

## what was done

1. **rebase on remote** — pulled with `--rebase`, rebased local
   `6f23bf3` on top of remote `c76b930`. clean, no conflicts.
2. **processes restarted** — writer pid 4629, batch pid 4630.
   pre-execution had already done this; confirmed running.
3. **new module: `restart_convergence`** — tracks how quickly the
   system recovers to full health after a restart. 28 tests.

## restart_convergence

visit 677 identified a three-layer failure chain (dead process →
stale lock → diverged branch). visit 678 asks: after we fix all
that, how do we know the system is *actually* healthy again?

`restart_convergence` measures the time from restart to three
milestones:

- **first_stroke** — the writer produces output. if this takes > 60s,
  the writer itself is stuck (not just the committer).
- **first_push** — the batch committer successfully pushes. if this
  takes > 660s (11 min), the push path is broken again — possibly
  the same divergence or credential issue that caused the original
  failure.
- **backlog_clear** — uncommitted files drop to zero. if this takes
  > 300s (5 min), the batch committer is struggling to catch up.

the tracker is stateless and idempotent. milestones can be marked
in any order. the `report()` method returns a structured dict with
health assessment against configurable thresholds.

### design choices

- **thresholds match IamAI cadence.** writer emits every 15s, batch
  commits every 600s. one cadence cycle for stroke, two for push.
- **idempotent marks.** the batch committer can call `mark_first_push()`
  on every push attempt — only the first sticks.
- **graceful partial convergence.** if push never happens, the report
  still returns useful data (which milestones were reached, how long
  elapsed) rather than failing.

### connection to visit 677

git_lock_monitor handles the *lock* half of the failure chain.
restart_convergence handles the *verification* half — did the restart
actually work? together they form a recovery sequence:

    1. git_lock_monitor: clean stale lock
    2. restart processes
    3. restart_convergence: track recovery milestones
    4. report healthy → caretaker can leave

## observation

the pattern across visits 676–678 is instructive:

- visit 676 added restart_debt tracking (measuring cumulative cost).
- visit 677 added git_lock_monitor (fixing the lock half).
- visit 678 added restart_convergence (verifying recovery).

each visit addressed a different layer of the same problem: processes
die and recovery is fragile. the modules are starting to compose into
a self-healing pipeline. the next logical step would be integrating
them into the batch committer's main loop — check lock, restart if
needed, track convergence, report health. that's a caretaker visit
for another day.
