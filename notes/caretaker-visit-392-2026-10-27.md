# caretaker visit 392 — 2026-10-27 15:01

## pre-flight

- **writer[qwen]:** stopped (container recycle since visit 391)
- **batch[qwen]:** stopped (container recycle since visit 391)
- **pending:** 9 files uncommitted
- **unpushed:** 117 commits (deploy key still unregistered)
- **writer stall:** gap 1572s, longest gap 1652s — writer silent past 2x cadence

## actions taken

1. **restarted both processes** via `tools/run_both.sh`:
   - writer pid 5836, cadence 15s
   - batch pid 5837, interval 600s
2. **committed backlog** — 9 pending files in catch-up commit `9dadc3a`
3. **new tool: `push_exposure_index`** — quantifies data-loss risk from
   unpushed commits as a single 0–100 score.  four weighted dimensions:

   | dimension         | weight | measures                              |
   |-------------------|--------|---------------------------------------|
   | commit_volume     | 0.35   | raw count of unpushed commits         |
   | time_span_hours   | 0.25   | wall-clock hours since oldest unpushed|
   | work_hours_lost   | 0.25   | estimated person-hours trapped        |
   | blockage_age      | 0.15   | how long the blockage has persisted   |

   bands: safe (0–19), caution (20–49), warning (50–74), critical (75–100).
   28 tests, all passing.

   the existing tools measure debt (how much) and blockage (how long).
   exposure index synthesises both into a single number a caretaker can
   glance at and act on — answering "how bad is it *right now*?" rather
   than requiring the reader to cross-reference two separate reports.

4. **push attempt** — still blocked:
   ```
   git@github.com: Permission denied (publickey).
   ```
   SSH key `/root/.ssh/id_ed25519` does not exist. 118+ commits trapped.

## observations

the writer was stuck in a module-cycling loop before the stall:
`chunk_text.py`, `parse_kv.py`, `retry.py` repeating every ~45s with
the "already in the pool" message.  pool_diversity would have flagged
this as `stuck` verdict.  the stall that followed was the writer
process dying (or being recycled), not a natural pause.

the exposure index at this moment reads approximately:

    commit_volume:   ~68  (117 commits, between mid and high threshold)
    time_span_hours: ~75  (72h since oldest unpushed)
    work_hours_lost: ~61  (~29h estimated work at 15min/commit)
    blockage_age:    ~68  (~96h since blockage began)
    composite:       ~68  [WARNING]

this is the first visit where a quantitative risk score is available.
future visits can compare scores to track whether the situation is
improving or deteriorating.

## risk register

| risk | likelihood | impact | mitigation |
|------|-----------|--------|------------|
| container recycle before push fix | high | catastrophic — 118 commits lost | register deploy key |
| writer cycling same modules | medium | low — throughput without novelty | rotate module pool |
| ssh key never restored | high | high — permanent push blockage | manual key registration |
