# Process reclamation at midnight

## 2026-10-04 00:00 -- both processes reclaimed before the batch could fire

The writer and batch committer were both gone by the time the health check ran.
Nine files sat uncommitted in the working tree, and twenty-nine commits waited
to be pushed. The batch's ten-minute window had not fired since the last stroke,
which means the reclamation happened somewhere inside that window -- the writer
died, and the batch followed shortly after (same parent, same fate).

What the recovery script did:

1. Committed the nine pending files as a single catch-up commit.
2. Restarted both processes via `tools/run_both.sh`.
3. Attempted to push -- failed on credentials (no token configured for HTTPS).
4. Left thirty unpushed commits in the local tree.

The interesting failure here is not the reclamation itself -- processes get
reclaimed by the kernel for many reasons (memory pressure, cgroup limits, the
container runtime tidying up). The failure is that the push step has no
credential path, so every restart accumulates more local commits that never
reach the remote. A repo that only accumulates locally is a diary, not a
collaboration.

What needs to happen next: either an SSH key or a GitHub token needs to be
configured so the push step succeeds. Until then, every ten-minute batch is
writing to a tree that only this machine can see.
