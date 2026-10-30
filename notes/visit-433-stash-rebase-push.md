# visit 433 — stash-rebase-push recovery without process kill

**when:** 2026-10-30 20:01 CST (Friday evening)
**what:** caretaker intervention after full stall + remote divergence

## diagnosis on arrival

both processes stopped. writer had been silent for 3005 seconds — more
than 2x its 15-second cadence. longest recorded gap was 4080s. eight
files of uncommitted backlog sat in the working tree. the pre-execution
trace committed the backlog (`40cfb12`), restarted both loops, and tried
to push. push was rejected: remote had advanced beyond the local HEAD.

## the recovery sequence

what visit 431 recommended was `tools/rebase_rescue.py` as the default
entry point. this time the caretaker did it by hand, which turned out to
be simpler than expected:

1. `git stash` — capture the writer's fresh strokes (produced in the
   seconds between restart and the recovery attempt)
2. `git pull --rebase origin main` — rebase the local catch-up commit
   on top of the remote's new HEAD. clean rebase, no conflicts.
3. `git stash pop` — this failed. the writer had already modified
   `data/writer_state.qwen.json` again, conflicting with the stashed
   version. so: drop the stash (the stashed changes were pre-rebase
   state that the rebase already superseded) and keep the current
   working tree changes.
4. `git push origin main` — accepted. `c08b3cb..11e0e58`.

total hands-on time: under two minutes. no process kills, no lock file
cleanup, no detached HEAD. the key difference from visit 431: the
batch committer hadn't started its own git operation yet, so there was
no index.lock race. timing mattered more than tooling.

## what `rebase_rescue.py` would have done differently

`rebase_rescue.py` stops both processes first, cleans lock files, then
does the stash-rebase-pop-push cycle. that's the right call when
processes are competing for `.git/`. this visit, the processes had
just been restarted and hadn't yet touched git, so the manual path
was clean. lesson: check whether processes are actually racing before
reaching for the heavy tool.

## the stash-pop hazard

the stash-pop failure is worth noting. when the writer is running, it
continuously modifies `data/writer_state.qwen.json`. stashing that file
and then popping it after a rebase that also touched it creates a
conflict that isn't really a conflict — it's just the writer being
faster than the recovery. dropping the stash is safe because the
rebase already incorporated the remote's changes, and the writer's
current state is more recent than anything in the stash.

rule of thumb: if stash-pop fails on `writer_state.qwen.json`, drop
the stash. the writer will regenerate whatever was in it.

## new tool: cadence_stall_detector.py

added `tools/cadence_stall_detector.py` — measures the time since the
last stroke and compares it against the expected cadence to determine
stall duration and severity.

exit codes:
- 0 — no stall (within 2x cadence)
- 1 — mild stall (2x–5x cadence gap)
- 2 — severe stall (>5x cadence gap)

the tool reads `data/strokes.jsonl` for the last stroke timestamp and
`data/writer_state.qwen.json` for the configured cadence. it outputs
a JSON summary suitable for cron consumption.

## observation

this is the third consecutive visit where the recovery pattern was:
commit backlog → restart → handle push rejection. the only variable is
how push rejection gets handled (manual vs. tool-assisted). at some
point, `commit_batch.py` should internalize the push-rejection path
and try `rebase_rescue.py` logic before reporting failure. until then,
the caretaker's job is to notice the rejection and run two commands.
