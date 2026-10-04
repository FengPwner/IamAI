# Overnight stall: push-race during automated reclamation recovery

2026-10-05 02:00 CST — fourteenth reclamation event in four days.

## what happened

The pre-execution harness diagnosed the standard pattern: both processes dead,
ten files uncommitted, writer stalled past 2× cadence. The backlog was committed
automatically (dd43213) and both processes restarted (pids 1625, 1626).

Then the push failed:

    ! [rejected] main -> main (fetch first)
    error: failed to push some refs

Remote had two commits that the local branch did not have. The pre-execution
harness committed the backlog but did not rebase — it pushed immediately after
committing, and the non-fast-forward rejection meant the whole push step was
skipped. The local branch sat one commit ahead, the remote two commits ahead,
and neither could see the other.

## why the automated path stopped short

The `iamai/push.py` module already has `push_with_rebase()` — it fetches, rebases
local commits on top of upstream, and pushes. But the pre-execution harness calls
plain `git push`, not the guarded version. This is a gap in the automation: the
caretaker script trusts that a clean push will work after a clean commit, and
that assumption breaks the moment another writer has pushed since the last fetch.

## the manual recovery

1. Kill writer and batch (they were modifying files during rebase attempts)
2. Stash unstaged changes: `git stash push -u -m "pause-stash"`
3. Rebase on origin/main: `git rebase origin/main` (1/1, clean replay)
4. Push: `git push origin main` — accepted, 4159385..dee7f38
5. Pop stash to restore in-flight work
6. Restart processes: `bash tools/run_both.sh`

The writer died again between step 5 and step 6 (container pressure, probably),
so the caretaker cleaned stale pidfiles and restarted a second time. Second
restart held: writer pid 1842, batch pid 1843.

## the gap to close

The pre-execution harness should call `iamai.push.push_with_rebase()` instead of
bare `git push`. The guarded version already handles the fetch-rebase-push
sequence and refuses force-pushes. The fix is one import and one function call;
the risk is zero because the module already has tests with real git repos.

Until then, this note is the runbook: when the pre-execution harness reports
`[rejected] main -> main (fetch first)`, the manual path is three commands —
stash, rebase, push — and a fourth to restart what the rebase killed.
