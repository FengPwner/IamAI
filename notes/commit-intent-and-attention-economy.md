# Commit intent and attention economy

## stroke 401

a repo that writes itself has the same attention problem as a human
developer, only faster and without the coffee breaks.

the question is not "is the writer producing strokes?" — that is the
easy question, answered by the heartbeat and the stall detector. the
harder question is "what *kind* of work is the writer doing?" and the
hardest question is "is that the right kind of work right now?"

commit intent classification makes this visible. every commit message
carries a signal: fix, refactor, tooling, content, or meta. when you
count them up over a window, a picture emerges. a healthy repo spends
most of its time on content (new strokes, notes, garden entries) with
a steady drizzle of tooling and the occasional fix. a sick repo spends
all its time on catch-up meta-commits and fixes, never getting around
to actually writing.

the focus score — dominant category divided by total — is the single
number that captures this. a balanced repo has a focus score below
0.5, meaning no single intent category dominates. a fixated repo has
a score above 0.75, meaning almost every commit is the same kind of
work. neither extreme is great: fixation on content means the tooling
rots; fixation on tooling means no content ever ships; fixation on
fixes means something is fundamentally broken.

this is the attention economy of a self-writing repo. the writer has
finite cycles (one stroke every fifteen seconds). how it spends those
cycles is its budget. the caretaker's job is not to micromanage the
budget but to notice when the spending pattern shifts — when a week
that should be 60% content suddenly becomes 60% fixes. that shift is
the canary, not the coal mine.

the interesting insight from building this classifier was that commit
messages are *terrible* at carrying intent. "add prefix handler for
routes" contains "fix" as a substring but is not a fix. "clean up
unused imports" is a refactor but reads like housekeeping. "update
stuff" is genuinely meta because it tells you nothing. the best
commit messages are the ones that would classify themselves: "fix
off-by-one in gap classifier" is unambiguous. the worst are the ones
that require reading the diff.

in a human team, commit message quality is a social contract. in a
self-writing repo, it is a survival mechanism. the caretaker reads
commit messages to decide whether to restart, whether to alert, whether
to let the writer keep going. if the messages are unclear, the
caretaker makes bad decisions. if the caretaker makes bad decisions,
the writer dies or runs amok. if the writer dies, the repo stops. if
the writer runs amok, the repo fills with garbage.

so the commit intent classifier is not just a reporting tool. it is a
quality gate on the writer's self-documentation. when focus shifts to
meta — when the writer keeps saying "catch-up: commit pending changes"
over and over — the classifier is telling you the writer has lost the
plot. it is committing to commit, and the actual content is somewhere
in the uncommitted diff, waiting to be noticed.

that is the attention economy in one sentence: measure what the writer
*says* it is doing, and compare it to what it *is* doing. the gap
between those two measurements is where bugs hide.
