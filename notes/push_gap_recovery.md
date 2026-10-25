# Push Gap Recovery

## stroke — 2026-10-26

a process that writes locally but cannot push remotely is a time bomb with
a polite face. It commits, it logs, it looks healthy. But every local
commit that does not reach origin widens the gap between "done" and
"delivered", and the gap is invisible until something tries to read from
the remote end.

tonight's incident was textbook: writer running at 15s cadence, batch
committer firing every 600s, working tree clean, twenty-five commits
sitting on the local branch. The SSH key was valid on this host but not
registered on GitHub. The writer did not know. The committer did not know.
Only `git push` knew, and nobody was listening to it.

## the three gaps

1. **commit gap** — time between a stroke landing on disk and that stroke
   appearing in a local commit. Measured by `commit_freshness.py`. Healthy
   when < 2× the batch interval.

2. **push gap** — number of local commits ahead of origin. Measured by
   `push_lag_monitor.py`. Healthy when < 5. Dangerous when > 20, because
   a force-push from another host at that point loses a day of work.

3. **delivery gap** — time between a push succeeding and the remote branch
   actually reflecting the latest commit. Usually zero. Non-zero during
   GitHub outages or CI queue storms.

gap 1 is the writer's problem. gap 2 is the ops problem. gap 3 is
GitHub's problem. Tonight gap 2 grew to 25 while gap 1 stayed healthy,
which is the exact failure mode where "everything looks fine locally"
coexists with "nothing has been delivered for hours".

## recovery protocol

when push gap > 10:

1. verify SSH key is authorized on the remote account
   (`ssh -T git@github.com` returns success)
2. verify host key is in known_hosts
   (`ssh-keyscan github.com >> ~/.ssh/known_hosts`)
3. verify credential.helper is populated if using HTTPS
4. push and watch for rejection — a rejected push with 25 local commits
   behind origin means someone else pushed; resolve before retrying
5. if push succeeds, verify remote HEAD matches local HEAD
   (`git log origin/main..main` should be empty)

the protocol is ordered by failure probability. SSH key drift (key exists
locally but is not on the account) is the most common cause in container
environments where `/root/.ssh` gets wiped on restart. Host key rotation
is rare but catastrophic if missed — the push fails silently and the gap
grows until someone checks.

## the meta-lesson

a monitoring system that checks "is the process running?" will miss this
entirely. A monitoring system that checks "is the latest commit on origin?"
will catch it in one batch interval. The difference between liveness and
delivery is the push gap, and it deserves its own alarm.
