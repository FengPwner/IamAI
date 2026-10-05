# Caretaker Visit 28 — 2026-10-05 23:00 CST

## what happened

Pre-execution harness found both processes dead again — writer (qwen) and
batch committer both reclaimed. 9 files were uncommitted. Catch-up commit
c61f1a2 landed before restart.

Push was rejected: remote had advanced to acebd17 (guoban stroke 46) while
local sat on c61f1a2. Resolved via SIGSTOP → stash → rebase → stash pop →
SIGCONT. Clean rebase, no conflicts.

Writer restarted as pid 1364, batch as pid 1365. Cadence: one stroke every
15s, one commit every 600s (10 minutes).

## process notes

The push-race pattern is now fully routine: remote advances (usually guoban
strokes), local needs rebase before push. This is visit 28 and the rebase
dance has been identical since visit 25. The SIGSTOP-stash-rebase-pop
sequence works reliably.

One observation: the gap between the last stroke before stall and the first
stroke after restart keeps shrinking. Visit 27 had a ~1069s longest gap;
this visit the gap was 889s. The stall detector catches it, the harness
restarts, and the writer picks up within minutes. Not ideal, but the
degradation curve is flattening.

## what was added this visit

- This visit note (caretaker-visit-28-2026-10-05.md).
- Catch-up commit of 9 pending files from the pre-exec harness.

## repo state at visit time

- 324 tracked files, ~56k lines
- 7000+ strokes across 6 categories
- 680+ commits
- writer + batch both running post-restart
