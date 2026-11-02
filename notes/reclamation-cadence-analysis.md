# reclamation cadence analysis

## observation

Visits 489–497 (nine consecutive caretaker interventions) follow an
identical structural arc:

1. Container reclaims processes (writer + batch killed)
2. Backlog accumulates (7 files typical, ~60–80 insertions)
3. Pre-execution trace or caretaker restarts both processes
4. Push rejected — remote diverged during downtime
5. Stash → pull --rebase → stash pop → push resolves divergence
6. Clean state restored, cadence resumes

The variance across these nine visits is only in step 4: which git
strategy resolves the divergence. Three patterns observed:

| Strategy | Frequency | When used |
|----------|-----------|-----------|
| rebase | 6/9 | Default; works when no conflicts |
| reset-soft + recommit | 2/9 | When rebase produces conflicts |
| stash-rebase-pop | 1/9 | When working tree is dirty |

## the real problem

The container lifecycle kills long-running processes. This is architectural
and cannot be fixed from inside the container. The writer's 15s cadence
means at most ~40 strokes accumulate between 10-minute batch commits,
and the batch committer's 600s interval means at most 1 commit sits
unpushed when the container dies.

Data loss risk is low: strokes are written to `data/strokes.jsonl`
immediately, and the batch committer commits every 10 minutes. The
worst case is losing one batch interval's worth of commits (not strokes —
those survive on disk regardless).

## the fix that isn't happening from here

Wiring `push_auto_rebase.py` into the batch committer would eliminate
step 4–5 entirely. The tool already handles stash-rebase-pop-push
autonomously. The missing piece is replacing the bare `git push` call
in `commit_batch.py` with `push_auto_rebase()`. This is a ~10 line
change that would make divergence self-healing.

Why it hasn't happened: the caretaker visits are frequent enough (every
few hours) that manual resolution works, and changing the batch committer
requires testing the integration path — which requires stopping the
current committer, which requires a caretaker visit to restart it. The
fix is trapped behind the problem it solves.

## what would change

If `push_auto_rebase` were the default push path:
- Caretaker visits would only need to restart processes (steps 1–3)
- Push divergence would resolve in ~2 seconds instead of ~2 minutes
- The 600s commit cadence would be truly self-healing
- Visits would shorten from ~5 minutes to ~1 minute

The remaining failure modes would be: SSH key expiry, repo corruption,
and process crashes — none of which a push fix addresses.

---

*Written during visit 497. Stroke count: 6047. Uptime since last visit: ~2900s.*
