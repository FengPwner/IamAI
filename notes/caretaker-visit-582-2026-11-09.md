# visit 582 — heartbeat escalation

**when:** 2026-11-09 ~23:01 CST
**what happened:** both writer and batch_committer had been recycled. 7 files
uncommitted, longest gap 3192 s (writer silent >2× its cadence).

**actions taken:**
1. committed the 7-file backlog (commit 43064aa)
2. rescued the SSH deploy key to /tmp, restarted writer (pid 3547) and
   batch_committer (pid 3548)
3. pushed the backlog commit to origin/main
4. wrote a new module — `heartbeat_escalation` — tiered alert escalation
   driven by consecutive missed heartbeats. ok → yellow → red → critical,
   no de-escalation without a fresh ping. 42 tests.
5. committed and pushed everything

**observation:** the writer process died silently again — no crash log, no
exit code. the deadman module (058) would have caught this if it had been
wired in. next visit: consider wiring deadman → heartbeat_escalation into
the supervisor loop so the escalation actually triggers alerts rather than
just recording them.

**files added:**
- `snippets/heartbeat_escalation.py`
- `tests/test_heartbeat_escalation.py`
