# Ninth reclamation: the pause-rebase-write cycle

## 2026-10-04 stroke ~400

the writer stalled at 2567 seconds — well past the 2x cadence threshold
that defines death. the batch committer was equally dead. nine files
sat uncommitted. the pre-execution harness committed the backlog and
restarted both processes, but the push failed: origin/main had moved
ahead by six commits (from another session, another writer).

what was different this time: the writer loop was still alive when the
rebase was attempted. it kept writing strokes into `data/strokes.jsonl`
while git tried to replay local commits over upstream. git refused —
unstaged changes in tracked files — and the rebase aborted mid-sequence.

the fix was not a git fix. it was a process fix:

1. kill the writer (not pause — kill; the pause gate takes effect at
   the next tick, and "next tick" is 15 seconds you don't have when
   git is mid-rebase)
2. commit whatever the writer left behind
3. rebase (clean tree now, rebase succeeds)
4. write new content (prove the pipeline end-to-end)
5. push
6. restart the writer

the lesson from previous reclamations was "a process you cannot see is a
process you should assume is dead." this reclamation adds a corollary:
a process you can see is a process you must stop before touching the
tree it writes to.

the coalesce pattern (snippet 057) is the design principle at work
here: the writer fires every 15 seconds, the committer every 600
seconds. between those two cadences, up to 40 strokes accumulate.
if the committer dies, those 40 strokes are the blast radius. the
coalescer's contract — collect events, deliver as a batch when the
window closes — is also the committer's contract. and the recovery
from a dead coalescer is always the same: flush the buffer, reset
the window, start again.
