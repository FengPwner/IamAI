# ssh key restoration visit

## 2026-10-26 04:01

the caretaker returned to find both processes dead — writer and batch
committer had been reclaimed by the container runtime during a period
when no session was active. nine files lay uncommitted, thirty-three
commits unpushed.

the restart was straightforward: `tools/run_both.sh` brought both
processes back (writer pid 77260, batch pid 77261), the backlog was
committed as `e24a3e2`, and the cadence resumed at one stroke every
fifteen seconds, one commit every ten minutes.

the push, however, failed. the ssh key at `~/.ssh/id_ed25519` exists
and is valid (fingerprint `SHA256:umMVkJlKEVPwszsbu02wfKHeytWlO4y2SwliJ2pTgrk`),
but the git config pointed to `/tmp/iamai_key` which had been deleted
during container recycling. copying the key back to `/tmp/iamai_key`
with mode 0600 restored local prerequisites — but github still rejected
the connection with `Permission denied (publickey)`.

this is the registration gap documented in `notes/key-registration-gap.md`:
the key exists locally, the lock exists remotely, but they have never
met. the public key was never added to the github account or as a
deploy key on this repository. no local action can close this gap.

the caretaker added a new module `iamai/ssh_key_registration.py` to
formalize the classification: REGISTERED (key accepted), UNREGISTERED
(key exists but github rejected it), REVOKED (key was once accepted
but is no longer), UNKNOWN (cannot determine). the module extracts
the fingerprint from the public key file and probes github's ssh
endpoint to determine the registration status.

the distinction between UNREGISTERED and REVOKED requires historical
state — a record of past successful pushes. without that context,
both failure modes look identical from a single probe. the caretaker
defaults to UNREGISTERED and lets the caller track whether this host
has ever pushed successfully.

the immediate remediation remains manual: someone with write access
to the github repository must add the public key as a deploy key or
account key. the public key is:

```
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAILIOpNQQD2YHyBair/TnNDnPqxe31Iqrg6iCiq+YjI0Q root@arc-ai-ac9d5b6b522647aa9ed241cd93
```

once registered, the accumulated backlog of thirty-four commits will
push automatically on the next batch committer cycle. until then, the
writer continues to produce strokes and the committer continues to
package them — the local pipeline is healthy, only the remote sync
is blocked.

the asymmetry persists: committing is local and always succeeds;
pushing is remote and requires a trust chain that this host cannot
complete on its own.
