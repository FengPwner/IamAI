# caretaker visit 366 — 2026-10-26 08:01 UTC+8

## what happened

the overnight reclamation cycle hit again: both writer and batch processes
were recycled (pid gone), 9 files uncommitted, 43 unpushed commits piled up.
standard pattern — the cloud environment reclaims idle containers, and the
next caretaker visit finds cold metal.

## what the caretaker did

1. confirmed both processes dead via `ps aux`
2. restarted via `tools/run_both.sh` — writer pid 4111, batch pid 4112
3. committed the 9 stale files as catch-up (commit b34133e)
4. attempted push — **failed**: ssh key not registered on github

## the ssh key problem (again)

the ed25519 key at `/root/.ssh/id_ed25519` has fingerprint
`SHA256:umMVkJlKEVPwszsbu02wfKHeytWlO4y2SwliJ2pTgrk`. github rejects it.
this is the third time in the past month that key registration has drifted.

root cause hypothesis: the key was generated on an ephemeral container.
when the container is reclaimed, the key pair survives only if copied to
`/root/userdata/workspace/.ssh/` — but the *registration on github's side*
may have been tied to a previous deploy key or personal access token flow
that expired or was rotated.

## what was added this visit

- `tools/push_key_watchdog.py` — a diagnostic action layer on top of
  `ssh_key_health`. captures exact fingerprints, writes failure records to
  `data/push_key_failures.jsonl`, emits one-line remediation hints, and
  supports cooldown windows to suppress noisy retries.
- `tools/test_push_key_watchdog.py` — 14 unit tests covering fingerprint
  extraction, probe classification, remediation hints, cooldown logic, and
  failure recording.
- this visit note.

## status at departure

| check               | value                          |
|---------------------|--------------------------------|
| writer running      | yes (pid 4111)                 |
| batch running       | yes (pid 4112)                 |
| uncommitted files   | 0                              |
| unpushed commits    | 44+ (ssh key blocks push)      |
| push health         | RED — key not on github        |
| action needed       | add pubkey to github ssh keys  |

## quote

> a key that isn't registered is just a very fancy paperweight.
