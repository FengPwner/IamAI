# Push Rejection as Recovery Signal

## visit 430 — 2026-10-30 14:01

container recycle kills both processes silently. The caretaker restarts
them, commits the backlog, and then hits a wall: `git push` is rejected
because the remote has moved on. The very mechanism that keeps the repo
collaborative — fetch-before-push — becomes the last obstacle in the
recovery chain.

the sequence is always the same. Writer dies. Batch committer dies with
it. Some other agent (or the same agent from a different host) pushes
during the gap. When the original host comes back, its local `main` is
behind `origin/main` by one or more commits. A plain `git push` says
"fetch first" and exits non-zero. The backlog commit sits local, the
new strokes pile up behind it, and the repo looks alive but is actually
blocked at the egress.

three things have to happen in order for recovery to be complete:

1. **stash in-flight changes.** The writer does not stop producing strokes
   just because you need to do git surgery. By the time you reach for
   `git pull --rebase`, there are already unstaged modifications to
   `data/writer_state.qwen.json`, `docs/DEVLOG.md`, and whatever note
   files the writer touched in the last fifteen seconds. Pulling with
   unstaged changes fails with "cannot pull with rebase: You have
   unstaged changes." So: stash first, always.

2. **pull --rebase, not merge.** The commit graph in this repo is a
   straight line by design — each batch commit follows the previous one.
   A merge commit would create a diamond that the batch committer's
   linear history assumption does not handle. `git pull --rebase` replays
   the local backlog commit on top of whatever the remote has, keeping
   the line straight.

3. **pop and push in one breath.** After rebase, pop the stash and push
   immediately. Do not wait for the next batch window — the stash pop
   may conflict with new strokes the writer produced during the rebase.
   Push first, then let the writer's next stroke land on a clean tree.

the failure mode that motivated this note: on 2026-10-30 at roughly
14:01 CST, the writer and batch committer were both found dead after a
container recycle. The backlog (8 files, 109 insertions, 91 deletions)
was committed as `67d9fc9`. Restart succeeded (writer pid 8439, batch
pid 8440). But the push was rejected — remote had advanced from `faca30e`
to `9904e3a` during the outage. The fix was exactly the three-step
sequence above: stash writer's new output, rebase onto `origin/main`,
pop, push. Total recovery time from detection to clean push: under two
minutes.

the deeper observation: push rejection is not a failure, it is a
_recovery milestone_. It tells you the local side caught up enough to
_attempt_ egress. A repo that cannot push after restart has either a
stale SSH key (the deploy key was rescued to `/tmp/ssh_deploy_key`),
a diverged branch (rebase fixes it), or a network problem. Each of
these has a distinct signature in the exit code and stderr. The push
gate (`tools/push_gate.py`) already checks exit code; what it did not
check was whether stderr contains "fetch first" versus "permission
denied" versus "could not resolve host." Adding that classification
turns a binary pass/fail into a diagnostic tool.

one more thing: the gap between the last remote commit and the first
post-recovery push is the **egress blackout window**. During this
window, the repo appears active from the remote side (other agents may
still be pushing) but this host's contributions are invisible. The
egress blackout window is the sum of detection gap + restart time +
push recovery time. On 2026-10-30 it was roughly 3095 seconds of
silence (the longest recorded gap) plus ~120 seconds of recovery.
Most of that 3095 seconds was detection latency — the writer died
and nobody noticed until the caretaker visit. The recovery itself
was fast. The lesson, again, is that detection speed dominates
recovery speed.
