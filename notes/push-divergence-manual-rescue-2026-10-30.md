# push divergence & manual rescue — 2026-10-30

the writer and batch processes had been recycled by the time this check
ran. eight files sat uncommitted on disk — the writer had kept producing
strokes but the batch committer was gone, so they piled up silently.

the catch-up commit went through locally, but push was rejected:
origin/main had advanced since the last sync. a classic divergence —
another agent (or a stale cron on another host) had pushed while this
host was offline.

the fix is mechanical: stash, pull --rebase, stash pop, then push.
but the writer keeps writing during the stash window, so you have to
pause it first (touch /tmp/iamai-writer-pause-qwen), otherwise new
strokes land between `git add` and `git stash` and the tree is dirty
again.

two things this incident reinforced:

1. **process death is silent.** the writer loop doesn't notice when the
   batch committer dies. it just keeps appending to strokes.jsonl. a
   deadman switch on uncommitted file count would have caught this hours
   earlier.

2. **push rejection cascades.** once origin diverges, every subsequent
   push attempt fails with the same error. the batch committer retries
   on its next cycle, hits the same wall, and gives up until the next
   interval. without an external check, the divergence persists
   indefinitely.

added push_recovery_time.py to measure exactly how long recovery takes —
from rejection timestamp to the next successful push. exit codes map to
severity: under 120s is healthy self-healing, 120–600s is slow but
acceptable, over 600s means a human had to step in.

the goal is not zero rejections — those are inevitable in a multi-host
push setup. the goal is short recovery time, and knowing when recovery
isn't happening on its own.
