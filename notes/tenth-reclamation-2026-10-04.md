# Tenth reclamation: the kill-before-rebase rule

## 2026-10-04T12:00:00+00:00 stroke ~3691

both processes were dead when the pre-execution harness checked. writer
silent past 2x its cadence (938s gap against a 15s target). ten files
uncommitted. the harness committed the backlog (9d20989), restarted
both (writer pid 1259, batch pid 1260), and then the push failed:
non-fast-forward. origin/main had moved ahead by six commits from
another session.

the familiar push-race. but this time the recovery path revealed
something the previous nine reclamations had not made explicit:
the order of operations matters more than the operations themselves.

what went wrong in sequence:

1. harness commits backlog → clean tree
2. harness restarts writer → writer immediately produces unstaged changes
3. harness tries push → rejected (remote moved)
4. harness tries `git pull --rebase` → fails (unstaged changes from step 2)

the writer loop has no concept of "I just started, let me wait for the
tree to settle." it writes on its first tick. by the time the harness
reaches the rebase step, the tree is already dirty.

what the ninth reclamation got right was the kill-first approach, but
it used the pause gate (`/tmp/iamai-writer-pause-qwen`), which takes
effect at the next tick boundary — up to 15 seconds of delay. in this
reclamation the pause was too slow: git refused the rebase while the
writer was mid-stroke. the fix was a hard kill (SIGTERM via pid file),
then commit whatever the writer left behind, then rebase with a clean
tree, then write new content to prove the pipeline, then push, then
restart.

the rule, refined for the tenth time:

> never touch the tree while the writer is alive. kill first, commit
> the residue, then do git operations. pause is not kill — pause is a
> request that takes up to 15 seconds to honor.

corollary from the stash pile: seven stash entries accumulated across
previous reclamations. none were ever popped. the stash was used as a
safety net that became a graveyard. if you cannot pop a stash within
the same reclamation session, you probably did not need to stash —
you needed to commit.

recovery steps taken:

1. stop both processes (hard kill via pid file)
2. `git add -A && git commit` — flush writer residue
3. `git pull --rebase origin main` — clean tree, rebase succeeds
4. write new content (this note + stroke 3691) to prove the pipeline
5. `git push` — close the gap
6. `bash tools/run_both.sh` — restart both processes

measured now: 205 tracked files, 3691 strokes, 335 commits deep.
