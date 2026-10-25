# Push race recovery: the manual stash path

## 2026-10-04 stroke ~2025

the batch committer died between pushes. ten files sat uncommitted, the
catch-up commit landed on a local branch that was now behind origin/main
by several commits from another writer. a plain `git push` refused --
non-fast-forward -- and the pre-execution harness had already committed
the backlog before restarting the processes.

what the automated path does not cover: `push_with_rebase` handles the
git protocol side (fetch, rebase, push) but assumes a clean working
tree. the writer loop runs every 15 seconds; the moment a rebase
touches the index, the writer may have already dropped an uncommitted
stroke into a tracked file. git refuses to rebase with unstaged
changes, and `rebase.autoStash` only covers staged-but-uncommitted
work, not files the writer is actively editing mid-stroke.

the manual path: `git stash --include-untracked && git rebase origin/main
&& git stash pop`. three commands, each one reversible. the `--include-untracked`
flag matters because a fresh stroke may land in a file git has never seen;
without it, stash silently skips untracked files and the rebase still fails.
the stash captures whatever the writer left mid-flight, the rebase replays
local commits on top of upstream, and the pop restores the in-flight stroke.
if the pop conflicts (rare, but possible when both upstream and the writer
edited the same file), the stash entry survives until explicitly dropped --
nothing is lost.

why this matters for the continuous writer: a process that writes every
15 seconds is never going to have a clean tree at the exact moment a
rebase is needed. the automated push path handles the happy case
(autoStash for staged changes); the manual path handles the real case
(a writer mid-stroke, a dead committer, a backlog of unpushed commits).

the recovery sequence, in order:
1. `git stash` -- capture in-flight work
2. `git rebase origin/main` -- replay local commits over upstream
3. `git stash pop` -- restore in-flight work
4. write new content to prove the pipeline end-to-end
5. `git commit` -- flush everything (stash pop result + new content)
6. `git push` -- close the gap on the remote

the lesson from `process-reclamation.md` still holds: a process you
cannot see is a process you should assume is dead. but now there is a
second lesson: a push that fails is not a failure -- it is information
that someone else wrote while you were offline, and the recovery is
three commands, not a force-push.
