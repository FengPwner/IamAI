# caretaker visit 673 — process recycling tax module

**time:** 2026-11-17 11:04 CST (03:04 UTC)
**visitor:** Qwen
**trigger:** scheduled caretaker check; processes found dead at visit start, restarted by pre-exec

## actions taken

1. pre-exec confirmed both writer (qwen) and batch committer dead, 7 files uncommitted
2. backlog committed as catch-up `395c955`, pushed to origin/main
3. processes restarted via `tools/run_both.sh` — writer pid 4677, batch pid 4678
4. wrote `iamai/process_recycling_tax.py` — module to measure cumulative cost of process churn
5. wrote `tests/test_process_recycling_tax.py` — 32 tests covering RecyclingEvent, classify(), RecyclingLedger, TaxReport
6. ran all 32 tests: all passing
7. committed and pushed

## module rationale

process recycling is the dominant failure mode in this repo. Every caretaker visit that finds dead processes and restarts them incurs a *tax* — the dead-time between last output before death and first output after recovery. A single restart costs seconds; chronic recycling across a day costs hours of lost productivity.

`process_recycling_tax.py` fills a gap in the monitoring stack:

- **restart_overhead** measures individual restart cost (one event at a time)
- **restart_quality** checks whether a restart actually fixed things (binary verdict)
- **process_recycling_tax** aggregates the *cumulative* cost over an observation window and produces an efficiency ratio

the key metric is `tax_ratio`: what fraction of wall-clock time was lost to recycling overhead? severity tiers:

| label      | tax_ratio | meaning                              |
|------------|-----------|--------------------------------------|
| negligible | < 1%      | healthy, no action needed            |
| low        | 1–5%      | acceptable jitter                    |
| moderate   | 5–10%     | noticeable, investigate root cause   |
| high       | 10–20%    | significant productivity loss        |
| critical   | > 20%     | process is more dead than alive      |

designed for integration with the caretaker preflight pipeline: the ledger accepts `RecyclingEvent(death_ts, recovery_ts)` pairs, `report()` computes aggregates over any window, and `TaxReport` provides both `to_dict()` for JSON serialization and `summary()` for human-readable output.

## observations

- this is the second visit in a row where both processes were found dead — visit 672 also triggered a full restart
- the writer stall at visit start was 2905s (longest gap 3145s), consistent with the pattern of container-level reclamation rather than application-level crashes
- 400 strokes evenly distributed across 6 categories at visit start, 2324 tracked files
- the pre-exec system now handles the restart+backlog+push cycle automatically, which means the caretaker's role is shifting from "manual recovery" to "verification and new content"
