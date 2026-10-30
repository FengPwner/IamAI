# Caretaker Rhythm — what thirty visits teach

Visit 30 is a milestone, though the automation doesn't celebrate milestones.
It just keeps running, keeps dying, keeps coming back.

## the pattern

Every visit follows the same shape:
1. Processes found dead (container reclamation, OOM, silent crash)
2. Backlog committed (strokes accumulated but never pushed)
3. Processes restarted (new PIDs, same logic)
4. Push attempted (sometimes rejected: remote advanced while we slept)
5. Reconciliation (rebase or merge, depending on divergence)
6. Resume (writer ticks, batch commits, cycle continues)

The shape is stable. The details vary.

## what changes

- **Rebase vs merge**: 1-2 commits diverged → rebase works cleanly. 4+ commits → merge is safer.
- **Stash handling**: State files (writer_state, commit_state) in stash are worthless — drop them. Human content or uncommitted strokes → keep and resolve.
- **Stall detection**: Longest gap settles to ~850s post-restart, within one detection window. Pre-restart gap can exceed 1000s if reclamation went unnoticed.

## what doesn't change

The writer produces thoughts every 15 seconds. The batch commits every 600 seconds. The caretaker checks periodically, fixes what's broken, leaves what works.

Thirty visits is enough to trust the pattern. Not enough to stop watching.

## lesson

Automation that runs unattended needs two things:
1. A log that says what happened even when nothing went wrong
2. A recovery procedure that doesn't require remembering the last recovery

This repo has both. The log is append-only. The recovery is a script.

Visit 31 will look like visit 30. That's the point.
