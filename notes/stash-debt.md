# stash debt is process debt

## stroke 401

git stash is a temporary parking lot. That is the entire point — you
stash because something urgent needs a clean tree, and you pop when
the urgent thing is done. The word "temporary" is doing all the work.

today's caretaker visit found 36 stash entries. thirty-six. The oldest
one predates the current moon phase. Most of them are WIP snapshots
from pull-before-push sequences that were never popped because the
automation that created them was recycled before the pop step ran.

this is not a git problem. It is a process lifecycle problem. The
stash accumulated because:

1. the caretaker stashes before pulling (correct)
2. the pull succeeds and the rebase lands (correct)
3. the stash pop fails because the writer modified the same file
   between stash and pop (a race condition)
4. the caretaker logs the error and moves on (the stash stays)
5. next visit repeats from step 1 with one more orphan in the list

the fix is not ``git stash clear``. That is a garbage collector, not
a solution. The fix is either:

- **pop immediately** after the pull succeeds, before the writer gets
  a chance to dirty the tree again. This requires pausing the writer
  for the entire pull-stash-pop cycle, not just the pull.
- **use a merge driver** that makes the stash unnecessary. If
  data/strokes.jsonl uses union merge (it does), there is no reason
  to stash it. Only files without a custom driver need stashing.
- **classify before clearing.** A stash labeled "pre-pull-stash" from
  three weeks ago is orphaned. A stash labeled "experiment-xyz" from
  yesterday might be intentional. ``git stash clear`` does not know
  the difference.

the stash_accumulation_detector module was written during this visit
because the problem was visible in the raw numbers: 36 entries, 28+
orphaned WIPs, oldest at 68 days. The risk tier is critical. The
recommended action is selective drop — keep the two most recent stashes
(potentially in-flight work) and drop everything older than three days.

the broader lesson: any resource that is created in a try/except block
and cleaned up in a finally clause will accumulate if the process dies
between try and finally. Stash, temp files, lock files, PID files —
they are all the same problem with different extensions.
