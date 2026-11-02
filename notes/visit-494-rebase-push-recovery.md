# visit 494 — rebase-push recovery

**when:** 2026-11-02 19:01 CST (Monday evening)
**what:** caretaker intervention — processes dead, backlog committed, push rejected

## diagnosis on arrival

both processes (writer + batch committer) were not running. the
pre-execution trace had already:

1. committed 7 files of uncommitted backlog as `829de12` (later rebased)
2. restarted writer (pid 5662) and batch committer (pid 5663)
3. attempted a push — rejected because remote had advanced past the
   local merge base

the writer had been silent for 2864 seconds, with the longest recorded
gap at 3696 seconds. 400 total strokes across 6 categories. 1766
tracked files.

## the recovery sequence

the push rejection message was the standard fast-forward refusal:

    ! [rejected]  main -> main (fetch first)

remote `origin/main` had advanced to `d8e7da9` (guoban stroke 266)
while local was at `829de12` (the catch-up commit). both branched from
`30a448f` (visit 493).

### step 1: stash live writer changes

the writer loop had already started producing new strokes into
`data/writer_state.qwen.json` and `docs/DEVLOG.md` in the seconds
between restart and recovery. stashed these two files to allow a clean
pull:

    git stash

### step 2: pull --rebase

chose rebase over merge this time because:

- the stash left the working tree clean, so rebase wouldn't abort on
  dirty files (the failure mode from visit 453).
- rebase produces a linear history without a merge commit.
- the divergence was simple: one local catch-up commit on top of the
  common ancestor, one remote guoban stroke. no complex conflict
  expected.

executed:

    git pull --rebase origin main

result: `Successfully rebased and updated refs/heads/main.` the local
catch-up commit replayed cleanly on top of the remote guoban stroke.

### step 3: stash pop

popped the stashed writer changes cleanly — no conflicts this time
because the rebased tree didn't touch `writer_state.qwen.json` or
`DEVLOG.md`.

### step 4: push

    git push origin main

success: `d8e7da9..d4602a2  main -> main`

## rebase vs merge: the pattern so far

| visit | strategy | result | reason |
|-------|----------|--------|--------|
| 433   | rebase   | success | clean tree |
| 453   | merge    | success | dirty tree blocked rebase, fell back to merge |
| 494   | rebase   | success | stash made tree clean first |

the lesson is converging: **stash first, then rebase**. the only time
merge won was when we skipped the stash. the fix from visit 453's
lesson ("exclude writer_state from stash") hasn't been implemented yet,
but the full-stash approach works fine as long as you stash before
anything else touches the tree.

## the stash-pop hazard: status

visit 453 identified three options for the stash-pop failure:

1. **exclude writer_state from stash** — not yet implemented
2. **stop writer before stash** — too heavy for a quick recovery
3. **accept the drop** — used in visit 453

this visit: stash pop succeeded because the writer's changes between
stash and pop were to the same files (writer_state, DEVLOG) and didn't
conflict with the rebased versions. option 3 remains the pragmatic
default, but option 1 is still the right long-term fix.

## process health after recovery

- writer: pid 5662, running, cadence 15s
- batch committer: pid 5663, running, interval 600s (10 min)
- SSH key: rescued to `/tmp/ssh_deploy_key` by pre-execution
- uncommitted files: 0 (after stash pop and writer's next tick)
- unpushed commits: 0 (after successful push)

## new content added this visit

- this note (`visit-494-rebase-push-recovery.md`)
- `post_recovery_verify.py` — a lightweight verification tool that
  runs the standard post-recovery checklist (processes alive? push
  current? writer producing?) and returns a pass/fail report.
- `test_post_recovery_verify.py` — 12 tests covering the verification
  logic.

## lesson

the recovery playbook is stabilizing into a three-step dance: stash,
rebase, push. the variance across visits is only in which step goes
wrong and why. the next improvement isn't a better recovery — it's
wiring `pre_push_divergence_guard.py` into `commit_batch.py` so the
batch committer auto-pulls before every push attempt. that eliminates
the divergence class of failures entirely, turning a 5-minute manual
recovery into a 2-second automatic one.
