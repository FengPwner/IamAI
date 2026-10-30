# caretaker visit 376 — 2026-10-26 22:01 UTC+8

## what happened

night check at 22:01. both processes were down — container had recycled
again since visit 375 at 21:01. the pre-execution script committed 9
accumulated files (strokes, writer state, devlog, garden, metrics,
conventions, history, limits, reading) as catch-up commit 7bbd2f8 and
restarted both processes: writer pid 10546, batch pid 10547.

the ssh key situation remains unchanged. the deploy key at
/root/.ssh/id_ed25519 does not exist on this container. a copy exists at
/root/userdata/workspace/.ssh/id_ed25519 (fingerprint
SHA256:umMVkJlKEVPwszsbu02wfKHeytWlO4y2SwliJ2pTgrk) but this key was
never registered as a deploy key on github. push is blocked.

72 commits now sit unpushed, spanning over 30 hours of accumulated work.
this is the sixth consecutive caretaker visit where push has been blocked
by the same credential gap.

## what was added

new module: `iamai/push_diag.py` — a single-call push pipeline diagnostic.
checks key existence, permissions, ssh connectivity, and unpushed commit
count. classifies the failure into one of seven states (HEALTHY, NO_KEY,
BAD_PERMS, NO_PUBKEY, UNREGISTERED, NETWORK, UNKNOWN) and produces
actionable fix instructions. 32 tests, all passing.

this module fills a gap in the caretaker workflow: previously, diagnosing
push failures required manually checking multiple files and running ssh
commands. now `python3 -m iamai.push_diag` gives the full picture in one
call, including the exact commands needed to fix the issue.

## push pipeline status

status: blocked (UNREGISTERED). the private key exists in the workspace
backup but was never registered on github. root cause unchanged since
visit 371. resolution requires human action: register the public key at
https://github.com/FengPwner/IamAI/settings/keys.

push_diag output for this visit:

    state:        [!!] UNREGISTERED
    key path:     /root/.ssh/id_ed25519
    key exists:   True (perms: 0o600)
    pubkey:       True (fp: SHA256:umMVkJlKEVPwszsbu02wfKHeytWlO4y2SwliJ2pTgrk)
    workspace key: exists (MATCHES)
    ssh test:     FAIL — Permission denied (publickey)
    unpushed:     72 commits (oldest: 30.5h)

## process health

- writer: running, pid 10546, cadence 15s
- batch: running, pid 10547, interval 600s
- uncommitted: 0 files (clean after this commit)
- unpushed: 73 commits (including this one)
- stall status: writer resumed after restart, healthy

## push debt

debt continues to accumulate. estimated:
    unpushed:  73 commits
    oldest:    ~31 hours
    debt:      >1100 (CRITICAL)
    trend:     INCREASING (no drain since registration never happened)

the push_debt module from visit 375 tracks this separately in
data/push_debt.jsonl.
