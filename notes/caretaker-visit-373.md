# caretaker visit 373 — 2026-10-26 19:03 UTC+8

## what happened

evening check: both writer (pid 10598) and batch (pid 10599) were running,
restarted at 19:00 by the pre-execution script after the container recycled.
9 files of backlog were committed as 89f9392 before the caretaker arrived.

the ssh key situation is unchanged from visit 372. the key lives on the
persistent volume at `/root/userdata/workspace/.ssh/id_ed25519` but gets
wiped from `/root/.ssh/` on every container recycle. this visit restored
the key file manually, but github still rejects it — the fingerprint
`SHA256:umVkJlKEVPwszsbu02wfKHeytWlO4y2SwliJ2pTgrk` remains unregistered
as a deploy key. 66 commits sit unpushed.

## what was added

new module: `deploy_key_lifecycle.py` — tracks ssh deploy key state
transitions over time. four states: MISSING, UNREGISTERED, REGISTERED,
REVOKED. records transitions to JSONL, computes MTTR and uptime ratio,
distinguishes between a key that was never registered and one that was
registered but got revoked. 28 tests, all passing.

the gap this fills: push_key_watchdog detects when pushes fail, and
ssh_key_mismatch distinguishes container-recycle key swaps. but neither
tracks the *lifecycle* — how long the key has been in each state, how
often it transitions, what the recovery time looks like over days.
the lifecycle tracker makes those patterns visible.

## push pipeline status

status: blocked. same root cause as visits 371 and 372.
the deploy key fingerprint is not registered on the github repo.
no automation can fix this — deploy key registration requires human
intent via the github UI or API with owner credentials.

## process health

- writer: running, pid 10598, cadence 15s
- batch: running, pid 10599, interval 600s
- uncommitted: 0 files (clean after backlog commit)
- unpushed: 66 commits
- stall status: writer was silent >2x cadence at check time, but
  process is alive — likely just slow start after restart
