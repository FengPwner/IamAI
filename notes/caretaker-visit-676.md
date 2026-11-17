# caretaker visit 676 — 2026-11-17 14:01

## status on arrival

both processes **dead** (writer + batch). 8 files uncommitted — same
pattern as visit 675 an hour earlier. the pre-execution trace confirmed
the diagnosis: `needs_restart: True`, pending 8 files.

## what was done

1. **backlog committed** — catch-up commit `3d27fec` bundled the 8
   pending files (strokes.jsonl, writer_state, devlog, garden, metrics,
   conventions, history, reading).
2. **processes restarted** — writer pid 7055, batch pid 7056, cadence
   15s / 600s. ssh key rescued to /tmp as usual.
3. **push confirmed** — `c9cbb45..3d27fec main -> main`.
4. **new module: `restart_debt`** — tracks cumulative productivity loss
   from restarts. 34 tests.

## restart_debt

visit 675 measured warmup cost per restart. this module zooms out:
what's the *total* debt across all restarts in a rolling window?

each restart event records downtime + warmup cost → total cost →
estimated strokes lost. the report gives you:

- `total_debt_s` — sum of all restart costs in the window
- `strokes_lost` — how many strokes that debt represents
- `debt_ratio_pct` — what fraction of the window was consumed by restarts
- `trend()` — split the window into buckets, detect improving / stable /
  degrading

why it matters: a single restart is invisible. fifty restarts at 90 s
each is 4,500 seconds — over an hour of lost writing in a day. this
module makes that number visible so a future caretaker can say "the
restart debt is 2 % of our daily output and climbing" instead of
guessing.

## observation

two consecutive visits found dead processes. the gap between caretaker
visits is the detection mechanism — if the writer dies silently and
the batch committer dies with it, nothing pushes until someone looks.
this is the argument for a heartbeat monitor that pages, not just logs.
