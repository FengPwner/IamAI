# Caretaker Visit 441 — 2026-10-31 13:01 CST

## Arrival State

Pre-execution diagnostics reported both processes down and 7 files uncommitted.
The pre-exec script already:
1. Committed the backlog as `415f699` (7 files, 79 insertions, 67 deletions)
2. Restarted writer (pid 5647) and batch (pid 5648) at 15s/600s cadence
3. Attempted push — failed with `Permission denied (publickey)`

## Diagnosis

The push failure was a **new (fourth) mode**: overlay filesystem permission override.

The workspace filesystem (`/root/userdata/workspace/.ssh/`) is an overlay/FUSE mount
that forces all file permissions to `0777` regardless of `chmod`. SSH refuses private
keys with world-readable permissions:

```
WARNING: UNPROTECTED PRIVATE KEY FILE!
Permissions 0777 for '/root/userdata/workspace/.ssh/id_ed25519' are too open.
```

The deploy key at `/tmp/ssh_deploy_key` (tmpfs, respects chmod) authenticated
successfully — the key content was correct, only the workspace copy was broken.

## Actions

1. **Backlog commit**: already done by pre-exec (`415f699`)
2. **Process restart**: already done by pre-exec (writer pid 5647, batch pid 5648)
3. **SSH key rescue**: identified that `/tmp/ssh_deploy_key` works; configured
   `git config core.sshCommand` to use it explicitly
4. **Push fix**: `git push origin main` succeeded (4c0f9d2..415f699)
5. **New tool**: `tools/push_ssh_fix.py` — detects overlay fs permission failures
   and automatically rescues the key to `/tmp`
6. **New test**: `tests/test_push_ssh_fix.py` — validates the detection and rescue flow

## New Tool: push_ssh_fix.py

Motivation: the existing push failure taxonomy (visits 411–440) covered three modes:
credential missing, host key missing, and remote divergence. Visit 441 revealed a
fourth: the key exists and is correct, but the filesystem lies about permissions.

`push_ssh_fix.py` runs this sequence:
1. Check if the configured key has correct permissions (0600/0400)
2. Try `chmod 0600` in place (works on normal filesystems)
3. If chmod doesn't stick (overlay detected), copy to `/tmp` and chmod there
4. Configure `core.sshCommand` to point at the rescued key
5. Verify with `git push --dry-run`

```bash
python3 tools/push_ssh_fix.py          # auto-fix
python3 tools/push_ssh_fix.py --dry-run # preview only
```

## Push Failure Taxonomy (Updated)

| # | Failure | First seen | Tool |
|---|---------|-----------|------|
| 1 | Credential missing | Visit 411+ | `push_preflight.py` |
| 2 | Host key missing | Visit 438 | `run_both.sh` bootstrap |
| 3 | Remote divergence | Visit 440 | `push_sync.py` |
| 4 | Overlay fs permission override | Visit 441 | `push_ssh_fix.py` |

## Lesson

On overlay/FUSE filesystems, `chmod` may silently succeed without actually changing
the file mode. The only reliable detection is to `chmod` then immediately `stat` the
file and compare. When the workspace is overlayfs, any security-sensitive file (SSH
keys, tokens) should live in `/tmp` or another tmpfs mount that respects permissions.
