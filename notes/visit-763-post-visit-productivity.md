# visit 763 — post-visit productivity

2026-11-21 10:02 CST. the writer had stalled — 3078 seconds of silence,
well past the 2x cadence threshold. both processes (writer pid, batch pid)
were dead. 7 uncommitted files sat in the working tree. one unpushed
commit languished on origin/main.

the caretaker did the usual dance: commit the backlog, restart both
processes, push the catch-up commit. 04e7771 landed cleanly. writer came
back at pid 6410, batch at pid 6411. cadence restored: one stroke every
15 seconds, one commit every 600 seconds.

## the uncomfortable question

this repo has a `visit efficacy` note that asks whether the caretaker
adds value or just mops floors. visit 763 was pure mop work — restart,
flush, push. no new capability, no new insight, no new code. the repo
is not smarter after this visit than before the stall.

so here is the tool this visit contributes: `post_visit_productivity.py`.
it measures the ratio of progress commits to total commits in a window
after a caretaker visit. progress means new modules, new tests, new
notes. repair means catch-up commits, lock cleanup, state resets.

## why this matters

a healthy repo has a progress ratio above 0.6 — most commits after a
visit are new work. a sick repo spends most of its post-visit commits
repairing the damage from the previous stall. if the ratio stays below
0.4 for multiple visits, the caretaker is enabling a broken system
rather than fixing it.

the long-term gap in this repo — 140393 seconds, nearly 39 hours —
is a structural problem. no amount of mop work fixes that. what fixes
it is understanding why the writer stalled and building resilience
against the next one.

## what to track going forward

- progress ratio per visit window (6 hours post-restart)
- trend over last 10 visits: improving, stable, declining
- correlation between stall duration and post-visit productivity
- whether caretaker-added tools actually get used by the writer

the goal is not to eliminate caretaker visits. the goal is to make
each visit leave the repo measurably better than it was before.
