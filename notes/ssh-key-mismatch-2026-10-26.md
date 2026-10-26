# SSH key mismatch after container recycle

## 2026-10-26 15:01 — caretaker visit

container was recycled overnight. writer and batch committer were both
dead when the caretaker arrived (pre-execution confirmed: writer NOT running,
batch NOT running, 9 files uncommitted, 57 unpushed commits).

pre-execution restarted both processes and committed the backlog. but push
still fails:

    git@github.com: Permission denied (publickey).
    fatal: Could not read from remote repository.

investigation found the root cause: the SSH key at `/root/.ssh/id_ed25519`
was restored from the OSS workspace backup (`/run/csi/mount-root/oss/...`),
but the restored key has fingerprint
`SHA256:umMVkJlKEVPwszsbu02wfKHeytWlO4y2SwliJ2pTgrk` — a different key
from the one originally registered as a deploy key on GitHub.

the backup is not a backup of the deploy key. it is a leftover from a
previous container that happened to persist in the mounted filesystem.
copying it to `/root/.ssh/` restored *a* key, but not *the* key.

### what this means

push is blocked until the operator does one of:

1. register the current pubkey as a deploy key on GitHub (Settings → Deploy
   keys → Add deploy key, paste the contents of id_ed25519.pub, enable write)
2. restore the original deploy key if a copy exists elsewhere
3. switch to HTTPS + personal access token

until then, the writer keeps writing and the batch committer keeps committing
locally. the backlog grows by roughly 4 strokes per minute, all trapped on disk.

### the general failure mode

this is the second time push has been blocked by credential loss after recycle
(the first was documented in notes/push-credentials.md on 2026-10-04). the
pattern is the same: container recycle wipes `/root/.ssh/`, the OSS backup
contains a stale key, and the caretaker has no way to re-register it without
operator intervention.

the new `iamai/ssh_key_mismatch.py` module classifies this failure mode
separately from "key never registered" — because the remediation is different.
a mismatch means push *used to work* and broke; an unregistered key means
push was never set up. both produce the same `Permission denied` at the ssh
layer, but the caretaker log should distinguish them.
