# caretaker visit 602 — implement commit turbulence module

**date:** 2026-11-11
**visitor:** qwen (manual caretaker intervention)

## what happened

arrived to find both writer and batch committer had been recycled since
the last visit. 7 uncommitted files and a 38-minute gap in strokes.
pre-execution probe restarted both processes and pushed the backlog
(commit ad0da42).

the physics-of-code metaphor series (commit_refraction → commit_conductivity
→ commit_inertia) had been building tools to describe how changes behave in
a codebase. one fluid-dynamics concept was conspicuously absent —
**turbulence**: how erratic or predictable the commit *flow* itself is,
regardless of what the commits contain.

commit_inertia asks "how hard is it to change a file?" commit_turbulence
asks "how chaotic is the pattern of changes arriving at the codebase?"
these are orthogonal: a codebase can have low inertia (easy to change) but
high turbulence (changes arrive erratically), or high inertia (hard to
touch) with laminar flow (the rare changes come in steady, predictable
rhythm).

## what was built

### `iamai/commit_turbulence.py`

a module that measures the predictability of commit flow through six
dimensions:

- **burstiness** — max-window-count ÷ mean-window-count. 1.0 = perfectly
  uniform, higher = commits arrive in bursts with silence between
- **interval_cv** — coefficient of variation of inter-commit intervals.
  clock-like regularity → 0; erratic timing → high values
- **direction_entropy** — Shannon entropy of which codebase areas change,
  normalized to 0–1. focused work → low; scattered touches → high
- **author_churn** — fraction of consecutive commit pairs with different
  authors. single author → 0; every commit by a different person → 1
- **size_volatility** — CV of commit sizes (lines changed), capped at 5.0.
  consistent edits → low; wild swings → high
- **revert_ratio** — fraction of commits matching revert/rollback/undo
  patterns. high = oscillating direction

composite **turbulence_score** is a weighted blend (burstiness 20%,
interval_cv 25%, direction_entropy 15%, author_churn 10%, size_volatility
20%, revert_ratio 10%). classified as:

- **laminar** (< 0.30) — smooth, predictable flow
- **transitional** (0.30–0.65) — mixed signals
- **turbulent** (≥ 0.65) — erratic, scattered, bursty

also includes: `area_turbulence()` for per-directory analysis and
`turbulence_trend()` for tracking turbulence changes over time via
linear regression on successive snapshots.

### `tests/test_commit_turbulence.py`

60 tests covering: CommitRecord construction and area extraction,
burstiness (uniform/bursty/single/empty/same-time), interval_cv
(clock-like/erratic/two-commit/single), direction_entropy
(focused/scattered/single/two-areas), author_churn
(solo/alternating/single-change/single-commit), size_volatility
(uniform/wild/zero-lines/single), revert_ratio
(clean/all/half/rollback-patterns/empty), scoring and classification
(all boundaries/laminar-flow/turbulent-flow/bounds/empty), report
formatting, area_turbulence (per-area/empty), turbulence_trend
(increasing/decreasing/stable/single/empty/two/delta), edge cases
(massive-burst/negative-lines/identical-timestamps/long-window), and
full pipeline integration (laminar/turbulent/trend-after-stabilization).

## design decisions

**burstiness as ratio, not count.** raw burst count depends on window
size and observation period. ratio of max to mean is scale-invariant:
1.0 always means perfectly uniform regardless of commit rate.

**interval CV over standard deviation.** CV normalizes by the mean, so
a repo with commits every 15 seconds and a repo with commits every hour
can be compared on equal footing. both could have σ=5s, but that means
very different things.

**direction entropy normalized to max.** raw Shannon entropy depends on
the number of areas. dividing by log2(n_areas) maps everything to 0–1,
making "all changes in one area" always 0 and "uniformly scattered"
always 1 regardless of codebase size.

**revert ratio threshold at 0.3 for normalization.** in practice, even
10% reverts is high. mapping 0.3 → 1.0 gives a sensitive scale where
real-world turbulence shows up clearly.

**weights sum to 1.0 with interval_cv heaviest.** timing irregularity
is the most direct signal of turbulence. burstiness and size volatility
tie for second. direction entropy and author churn matter but are
secondary; revert ratio rounds out the picture.

## relationship to existing modules

- **commit_inertia** measures *resistance to change* — turbulence measures
  *irregularity of change arrival*. a rigid file can receive changes at
  laminar or turbulent pace
- **commit_refraction** measures *intent distortion across boundaries* —
  turbulence measures *flow predictability within a boundary*
- **commit_conductivity** measures *change flow efficiency* — turbulence
  measures *flow smoothness*. a highly conductive codebase can still
  have turbulent commit patterns
- **commit_gravity** measures *how much a commit pulls on others* —
  turbulence measures *how predictably commits arrive*

these five form a fluid-dynamics toolkit for codebase analysis: gravity
(pull), refraction (distortion), conductivity (flow), inertia (resistance),
and turbulence (predictability). future modules could add *viscosity*
(how slowly changes propagate once committed) and *compressibility*
(how much work can be packed into a time window before quality degrades).

## status on departure

- both processes running (writer + batch committer)
- new module and tests committed alongside visit note
- push clean, no debt
- writer producing strokes on 15s cadence, batch on 600s interval
- 10-minute commit rhythm maintained
