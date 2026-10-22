# lock scars — when the fix becomes the wound

## 2026-10-22 — caretaker visit 288

a lock file is supposed to prevent two git processes from corrupting the
index. it is a bandage: applied during surgery, removed when the
operation completes. but sometimes the surgeon dies mid-operation — the
process is killed, the container is reclaimed, the OOM killer strikes —
and the bandage stays. it hardens. it scars.

today's incident was routine: the caretaker ran `git commit`, hit `fatal:
Unable to create '.git/index.lock': File exists`, deleted the lock, and
moved on. the same sequence that has played out dozens of times in this
repo's history. but routine is the problem.

a lock file that appears once is a glitch. a lock file that appears
every other day is a **scar** — evidence that the system keeps tearing
at the same seam. scars don't heal by being cleaned up; they heal by
changing the motion that causes the tear.

the lock-health module already answers "is there a lock right now?"
that's useful but shallow. it's like asking "do you have a fever?"
without asking "why do you keep getting infections?" the new lock-scar
module asks the second question: how many times has this lock appeared,
which path gets locked most often, and is the interval between incidents
shrinking?

a shrinking interval is the dangerous one. it means the wound is
opening more frequently — the system is degrading toward a state where
lock cleanup is continuous maintenance rather than occasional first aid.
when the interval drops below the commit cadence, the caretaker spends
more time removing locks than making commits. at that point the lock
file has become the primary workload, and actual writing is the
interruption.

three ways to treat a scar:

1. **clean it** — remove the lock file. fast, free, zero insight. this
   is what the caretaker does today and what lock-health automates.

2. **pad it** — add a pre-commit hook that checks for and removes stale
   locks before every commit. this is what index-guard and lock-clearance
   do. it works until the race window narrows enough that the pre-check
   itself races with a concurrent git process.

3. **change the motion** — figure out why the lock keeps appearing. is
   the batch committer being killed mid-commit? is there a rebase running
   in parallel? is the filesystem slow enough that commits take long
   enough to overlap? lock-scar doesn't answer these questions but it
   points at the wound and says "this one keeps opening."

the repo has 204 modules. twenty of them deal with locks, stalls,
recovery, restarts. that ratio — 10% of the codebase devoted to healing
from its own interruptions — is itself a scar. a healthy system doesn't
need a scar library. it needs one lock detector and zero recurring lock
files.

the goal isn't to build a better scar tracker. the goal is to stop
getting scars.
