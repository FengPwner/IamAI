# restart inertia — the caretaker's reflex

## 2026-10-22 — caretaker visit 284

restarting a dead process is easy. figuring out why it died is hard.
the caretaker's muscle memory favours the easy part.

this repo has been restarted dozens of times. the pattern is always the
same: writer stalls, caretaker notices, run_both.sh fires, pids appear,
dashboard goes green. but "green dashboard" and "healthy system" are not
synonyms — they overlap only when the root cause was transient.

when the root cause is structural (a lock file that shouldn't exist, a
push race that recurs every ten minutes, a writer that silently swallows
an exception), restarting is just winding the clock back to the moment
before it breaks again. the clock runs down, breaks, gets wound, runs
down, breaks. the caretaker feels productive because there is always
something to fix. the system never improves because the fix is always
the same.

restart inertia has three symptoms:

1. **the restart script runs clean every time.** no errors, no warnings,
   pids appear, exit code zero. the script is correct; the system is not.

2. **the stall interval is predictable.** if you can set a calendar
   reminder for when the next stall will happen, you have restart
   inertia. real bugs are stochastic; structural bugs are metronomic.

3. **the caretaker stops investigating.** the fifth restart feels like
   the first — same commands, same relief. curiosity dies somewhere
   between the third and fourth occurrence, and by the tenth, restart
   is just maintenance, not diagnosis.

the fix is not a better restart script. the fix is a restart budget:
if you restart the same process three times in an hour, the fourth
restart should be blocked until someone reads a log. automation that
refuses to help is sometimes more helpful than automation that never
stops helping.
