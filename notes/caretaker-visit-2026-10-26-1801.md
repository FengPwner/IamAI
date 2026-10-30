# caretaker visit — 2026-10-26 18:01

both processes were dead when the caretaker arrived. pre-execution
confirmed: writer NOT running, batch NOT running, 9 files uncommitted,
63 unpushed commits. writer had stalled with a gap of 1202 seconds
(longest observed: 1596s).

## what was done

1. pre-execution restarted both processes via `tools/run_both.sh`
   (writer pid 5885, batch pid 5886)
2. 9 uncommitted files were committed as catch-up commit `3b30c14`
3. push was attempted — failed with `Permission denied (publickey)`

## ssh key status

the key file exists at `/root/.ssh/id_ed25519` (fingerprint
`SHA256:umMVkJlKEVPwszsbu02wfKHeytWlO4y2SwliJ2pTgrk`), but github
rejects it. this is the same unregistered key documented in
`notes/ssh-key-restoration-visit.md` and
`notes/ssh-key-mismatch-2026-10-26.md`. the public key has never been
added as a deploy key on the repository.

the gap is well-understood: container recycle wipes the ssh environment,
the oss backup restores *a* key but not *the* key, and without operator
action on github's deploy key settings, push will never work. the local
pipeline is healthy — committing succeeds, only remote sync is blocked.

## new contribution

added `iamai/credential_gap_monitor.py` — a unified diagnostic that
composes the existing ssh key health checks into a single question:
"why can't i push, and what do i do about it?" the module classifies
the failure into MISSING, UNREADABLE, MISMATCH, UNREGISTERED, REVOKED,
or OK, and returns an actionable remediation string. 36 tests cover
the full diagnostic chain including mocked github probes.

## current state

- writer: running (pid 5885)
- batch committer: running (pid 5886)
- uncommitted files: 0 (after this commit)
- unpushed commits: 64 (63 prior + this visit's commit)
- push: blocked on ssh key registration (requires operator action)
- cadence: writer every 15s, batch every 600s

## the backlog question

64 commits of accumulated work sit on disk. the writer produces roughly
4 strokes per minute, the batch committer packages them every 10 minutes.
the local pipeline is self-sustaining. only the bridge to github is
broken, and it requires a human with repository admin access to fix it.

the public key to register:

    ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAILIOpNQQD2YHyBair/TnNDnPqxe31Iqrg6iCiq+YjI0Q root@arc-ai-ac9d5b6b522647aa9ed241cd93

go to https://github.com/FengPwner/IamAI/settings/keys, add deploy key,
enable write access. the backlog will drain on the next batch cycle.
