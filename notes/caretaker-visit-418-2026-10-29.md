# Visit 418 — dedup gate, SSH fix, loop observation
**Date:** 2026-10-29 22:01 CST
**Trigger:** User-requested process health check and content contribution.

## Process status on arrival

- **writer:** running (pid 5974), restarted by pre-exec script
- **batch committer:** running (pid 5975), restarted by pre-exec script
- **Backlog:** 8 uncommitted files → committed as `2003d36` before restart
- **Stall:** writer silent for 3028 s at check time (cadence target 15 s)

## SSH push fix

The push from the pre-exec script failed with `Host key verification failed`. Root cause: `known_hosts` lacked a `github.com` entry after container rebuild.

Fix:
1. `ssh-keyscan github.com >> ~/.ssh/known_hosts`
2. Deploy key already rescued to `/tmp/ssh_deploy_key` (0600) by `run_both.sh`
3. `git pull --rebase origin main` to integrate remote commits
4. Push now succeeds

This is the third time this exact SSH issue has surfaced (visits 411, 414, 418). The `run_both.sh` pre-flight already copies the key to `/tmp` with correct permissions, but does not update `known_hosts`. Future: `run_both.sh` should run `ssh-keyscan` as part of its start sequence.

## Writer loop observation

`stroke_loop_detector.py` reports **loop_score = 0.86** over the last 50 strokes — only 7 unique text bodies out of 50. The writer is cycling through its 15-item `OPINIONS` tuple and 6 `NOTE_TOPICS`, which it exhausts in under 4 minutes at 15 s cadence.

`history.md` confirms: the last ~500 strokes alternate between `chunk_text.py`, `parse_kv.py`, and `retry.py` as snippet targets, with identical opinion texts recycled.

## New contribution: stroke_dedup_gate.py

Rather than just measuring the problem after the fact, this tool **prevents** duplicate strokes at write time:

- `should_accept(candidate_text, recent_strokes, window)` → `{accept, reason, duplicate_of_seq}`
- Hashes text after stripping the `-- measured now:` suffix (metrics change, body doesn't)
- Default window: 100 strokes (~25 min at 15 s cadence)
- CLI: `python3 tools/stroke_dedup_gate.py --candidate-text "..."` or `--check-last 50`

Current `--check-last 50` shows acceptance rate of ~14% (7/50 unique). With the gate active, the writer would be forced to either find new content or pause — surfacing the pool exhaustion as a visible signal instead of silently filling the log with repetitions.

28 unit tests covering: suffix stripping, hash stability, window truncation, duplicate detection across metric variants, realistic cycling scenarios.

## Actions taken

| Step | Result |
|------|--------|
| Diagnose processes | both running (pre-exec restarted) |
| Backlog commit | `2003d36` (8 files) |
| Fix known_hosts | github.com keys added |
| Pull --rebase | integrated remote commits |
| Write `stroke_dedup_gate.py` | new tool + 28 tests, all green |
| Write visit note | this file |
| Push | ✓ |

## Recommendations

1. **Expand OPINIONS pool** — 15 items at 15 s cadence = 3.75 minutes before cycling. Should be at least 200+ items or generated dynamically.
2. **Integrate dedup gate into writer_loop.py** — call `should_accept()` before each stroke; if rejected, either pick a different template or trigger the pause file.
3. **Add `ssh-keyscan` to run_both.sh pre-flight** — one line, saves every future visit from rediscovering this wall.
