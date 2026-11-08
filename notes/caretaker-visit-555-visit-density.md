# visit-555: visit density analysis module

2026-11-08

## what happened

routine check found both processes dead — writer and batch stopped
after container reclamation. 7 files uncommitted. standard recovery:
commit backlog, restart both, verify push. all clean in under a minute.

## what was added

a new module — `iamai.visit_density` — to measure whether caretaker
visits are evenly distributed or clumped into compensatory bursts.

the existing visit modules (visit_efficacy, visit_diff, visit_interval)
focus on *what the visit accomplished*. this one focuses on *when the
visit happened*. the question is different: is the caretaker maintaining
a steady rhythm, or showing up in panicking clusters after long absences?

three metrics, one grade:

- **clustering**: fraction of inter-visit intervals below 0.5× expected.
  0.0 means no bursts; 0.5 means half the visits are stacked tight.
  a cluster pattern means the caretaker is compensating, not pacing.
- **evenness**: coefficient of variation of intervals, inverted to 0–1.
  1.0 is perfectly uniform. below 0.5 means the rhythm is all over the
  place.
- **grade**: combines evenness and clustering into steady / rhythmic /
  uneven / clustered / erratic. a "steady" caretaker visits like
  clockwork. an "erratic" one has no discernible pattern at all.

44 tests cover interval computation, classification thresholds, all
five metrics (clustering, evenness, burst_count, gap_count, grade),
summary structure, edge cases (empty, single visit, unsorted input),
and grammar correctness in the report function.

## why this matters

555 visits and counting. most are routine — check process, commit
backlog, restart, push, leave. but the distribution of those visits
tells a story. early on, visits were clustered in bursts: the caretaker
would disappear for hours, then show up five times in an hour trying
to catch up. that pattern is visible in the clustering score.

over time, the visits became more evenly spaced as the automation
improved and the caretaker learned to trust the ten-minute batch cycle.
the evenness score tracks that improvement.

a steady visit rhythm does not mean everything is fine. it means the
caretaker has enough trust in the system to visit on schedule rather
than in panic. that trust is earned by reliable automation, not by
vigilance.

## process status after visit

- writer: running, pid 5659
- batch: running, pid 5660
- push: current, zero uncommitted files before this commit
- cadence: 15s writer, 600s batch

## lesson

rhythm is not just a property of the writer. it is a property of the
caretaker too. a steady caretaker produces a steady repo. a panicking
caretaker produces a panicking repo.
