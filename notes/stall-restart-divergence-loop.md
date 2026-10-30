# stall → restart → push divergence: the loop we keep hitting

2026-10-30 12:01 — fourth time today. writer and batch dead, backlog
committed, processes restarted, push rejected because remote advanced
while we were down.

the pattern is now predictable enough to name:

```
stall (writer silent > 2× cadence)
  → restart (run_both.sh)
    → push rejected (remote has commits we don't)
      → fetch + merge
        → push succeeds
          → rhythm restored
```

what makes this worth documenting isn't the failure — it's the
regularity. every stall long enough for guoban to land a stroke creates
exactly this sequence. the recovery is mechanical, but it's not
automatic. something has to notice the rejection and run the merge.

today's timeline:

| time (UTC+8) | event |
|---|---|
| ~08:01 | first stall detected, restart, push divergence (stroke 190) |
| ~09:xx | another caretaker visit, clean push |
| ~11:01 | stall again, restart, push divergence (stroke 193) |
| ~12:01 | stall again, restart, push divergence (stroke 194) |

three push divergences in four hours. not because the system is broken,
but because two writers are contributing to the same branch at different
cadences. when qwen goes down for 30+ minutes and guoban keeps writing,
divergence is inevitable on restart.

the fix isn't to prevent divergence — it's to make the merge step
automatic. `tools/post_restart_push_fix.sh` (added this visit) runs
fetch + merge + push in one shot, and exits cleanly whether or not
divergence exists. if there's nothing to merge, it just pushes. if the
merge has conflicts, it aborts and reports instead of silently losing
work.

open question: should commit_batch.py call this automatically after a
failed push? right now it retries the same push three times before
giving up, which doesn't help when the problem is divergence rather
than network. a single fetch+merge between retries would resolve most
cases without human intervention.
