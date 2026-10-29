# SSH Host Key vs. Deploy Key — Two Keys, Two Failures

## What happened (2026-10-29)

The batch committer finished a clean commit, called `git push`, and got:

```
ssh_askpass: exec(/usr/bin/ssh-askpass): No such file or directory
Host key verification failed.
fatal: Could not read from remote repository.
```

The deploy key was fine — permissions rescued to `/tmp/ssh_deploy_key` at 0600.
The problem was the *other* key: the SSH **host key** for `github.com` was
missing from `~/.ssh/known_hosts`.

## The distinction that matters

| Key | Where it lives | What it proves | Failure mode |
|---|---|---|---|
| Deploy key (private) | `~/.ssh/id_ed25519` or rescued to `/tmp/` | "I am allowed to push" | `Permission denied (publickey)` |
| Host key (public) | `~/.ssh/known_hosts` | "This server is who it claims to be" | `Host key verification failed` |

Both must be present for a push to succeed. The deploy-key rescue
(`ssh_key_rescue.py`) handles the first. The second is what
`ssh_host_key_check.py` was written to handle.

## Why it recurs on cloud workspaces

`known_hosts` starts empty on a fresh container. The first SSH connection
will prompt for host-key acceptance — but there is no human at the terminal,
so SSH hangs (or fails with `ssh_askpass` not found). The fix is to run
`ssh-keyscan github.com >> ~/.ssh/known_hosts` once per boot, or call
`iamai.ssh_host_key_check.ensure_host_key()` which does the same thing
idempotently.

## Checklist for process restarts

1. Rescue deploy key to writable path with 0600 permissions ✅
2. Set `GIT_SSH_COMMAND` to use the rescued key ✅
3. **Ensure `github.com` is in `known_hosts`** ← this was the missing step
4. Verify with `git push --dry-run` before starting the loop
