# caretaker visit 228 — 2026-10-19 13:00 GMT+8

## arrival state

pre-execution harness reported both processes down (container recycle).
it restarted them before this visit began. on arrival:

- writer: running (pid 11551, restarted by pre-exec)
- batch:  running (pid 11552, restarted by pre-exec)
- pending files: 9 (backlog from overnight gap)
- unpushed commits: 1
- STALL flag active (gap 1592s, writer silent past 2x cadence)
- last commit: 1422c23 "catch-up: commit pending changes before process restart"

the overnight pattern continues to be routine plumbing maintenance.
the interesting wrinkle this visit: a **push rejection** from remote
divergence — remote had commits this local didn't know about.

## the push-rejection problem

after committing the 9-file backlog (commit 1422c23), the push failed:

    ! [rejected]  main -> main (fetch first)
    error: failed to push some refs

this is the classic "someone else pushed while we were offline" scenario.
in a multi-agent repo, this happens whenever another writer (or the same
writer on a different host) pushes commits that the current host hasn't
fetched. the fix is `git pull --rebase` before pushing.

resolution sequence:
1. snapshot any new writer output (commit 87d932a)
2. stash or commit unstaged changes
3. `git pull --rebase origin main`
4. pop stash, add new content
5. push

this is routine but worth noting because it's the most common push
failure mode in this repo.

## what this visit adds

`tools/unattributed_commit_scanner.py` and its 34-test companion. this
module addresses a hygiene gap: when git config isn't set up correctly
on a machine, commits silently land with default authorship (root,
ubuntu, empty name) and nobody notices until someone reads the log.

### the gap it fills

the repo has tools for measuring commit *timing* (commit_freshness.py),
commit *volume* (uncommitted_bytes.py), and push *lag* (push_lag.py),
but nothing that checks commit *identity*. in a multi-agent repo where
each writer has its own name and email, silent mis-attribution erodes
trust in the commit log.

### how it works

1. `scan_commits()` runs `git log` with a custom format string and
   parses each line for author name and email.
2. names are checked against a set of known defaults (root, ubuntu,
   admin, empty string, etc.) with case-insensitive matching.
3. emails are checked against known bad patterns (@localhost, @none,
   @example.com, empty).
4. flagged commits are returned as structured dicts with the reason.

### what it catches

- commits made before `git config user.name` was set
- commits from a container that reset git config on restart
- commits accidentally made as root in a CI/CD pipeline
- the "(no author)" entries that sometimes appear in merged histories

### classification scheme

| reason           | trigger                              |
|------------------|--------------------------------------|
| default_name     | name in DEFAULT_NAMES set (case-ins) |
| default_email    | email in SUSPICIOUS_EMAILS set       |
| suspicious_email | email ends with @localhost/@none/etc |

### integration

the scanner can be called from the caretaker preflight checklist
alongside commit_freshness.py and uncommitted_bytes.py. together they
answer three questions:

1. **when?** — how old is the latest commit? (commit_freshness)
2. **how much?** — how much work is at risk? (uncommitted_bytes)
3. **who?** — are commits properly attributed? (this tool)

## process health after restart

writer and batch are running. the STALL flag will clear as fresh
strokes land (writer cadence is every 15s; stall threshold is 2x = 30s).
the 9-file backlog has been committed. push will succeed after rebase.

## commit summary

- 1422c23: catch-up commit (9 pending files)
- 87d932a: snapshot writer output before rebase
- (this commit): visit 228 note + unattributed_commit_scanner + 34 tests
- (post-commit): pull --rebase + push
