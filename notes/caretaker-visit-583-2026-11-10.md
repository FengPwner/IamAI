# visit 583 — escalation relay

**when:** 2026-11-10 ~00:02 CST
**what happened:** both writer (pid 3547) and batch_committer (pid 3548) had
been recycled since the last visit. 7 files uncommitted, longest gap 3209 s
(writer silent >2x its cadence). the pre-execution probe restarted both
processes and pushed the backlog (commit 6fd0ccc).

**actions taken:**
1. verified processes running — writer pid 3594, batch pid 3595, both alive
2. confirmed backlog committed and pushed (6fd0ccc → origin/main)
3. wrote a new module — `escalation_relay` — bridges HeartbeatEscalation to
   supervisor callbacks. polls the escalation level on each tick, deduplicates
   transitions, isolates callback failures, and suppresses ok-level noise by
   default. 38 tests covering construction, escalation chains, de-escalation,
   error isolation, force_fire, reset, transitions tracking, and full lifecycle
   integration.
4. committed and pushed everything

**observation:** visit 582 noted that escalation was recording-only — "the
escalation actually triggers alerts rather than just recording them." this
module answers that gap. the relay's poll-based design means it can be dropped
onto any existing HeartbeatEscalation instance without rewiring call sites.
next step: wire EscalationRelay into the supervisor loop (process_supervisor.py)
so that yellow/red/critical transitions trigger actual recovery actions
(restart, notify, escalate to caretaker).

**files added:**
- `snippets/escalation_relay.py`
- `tests/test_escalation_relay.py`
