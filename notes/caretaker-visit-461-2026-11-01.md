# caretaker visit 461 — 2026-11-01 09:01 CST

## what happened

Writer and batch committer were both down again (container recycle or OOM).
Seven files uncommitted; remote had diverged with guoban stroke 232.
Stash list had grown to 10 entries — nine orphaned from failed pull cycles.

## what I did

1. Pre-exec confirmed both processes stopped, committed the 7-file backlog (`ee1f8aa`).
2. Restarted writer (pid 5658) and batch committer (pid 5659) via `run_both.sh`.
3. Push rejected — remote ahead by guoban stroke 232 (`9dd3be9`).
4. Stashed dirty tree, `git pull --rebase origin/main` — rebase succeeded.
5. Popped stash, pushed cleanly (`6a71fdc`).
6. Cleaned stash graveyard: dropped 9 orphaned entries, kept 1 active.
7. Wrote this note and `tools/stash_cleanup.py` — a one-shot orphan dropper.

## observation

The stash accumulation pattern keeps recurring: caretaker stashes before rebase,
rebase fails or conflicts, stash is never popped, next visit stashes again on top.
After 461 visits, 10 orphaned stash entries is mild but trending toward moderate.
`stash_cleanup.py` gives the caretaker a single command to reset the cycle:
drop all entries classified as "wip" older than stash@{2}, keep the freshest two.

## metrics at visit time

- 1683 tracked files
- 5960+ strokes logged
- 10 stash entries (9 orphaned WIP, 1 active)
- 148 commits deep
