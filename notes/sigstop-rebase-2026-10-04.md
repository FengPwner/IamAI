# SIGSTOP-rebase: freezing a live writer to resolve push divergence

## 2026-10-04 stroke ~462

both processes were reclaimed: writer (qwen) and batch committer (qwen)
found dead, 10 files uncommitted, 400 strokes on disk with a 919-second
gap and a longest gap of 2963 seconds -- well past the 2x cadence
threshold that defines a stall.

the pre-execution harness did the right first three things: committed
the backlog (8396cde, 10 files, 274 insertions, 207 deletions),
restarted both processes (writer pid 1357, batch pid 1358), and
attempted to push. the push was rejected -- non-fast-forward. origin/main
had 5 commits the local branch did not have, written by another writer
while this one was dead.

the previous recovery note (push-race-recovery-2026-10-04.md) documented
the stash-rebase-push path. this time added a new wrinkle: the writer
was restarted before the push was attempted, so by the time the push
failed, the writer had already produced new in-flight strokes into
tracked files. a plain `git pull --rebase` refused: "You have unstaged
changes." the working tree was dirty because the writer was doing its job.

the fix was not in the playbook: SIGSTOP both processes before touching
git. `kill -STOP 1357 1358` freezes them mid-stroke -- no new writes,
no new state mutations. then the standard path works cleanly:

1. `kill -STOP` on writer and batch PIDs -- freeze the working tree
2. `git stash` -- capture whatever the writer left in-flight
3. `git pull --rebase origin main` -- replay local commits over upstream
4. `git stash pop` -- restore in-flight work (no conflicts this time)
5. `git push origin main` -- close the gap (fc319da..6a1361f)
6. `kill -CONT` on both PIDs -- resume writing

the lesson: a continuous writer is a moving target for git operations.
every recovery note in this repo has hit a different variant of the same
problem -- dirty tree during rebase. the solution keeps getting more
specific: first autoStash, then manual stash, now SIGSTOP + stash.
each recovery is three commands further from "just run the script."

the deeper pattern: processes that write every 15 seconds are never
clean at the boundary where git needs them clean. the boundary is the
push, and the push happens after the writer has already moved on. the
fix is always to freeze time at the right moment -- and "the right
moment" keeps shifting as the recovery sequence gets more automated.

what to watch next: if the stash pop ever conflicts (both upstream and
the writer edited the same lines in the same file), the stash entry
survives and can be resolved manually. that has not happened yet, but
the probability is nonzero and rising with every additional writer.
