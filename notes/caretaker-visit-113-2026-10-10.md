# caretaker visit 113 — 2026-10-10 01:00 CST (17:00 UTC)

## what happened

- writer and batch processes were both dead (recycled by the container scheduler)
- 9 pending files had accumulated uncommitted — committed as backlog (`bbefe8f`)
- `run_both.sh` restarted both (writer pid 1371, batch pid 1372)
- push succeeded on first attempt (no push race this visit)
- writer had been stalled for ~2983s (49.7 min) before detection — well past 2× cadence threshold

## new content

- **tools/commit_burst_detector.py** — CLI wrapper for `iamai.commit_burst_detector`. Reads git log, computes inter-commit gaps, and classifies burst patterns into four verdicts: quiet (zero bursts), steady (1-2 short bursts), surging (3+ bursts or a long one), panic (any burst with mean gap < 5s, indicating a retry loop). Configurable window, threshold, long-burst, and panic-gap parameters. Exit codes: 0 for healthy rhythm, 1 for surging/panic.
- **tests/test_commit_burst_detector_cli.py** — 20 tests covering: basic invocation (exit codes, verdict presence, window display), JSON output validation (required keys, burst dict structure), window override (custom/small values), threshold override (custom/zero/large values), verdict overrides (long-burst/panic-gap), edge cases (different cwd, positive commit count), and exit code semantics (quiet/steady → 0, surging/panic → 1).

## process status after visit

| component | status |
|-----------|--------|
| writer    | running (pid 1371) |
| batch     | running (pid 1372) |
| pause     | cleared |
| pending   | committing with this visit |
| push      | succeeded |

## observation

the 49.7-minute stall went undetected until this caretaker visit because the batch committer's watchdog only fires on commit freshness, not process liveness. The writer died, the batch kept running with nothing to commit, and nobody noticed until a caretaker checked PIDs.

the new commit_burst_detector fills a gap in the monitoring stack: existing tools measure stroke cadence (cadence_drift), commit age (commit_freshness), and gap classification (restart_audit), but nothing measures whether commits are arriving in healthy bursts or pathological ones. A repo with 100 commits in 10 minutes followed by 2 hours of silence looks "fresh" to commit_freshness but is clearly sick — commit_burst_detector catches exactly that pattern.

the "panic" verdict (mean gap < 5s) is particularly useful for detecting retry loops, where a failing operation generates rapid commits in quick succession. This has happened at least twice in this repo's history during push race recovery attempts.

next visit should: (1) wire commit_burst_detector into the batch committer's post-commit health check, (2) add a cron job that runs commit_burst_detector every hour and alerts on surging/panic, (3) investigate why the writer stalled for 49.7 minutes before the batch committer's own watchdog noticed.
