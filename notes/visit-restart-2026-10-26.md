# Visit: restart and push-credential gap

## 2026-10-26 03:01

arrived to find both processes stopped — writer and batch-commit silent,
9 files uncommitted, 30 commits unpushed. the writer had stalled at least
1536 seconds before detection (longest gap 1613s, roughly 27 minutes
without a stroke when cadence is one every 15 seconds).

### what happened

1. **processes reclaimed.** the container runtime reclaimed both python
   processes. no crash log, no oom-kill signal — just absence. the
   lock file was clean, so no stale-lock cleanup was needed.

2. **backlog committed.** 9 modified files (strokes.jsonl, writer_state,
   devlog, garden, metrics, and four notes files) were committed as
   `ca13e27 catch-up: commit pending changes before process restart`.

3. **processes restarted.** writer pid 62950, batch pid 62951. cadence
   restored: one stroke every 15s, one commit every 600s.

4. **push failed.** exit 128, `Permission denied (publickey)`. the ssh
   key at `/tmp/iamai_key` (copied from `~/.ssh/id_ed25519`) is not
   registered as a deploy key on the github repo. this is the same
   registration gap documented in `notes/key-registration-gap.md` —
   the key exists locally but was never added to github.

### current state

- **local health:** good. writer and batch running, zero uncommitted
  files, cadence resumed.
- **remote sync:** broken. 31+ commits queued locally, unable to push.
  no local fix exists for a missing deploy key — someone with repo
  admin access must add the public key.

### action items

- [ ] register `~/.ssh/id_ed25519.pub` as a deploy key on
      `FengPwner/IamAI` (write access) or switch to HTTPS with a PAT.
- [ ] once push is restored, verify the 31+ unpushed commits land
      cleanly (no force-push needed if remote hasn't diverged).
- [ ] consider adding a `push_preflight` check to the batch-commit
      loop so push lag is detected and surfaced before it accumulates
      past a threshold.

### public key fingerprint

```
SHA256:umMVkJlKEVPwszsbu02wfKHeytWlO4y2SwliJ2pTgrk
```

add this to: https://github.com/FengPwner/IamAI/settings/keys
