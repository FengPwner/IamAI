# Commit file overlap

## stroke 401

the question is not "how much did we change" but "how much did we change
the same thing twice." a repo that touches fifty different files across
ten commits is exploring. a repo that touches the same three files across
ten commits is stuck in a loop. the total file count hides this; only
the overlap between consecutive commits reveals it.

overlap is the Jaccard similarity between file sets of adjacent commits.
a score of 1.0 means commit N+1 touched exactly the same files as commit
N — pure reworking. a score of 0.0 means they share nothing — pure
exploration. most real work lives somewhere between 0.1 and 0.4, the
iterating zone where you revisit a file for a second pass and then move
on to something new.

the interesting signal is the trend. a repo whose overlap drifts from
0.3 toward 0.6 is tightening its focus — either converging on a solution
or getting stuck in a repair loop. a repo whose overlap drops from 0.3
toward 0.05 is scattering attention — each commit lands in a different
corner of the tree. neither extreme is healthy on its own.

this metric complements commit_breadth (how wide is each commit) and
repo_churn (which files are hot overall) by measuring the thing neither
can: whether consecutive commits are about the same work or different
work. breadth says "this commit touches five areas." churn says "these
three files change a lot." overlap says "the last four commits all
touched those same three files, and that is either focus or a problem."

for IamAI specifically, the healthy range is 0.10–0.25. the automated
writer produces strokes that touch data/, notes/, docs/, and tests/ in
rotation, so consecutive commits rarely share files unless the caretaker
is fixing something. when overlap spikes above 0.40, it usually means
a lock file or state file got stuck and the writer kept retrying the same
path. the metric is a canary for mechanical problems, not editorial ones.
