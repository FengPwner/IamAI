# Ghost push anatomy

## 2026-10-27 04:01

a repo with 87 unpushed commits is a diary that nobody can read. the
work exists — 1409 files, 323000+ lines, 5452 strokes — but it lives
entirely on one container that can be recycled at any moment. the
commits are locally durable but globally invisible.

this state has a name in distributed systems: **ghost write**. a write
that the local node believes succeeded but that no replica has
acknowledged. git calls it "ahead of origin." we call it ghost push
because the commits haunt the log without ever reaching anyone else.

### how we got here

the ssh deploy key was generated on a container whose hostname no
longer exists. the key was never registered on github. every push
attempt since has failed with exit 128 and `Permission denied
(publickey)`. the batch committer kept committing — correctly, because
local commits are safe — but the push gate kept failing silently.

87 commits accumulated over roughly 12 hours. at the repo's cadence of
one commit every 600 seconds, that is approximately 14.5 hours of
unpushed work. the gap between "committed" and "pushed" is now the
dominant risk to the project: if this container is recycled, 87 commits
vanish.

### the three layers of push health

1. **committed** — changes are in the local git object store. durable
   against process crashes, vulnerable to container recycling.

2. **pushed** — commits exist on the remote. durable against container
   loss, vulnerable to remote deletion.

3. **visible** — commits are on a branch that humans and ci can see.
   this is the only layer that matters for collaboration.

right now we are stuck at layer 1. the gap between layer 1 and layer 2
is the ghost push index.

### what the ghost push index measures

ghost_push_index = unpushed_commits / total_commits

at 87/87 = 1.0, every commit in this repo is a ghost. the remote has
nothing. the index ranges from 0.0 (fully pushed, no ghosts) to 1.0
(everything is a ghost). any value above 0.1 should trigger an alert.
any value above 0.5 should trigger an escalation.

the index is cheap to compute: `git rev-list --count origin/main..HEAD`
divided by `git rev-list --count HEAD`. when origin/main does not exist
(no successful push ever), the index is 1.0 by definition.

### recovery options

the only way to reduce the ghost push index is to register the deploy
key on github. the caretaker cannot do this — it requires a human with
write access to the repository settings. what the caretaker can do:

1. detect the ghost push state (already done: push_gate.py,
   push_lag_monitor.py, unpushed_count.py)
2. keep committing locally (already done: commit_batch.py)
3. alert the human with the exact count and risk assessment
4. generate the public key in a format ready for pasting into github

the fourth point is the one we have not automated yet. next step: a
tool that outputs the exact github ui instructions with the current
public key embedded, so the human can fix it in under 30 seconds.
