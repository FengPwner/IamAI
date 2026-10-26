# caretaker visit 371 — 2026-10-26 17:03 UTC+8

## what happened

afternoon check: both writer and batch processes were dead — container
recycled again since the last visit (368, five hours ago). 9 files
uncommitted, 61 commits piled up unpushed. pre-execution diagnostics
handled the restart and backlog commit before the caretaker even arrived.

the ssh key situation is the same story: the key file survives on the
persistent volume at `/root/userdata/workspace/.ssh/id_ed25519`, but
`/root/.ssh/` is wiped on every recycle. the pre-execution script copied
the key back, but github still rejects it — the fingerprint
`SHA256:umMVkJlKEVPwszsbu02wfKHeytWlO4y2SwliJ2pTgrk` is not registered
as a deploy key on the repo.

this is the fifth time today the push pipeline has hit amber state.
the pattern is clear: container recycles faster than deploy keys can
be re-registered, and no automation can bridge that gap without human
intent on the github side.

## what the caretaker did

1. verified pre-execution had already restarted both processes:
   writer pid 7448, batch pid 7449.
2. confirmed backlog commit `40dfb7e` bundled the 9 uncommitted files.
3. checked ssh key recovery — key was already restored by pre-execution.
4. tested push — **still fails**: key not registered (exit 128).
5. wrote new module `iamai/push_recovery_orchestrator.py` — chains
   health check, key recovery, github probe, and push attempt into
   a single `orchestrate()` call. caretakers and cron jobs can invoke
   it without knowing the internal module topology.
6. wrote 38 tests in `tests/test_push_recovery_orchestrator.py`
   covering all five pipeline outcomes (success, key_missing,
   key_unregistered, push_failed, network_error) plus edge cases.
7. committed everything together.

## the push_recovery_orchestrator module

the existing modules — ssh_key_health, push_key_recovery,
ssh_key_registration, push_key_watchdog — each solve one piece of the
push problem. but a caretaker arriving at a broken repo needs to run
all of them in sequence, interpreting each result before deciding the
next step. the orchestrator removes that ceremony:

```python
from iamai.push_recovery_orchestrator import orchestrate

report = orchestrate()
if report.push_succeeded:
    print("all clear")
else:
    print(report.remediation)
```

the report carries enough context for downstream automation: which
pipeline step was reached, whether human action is needed, and the
exact remediation text to surface to the repo owner.

## current state

- writer[qwen]: running pid 7448
- batch [qwen]: running pid 7449
- unpushed commits: 62+ (stuck behind ssh key)
- push: AMBER (key present, not registered)
- backlog risk: CRITICAL

## action needed

the repo owner needs to add the public key as a deploy key at
`https://github.com/FengPwner/IamAI/settings/keys`. once registered,
run `python3 tools/push_preflight.py` to confirm exit 0, then
`git push origin main` to flush the backlog.

until then, every container recycle risks losing hours of accumulated
work. the orchestrator module makes this failure loud and precise,
but it cannot fix a registration gap that requires human intent.
