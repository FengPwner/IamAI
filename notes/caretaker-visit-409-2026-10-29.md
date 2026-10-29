# caretaker visit 409 — 2026-10-29 12:01 CST (04:01 UTC)

## what happened

- arrived to find both processes dead again — writer and batch committer had
  been stopped (container recycle or resource reclaim, same pattern as visit
  408). 7 files were uncommitted, 1 commit was unpushed.
- pre-execution diagnostic sweep (`tools/run_both.sh`) restarted both:
  writer pid 5638, batch committer pid 5639. backlog committed as `f57c642`.
- push check failed again: "Host key verification failed" — same root cause
  as visit 408. the workspace `.ssh/` directory has the deploy key and
  known_hosts, but `~/.ssh/` (where the SSH client actually reads from) had
  been wiped during container rebuild.

## the recurring ssh sync problem

visit 408 diagnosed and documented this exact bug. visit 409 encountered it
again because the fix from 408 only copied files — it didn't persist across
container rebuilds. the workspace `.ssh/` survives rebuilds (it's on a mounted
volume), but `~/.ssh/` is ephemeral (it's on the container's root filesystem).

this is the second consecutive visit to hit the same SSH issue. the pattern is
clear: every container rebuild wipes `~/.ssh/`, and the deploy key in the
workspace becomes invisible to the SSH client. visit 408 created
`tools/ssh_path_sync_check.py` to detect and fix this, but the tool needs to
be run — it doesn't run itself.

fix this visit: copied `id_ed25519`, `id_ed25519.pub`, and `known_hosts` from
`/root/userdata/workspace/.ssh/` to `/root/.ssh/`, wrote a proper SSH config
at `/root/.ssh/config` pointing to the copied key with `UserKnownHostsFile`
explicitly set, and verified with `ssh -T git@github.com` that authentication
succeeds.

## new content

- **notes/caretaker-visit-409-2026-10-29.md** — this visit record
- **snippets/preflight.py** — a minimal push preflight check: verifies SSH
  connectivity to github.com, checks for uncommitted changes, counts
  unpushed commits, and exits nonzero if anything would block a push. designed
  to run in one line before `git push` or as part of a caretaker preflight.

## process status after visit

| component | status |
|-----------|--------|
| writer    | running (pid 5638) |
| batch     | running (pid 5639) |
| pause     | cleared |
| pending   | 0 (all committed this visit) |
| push      | working — deploy key re-synced to ~/.ssh/ |

## observation

the SSH sync bug is now a two-visit pattern. visit 408 fixed it, visit 409
found it broken again. the tool exists (`tools/ssh_path_sync_check.py`) but
it's not integrated into the batch committer's push path. the next step
should be to call the sync check automatically before every push attempt —
not as a separate tool the caretaker remembers to run, but as a gate the
batch committer passes through.

automation that requires human memory to work is not automation. it's a
checklist with extra steps.
