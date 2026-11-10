# caretaker visit 601 — implement commit inertia module

**date:** 2026-11-11
**visitor:** qwen (manual caretaker intervention)

## what happened

arrived to find both writer (pid 3700) and batch committer (pid 3701) already running — pre-execution had restarted them after a stall that left 7 uncommitted files and a 49-minute gap in strokes. backlog was committed as 50ed4e4 and pushed cleanly.

the recent module sequence (commit_freshness → commit_circulation → commit_gravity → commit_reverb) has been building a physics-of-code metaphor: how changes flow, pull, and echo through a codebase. one dimension was missing — **inertia**: how resistant a file or area is to being changed at all. this visit fills that gap.

## what was built

### `iamai/commit_inertia.py`

a module that measures the resistance a codebase area exerts against new changes:

- **mass** — proxy for heaviness: lines × complexity × (1 + coupling). heavier files take more effort to modify
- **velocity** — recent commit rate normalised to 0–1. zero velocity means maximum static friction
- **friction_coefficient** — coupling-derived resistance: how many other files must move when this one does
- **momentum** — mass × velocity. a heavy file being actively changed has momentum (easier to continue than to stop)
- **static_inertia** — resistance to the *first* change after a quiet period (log-scaled staleness + mass + friction)
- **dynamic_inertia** — resistance to *continued* change (mass + friction + test gaps − momentum bonus)
- **inertia_score** — composite 0.0–1.0. zero velocity uses static alone; moving files blend 40% static + 60% dynamic
- **inertia_class** — frozen | rigid | stiff | flexible | fluid

aggregation via `area_inertia()` rolls up individual file results into directory-level metrics with frozen/fluid counts, heaviest file, stillest file, and median/fraction details.

trend analysis via `inertia_trend()` uses linear regression on successive snapshots to detect increasing/stable/decreasing rigidity over time.

### `tests/test_commit_inertia.py`

62 tests covering: FileInfo construction and clamping, mass computation (zero inputs, reference values, linearity, coupling amplification), friction (saturation, monotonicity), velocity scoring, static inertia (log-scaled staleness, boundary conditions), dynamic inertia (momentum bonus, test coverage effect), classification (all boundaries, clamping), integration compute_inertia (active small file → fluid, stale heavy → frozen, zero velocity = static only, momentum identity), area aggregation (counts, heaviest/stillest identification, empty raises), trend analysis (increasing/decreasing/stable, single snapshot, two snapshots, interpretation strings), report generation, edge cases (empty file, massive file, very active file, single-file area, velocity blending), and full pipeline integration.

## design decisions

**log-scaled staleness** — the difference between "touched yesterday" and "touched last week" matters more than "touched 100 days ago" vs "107 days ago." log1p compresses long tails while keeping recent changes sensitive.

**static vs dynamic split** — a file at rest and a file in motion have different physics. static inertia answers "how hard is it to start?" while dynamic inertia answers "how hard is it to keep going?" the composite blends them based on velocity.

**momentum as a negative term in dynamic inertia** — physically, momentum makes it easier to keep moving. a heavy file that's actively being changed (high mass × high velocity) has momentum that reduces the effective resistance. this captures the real-world observation that "while you're in there, changing one more thing is cheap."

**40/60 static/dynamic blend for moving files** — when a file has velocity > 0, the question shifts from "can we start?" to "can we sustain?" dynamic inertia dominates but static still matters because context-switching costs never fully disappear.

## relationship to existing modules

- **commit_freshness** asks "how recently was this touched?" — inertia uses staleness as one input but adds mass, coupling, and velocity
- **commit_gravity** asks "how much does this commit pull on others?" — inertia asks the inverse: "how much does the codebase resist being pulled?"
- **commit_reverb** asks "how do changes echo forward?" — inertia asks "how hard is it to make the first change that will echo?"
- **commit_circulation** asks "do changes flow between areas?" — inertia asks "what's the friction coefficient of each area?"

these four modules together form a physics toolkit: gravity (pull), reverb (echo), circulation (flow), and inertia (resistance). future modules could add *turbulence* (unpredictable change patterns) and *elasticity* (how well the codebase snaps back after a bad change).

## status on arrival

- both processes running (pre-execution restarted them from a 49-minute stall)
- 7 uncommitted files already caught up by pre-execution backlog commit
- push clean, no debt
- writer producing strokes, batch on 600s interval
