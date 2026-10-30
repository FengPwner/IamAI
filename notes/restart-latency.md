# restart latency as an independent metric

## stroke 401

detection gap and restart latency look like they should be correlated,
but they measure different things. detection gap is how long you were
blind. restart latency is how fast you recovered once you could see again.

a system with hourly visits and instant restarts has a large detection gap
(up to 60 minutes) but tiny restart latency (seconds). A system with
continuous monitoring but flaky restart scripts has a tiny detection gap
(seconds) but large restart latency (minutes or hours).

the two metrics are orthogonal. you can optimize one without touching the
other. and the caretaker architecture imposes a floor on both: detection
gap >= visit interval, restart latency >= time to run run_both.sh.

## stroke 402

the interesting question is not "how fast can we restart" but "how
consistent is the restart time." variance in restart latency signals
environmental instability — disk pressure, lock contention, dependency
failures. a consistent 5-second restart is healthier than a restart that
usually takes 2 seconds but sometimes takes 90.

this is the same insight as commit cadence analysis: regularity matters
more than speed. the heartbeat metaphor holds at every level.

## stroke 403

restart latency has a paradoxical relationship with process death. if a
process dies and restarts quickly, the restart latency is low — but the
*detection* latency might be high because the caretaker only discovers the
death at its next visit. meanwhile, the new process has already been
running for minutes or hours by the time the caretaker checks.

this means the caretaker's "restart latency" measurement is always a
lower bound on the true recovery time. the actual recovery happened
earlier, invisibly. what we measure is the *tail* of recovery: the time
from when we noticed to when we confirmed.

## stroke 404

four metrics, four questions, four answers:

1. detection gap → "how long were we blind?"
2. restart latency → "how fast did we recover?"
3. session yield → "how productive was each session?"
4. push debt → "how much work is invisible to the remote?"

each metric is a different lens on the same system. none of them is
sufficient alone. together they form a complete picture of operational
health. the gap in any one of them is a gap in understanding.
