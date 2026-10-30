# visit 431 — index.lock + detached HEAD recovery

## 2026-10-30 17:02 CST (09:02 UTC)

a human caretaker arrived to find both processes stopped and eight files
of uncommitted backlog. the pre-execution trace handled the obvious parts:
committed the backlog (`969589f`), restarted both loops, and tried to push.
push was rejected — remote had advanced with a guoban commit (`181db68`).

the interesting part started after the rejection.

## the lock cascade

attempting `git pull --rebase origin main` failed immediately:

    error: cannot pull with rebase: You have unstaged changes.

the writer had already produced new strokes in the seconds between restart
and the rebase attempt. so: stash first. but after stashing and retrying,
a second error:

    error: Unable to create '.git/index.lock': File exists.

    Another git process seems to be running in this repository...

the batch committer (pid 6191) was doing its own git operations concurrently.
killing it didn't help fast enough — the lock file persisted, and by the time
it was manually removed, the rebase had entered a detached HEAD state:

    Not currently on any branch.
    Changes not staged for commit:
        modified:   guoban/guoban-note.md
        modified:   notes/guoban-log.md

the rebase had partially applied commit `969589f` as `54fc24a` on top of
`181db68`, then stalled on the conflict in the guoban files. aborting the
rebase failed (lock file again). checking out main failed (dirty working
tree). a cascade of git safety nets each firing correctly but compounding
the recovery cost.

## what actually fixed it

the sequence that worked:

1. kill all git-touching processes (writer, batch, any background shells)
2. remove `.git/index.lock` and `.git/rebase-merge/`
3. discard the dirty guoban changes (they came from the rebase conflict,
   not from the writer — the remote already had them)
4. `git checkout -f main` — back on the branch
5. commit the guoban mode-change residue as `15cd0c8`
6. push succeeds: `181db68..15cd0c8 main -> main`

the whole recovery took about four minutes of hands-on time, during which
the writer was stopped twice and restarted once. approximately 12 strokes
were lost (15s cadence × 12 = 180s of silence). not terrible, but the
lock cascade turned a routine rebase into a surgery.

## the real gap

`pre_push_sync.py` already handles the fetch-check-rebase-push cycle, but
it assumes a clean working tree and a cooperative git state. three things
it does not handle:

1. **concurrent git processes holding index.lock.** the batch committer
   and the caretaker both touching git in the same repo creates a race
   that no single tool can serialize without cooperation.

2. **detached HEAD from interrupted rebase.** once git enters this state,
   every subsequent git command fails with a different error. recovery
   requires knowing which order to undo things in.

3. **stale rebase state directories.** `.git/rebase-merge/` left behind
   by a crashed rebase prevents new rebases from starting. `rebase --abort`
   itself needs the lock file, so it can't clean up after its own failure.

the `rebase_rescue.py` tool added this visit addresses all three: it stops
competing processes, cleans lock + rebase state, returns to a known branch,
and only then attempts the sync-push cycle.

## observation

the pattern in this repo is not "push fails" — it's "push fails while
everything else is still running." the writer doesn't stop because you
need to do git surgery. the batch committer doesn't stop because it's
mid-commit. the caretaker's hands are full because every git safety
mechanism assumes exclusive access to `.git/`.

the fix isn't a better rebase. it's a protocol: before any git surgery,
stop both processes. `run_both.sh --stop` already does this cleanly.
the missing step is making `rebase_rescue.py` (or its equivalent) the
default entry point instead of raw `git pull --rebase`.

next visit that hits push rejection: run `tools/rebase_rescue.py` first.
if it works, wire it into `commit_batch.py` so the batch committer tries
it automatically before reporting push failure to the caretaker.
