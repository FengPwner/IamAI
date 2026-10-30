# caretaker visit 224 — 2026-10-19 09:00 GMT+8

## arrival state

overnight container recycle killed both processes again.  pre-execution
harness resurrected them (writer pid 5867, batch pid 5868) but the
index.lock from a crashed commit during the die-off blocked all
subsequent commits.  nine files sat uncommitted in the working tree,
and the batch process was silently failing every 600s retry cycle.

on arrival:

- writer: running (just restarted)
- batch:  running (just restarted)
- index.lock: stale, cleared manually
- uncommitted files: 9
- STALL flag active (overnight gap 1337s, longest 1677s — will clear
  as fresh strokes accumulate)

the lock file was the interesting failure here.  the batch process was
alive, CPU ticking, retry loop running — but every commit attempt hit
``fatal: Unable to create .git/index.lock: File exists`` and silently
failed.  from the outside, everything looked fine.  from the inside,
nothing was getting committed.

## what this visit adds

`iamai/batch_effectiveness.py` and its 32-test companion.  this module
tracks whether the batch committer is actually *succeeding*, not just
whether it's running.

the monitoring stack already has:

- `process_mortality` — is the process alive?
- `lock_health` — is there a stale lock blocking git?
- `commit_blockage` — why can't git commit right now?

these answer "is the committer running?" and "what's blocking it?"
but they don't answer "is it actually getting work done?"  a process
can be alive, the lock can be cleared by the time you check, and the
committer can still be failing for other reasons (network, permissions,
corrupt index).  batch_effectiveness tracks the *outcomes*.

### design

sliding window of the last N commit attempts (default 20).  each attempt
records success/failure, timestamp, and failure reason.  classification:

| verdict    | meaning                                    |
|------------|--------------------------------------------|
| healthy    | failure ratio < 20%                        |
| degraded   | failure ratio 20–60%                       |
| failing    | failure ratio ≥ 60% OR stuck streak (5+)   |
| dead       | no attempts in window                      |

the stuck streak is the key addition.  a committer that was healthy
for hours and just hit a lock file will show "healthy" by ratio
(19 successes, 1 failure = 5%) but "stuck streak" by recency (last
5 attempts all failed).  the verdict takes the worse of the two,
so the caretaker gets an early warning instead of a false all-clear.

### why not just check process_mortality?

process_mortality answers "is the pid alive?"  that's necessary but
not sufficient.  the batch process during this visit's incident was
perfectly alive — it just couldn't commit.  mortality would have
reported green while nine files rotted in the working tree.

batch_effectiveness is the layer above mortality: mortality says
"the committer is running"; effectiveness says "the committer is
actually committing."

## the monitoring stack, updated

```
process_mortality   →  is the process alive?
lock_health         →  is there a stale lock blocking git?
commit_blockage     →  why can't git commit right now?
batch_effectiveness →  is the committer actually succeeding?  (NEW)
cadence_adherence   →  is the writer on schedule?
heartbeat           →  is the writer alive right now?
tide                →  is the writer getting faster or slower?
stall_classifier   →  what kind of stall happened?
```

eight layers, each answering a different question at a different
level.  mortality/lock/blockage/effectiveness cover the commit
pipeline; cadence/heartbeat/tide/stall cover the writing pipeline.
together they give the caretaker full visibility from "is anything
running?" down to "is the writing actually happening and getting
committed?"

## process notes

the overnight die-off pattern is now well-understood: container
recycles, both processes die, lock file may or may not be left
behind depending on timing.  the pre-execution harness handles
resurrection cleanly.  the lock file cleanup is the one manual
step that still bites — batch_effectiveness will at least make
the silent failure visible faster next time.
