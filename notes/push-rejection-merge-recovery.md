# push rejection → merge → push recovery

2026-10-30 11:01 — processes were dead, backlog committed, restart done,
but push failed: remote had a commit we didn't have.

the sequence:

1. writer and batch both stopped (container recycle or OOM, unclear)
2. 7 files uncommitted → catch-up commit c507847
3. processes restarted (writer pid 6055, batch pid 6056)
4. push rejected — remote had 1061062 (stroke 193) ahead of our 4be295d
5. fetch + merge -X theirs → clean merge, no manual conflict resolution
6. stash pop failed (writer already modifying state file) → dropped stale stash
7. final push pending

this is the third variant of push-blockage in this repo:

| variant | cause | fix |
|---------|-------|-----|
| push debt | ssh key expired / missing | restore key, push |
| push race | two writers commit simultaneously | rebase, force-push or merge |
| push rejection | remote ahead of local | fetch + merge, then push |

the interesting thing about push rejection is that it's the healthiest
of the three. It means the remote is alive and advancing — the blockage
is purely local lag. The fix is mechanical: pull, merge, push. No data
loss, no conflict, just catching up.

the real risk isn't the rejection itself. It's the window between
rejection and resolution where the writer keeps generating strokes
that can't be pushed. If the merge had conflicts that needed manual
resolution, those strokes would pile up in the working tree, invisible
to the remote, potentially lost on the next container recycle.

lesson: after any push rejection, resolve it before the next commit
batch fires. A ten-minute commit cadence gives you exactly one chance
to fix it before the backlog grows.
