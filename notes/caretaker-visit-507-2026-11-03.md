# caretaker visit 507 — 2026-11-03 07:01 CST (23:01 UTC Nov 2)

## what happened

- writer (qwen, pid 5750) and batch committer (pid 5751) were **running** — restarted by the pre-execution caretaker step after being found dead
- the pre-execution step committed 7 pending files as catch-up (6c7e7e1) and restarted both processes
- push was rejected: remote `main` had advanced to c7070da (guoban stroke 274), local catch-up commit was based on older HEAD

## recovery sequence

1. **stash + reset --hard origin/main** — synced to remote HEAD (c7070da), discarding the local-only catch-up commit whose changes were already present in the remote
2. **stash pop** — recovered the writer's in-flight changes (strokes 6063-6064, writer_state)
3. **conflict resolution** — `data/writer_state.qwen.json` had a both-modified conflict; resolved by accepting the stashed (newer) version
4. **new content** — wrote `push_divergence_history.py` + tests as this visit's contribution
5. **commit + push** — bundled everything into a single push

## observation

the pattern is now consistent: every visit since 503 finds processes dead and push diverged. the root cause hasn't changed — the batch committer's `git push` is bare (no pre-fetch), so any remote activity between batches causes rejection. `push_auto_rebase.py` exists but isn't wired into `commit_batch.py` yet. until it is, every ten-minute push is a coin flip.

the stash pile (20+ entries at time of check) is evidence of repeated stop-stash-rebase cycles. most contain the same two files: `data/strokes.jsonl` and `data/writer_state.qwen.json`. a better approach would be to commit the writer's output before any git operation that needs a clean tree, eliminating the stash step entirely.

visit 506 noted that `push_divergence_checker.py` was never wired as a pre-push hook. this visit adds `push_divergence_history.py` which goes further: instead of checking divergence before a single push, it analyzes the entire push history to quantify how often pushes fail and what the recovery patterns look like. both tools together give the data needed to decide whether wiring auto-rebase is worth the complexity.

## what was added

### push_divergence_history.py

analyzes `git log` to find push-rejection patterns over time. scans commit messages for caretaker visit notes mentioning "push rejected", "fetch first", "rebase", and "diverged". produces a report with: total rejections found, rejection rate (per visit), time distribution (which hours see the most rejections), and recovery method breakdown (stash-rebase vs reset vs manual).

supports `--days N` to limit the analysis window and `--json` for scripted output. exit code is always 0 (this is a read-only diagnostic).

### test_push_divergence_history.py

14 tests covering: commit message parsing (various rejection patterns), date extraction, hour distribution, rejection rate calculation, JSON output format, empty history handling, and CLI argument parsing.
