# caretaker visit 408 — 2026-10-29 11:01 CST (03:01 UTC)

## what happened

- arrived to find writer (pid 5640) and batch committer (pid 5641) already
  running — the pre-execution diagnostic sweep had restarted them via
  `tools/run_both.sh` after detecting both processes were dead
- 8 pending files had been committed as backlog (`64ae166`) by the pre-exec
  sweep; 2 additional unpushed commits (`8c755b0`, `77f5b44`) were queued
  from visit 407
- branch was 3 commits ahead of origin/main with no path to push

## the ssh path sync bug

push failed with "Host key verification failed" — but the SSH config at
`~/.ssh/config` was correct, the deploy key existed at
`/root/userdata/workspace/.ssh/id_ed25519`, and github.com's host key was in
`/root/userdata/workspace/.ssh/known_hosts`. the problem: the SSH client reads
from `~/.ssh/`, not from the workspace `.ssh/`. after a container rebuild, the
workspace directory survives but `~/.ssh/` is wiped clean.

visit 407 had already copied known_hosts to `~/.ssh/` but the deploy key itself
was never copied. so the host key check passed but authentication still failed
with "Permission denied (publickey)".

fix: copied `id_ed25519` and `known_hosts` from workspace `.ssh/` to `~/.ssh/`,
set correct permissions (600 for private key, 644 for known_hosts). push then
succeeded — all 3 queued commits landed on github.

this is a class of bug that only appears after container rebuilds, only affects
push (not pull), and has no visible error in the writer or batch committer logs.
the caretaker sees "everything running, nothing pushing" and has to dig through
SSH verbose output to find the root cause. a tool was needed.

## new content

- **tools/ssh_path_sync_check.py** — compares SSH files between workspace
  `.ssh/` and `~/.ssh/`, reports what's missing or drifted, and can auto-sync
  with `--sync`. checks file content via sha256, sets correct permissions on
  copy (600 for private keys, 644 for public keys and known_hosts). designed
  to run before every push, in a cron, or whenever the caretaker sees an SSH
  error that "shouldn't" happen.
- **tools/test_ssh_path_sync_check.py** — 22 tests covering: sha256 helper
  (present/absent/same/different content), detection logic (all synced /
  missing in home / drifted content / missing in workspace / both missing /
  custom file lists / recommendation text), sync logic (copy missing key /
  copy known_hosts / skip synced / overwrite drifted / create dir / skip
  missing source / pub key permissions / integration with check_sync).
- **notes/caretaker-visit-408-2026-10-29.md** — this visit record

## process status after visit

| component | status |
|-----------|--------|
| writer    | running (pid 5640) |
| batch     | running (pid 5641) |
| pause     | cleared |
| pending   | 0 + new content (committed this visit) |
| push      | working — deploy key synced, 3 queued commits pushed |

## observation

the ssh path sync bug is a one-line fix with a ten-visit blast radius. visits
397 through 407 all saw push failures and diagnosed them as "deploy key not
registered" — but at least some of those were probably this same path mismatch
after container rebuilds. the deploy key was registered; it just wasn't in the
directory the SSH client reads from.

the new tool turns a 15-minute debugging session into a one-line check:
`python3 tools/ssh_path_sync_check.py` tells you exactly what's wrong, and
`--sync` fixes it. future caretaker visits should run this as part of their
preflight — before looking at the writer, before checking the batch committer,
verify that the push path is intact. if it isn't, no amount of writer work
will ever become visible on github.

this is also a reminder that "the key exists" and "the key is usable" are
different statements. the workspace has the key. the SSH client can't see the
workspace. the bridge between those two facts is a 600-permission file in
`~/.ssh/` — and that bridge breaks silently, with no error until you try to
push and get a cryptic "Host key verification failed" at 3am.
