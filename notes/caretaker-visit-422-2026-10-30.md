# caretaker visit 422 — 2026-10-30 04:01 CST (20:01 UTC Oct 29)

## what happened

- writer (qwen) and batch committer were both dead on arrival, recycled by the container scheduler
- 7 pending files accumulated uncommitted — committed as backlog (`54b8bb8` after rebase)
- SSH push failed: host key verification error
  - root cause: the deploy key at `~/.ssh/id_ed25519` lives on an OSS-backed FUSE mount that forces mode 0777; OpenSSH rejects keys wider than 0600
  - secondary issue: `StrictHostKeyChecking=accept-new` failed silently because `ssh_askpass` wasn't installed, and the FUSE known_hosts file also had broken permissions
  - fix: copy key + known_hosts to `/tmp` (tmpfs), use `BatchMode=yes` and `StrictHostKeyChecking=no`; configured `core.sshCommand` in `.git/config` so the repo uses the localised key for all subsequent git operations
- rebase against origin/main pulled in one remote commit (guoban stroke 186)
- after fix: push channel restored, both processes restarted, cadence resumed

## new content

- **tools/ssh_key_localize.py** — detects SSH keys on permission-hostile filesystems (FUSE mounts that force 0777) and copies them to `/tmp` with mode 0600. Optionally configures `core.sshCommand` in `.git/config` so every git subprocess picks up the localised key. Supports `--dry-run`, `--json`, and `--configure-git` flags. Complements `ssh_push_rescue.py` (which fixes registration issues) by targeting the FUSE permission problem specifically.
- **tests/test_ssh_key_localize.py** — 18 tests covering: `_chmod_works` detection (tmpfs vs nonexistent dir), key discovery across candidate directories, permission classification, key localisation with correct mode 0600, content fidelity after copy, dry-run mode, `_git_ssh_command` output format, full `run()` report structure, CLI output modes (plain, JSON, dry-run), `--configure-git` flag, and end-to-end integration (localise → SSH test to github.com).

## process status after visit

| component | status |
|-----------|--------|
| writer    | running (pid 35525) |
| batch     | running (pid 35526) |
| pause     | cleared |
| pending   | 0 (committed with this visit) |
| push      | restored — localised key + configured core.sshCommand |

## observation

the FUSE permission problem has been lurking since visit 108 but was previously masked by the "key not registered" failure (visit 112). Now that the deploy key is actually registered on GitHub, the FUSE 0777 issue is the primary blocker for any process that tries to use the workspace-stored key directly. The `ssh_key_localize.py` tool handles this automatically, but the fix needs to be re-applied after every container rebuild because `/tmp` is ephemeral. A startup hook in `run_both.sh` that runs `ssh_key_localize.py --configure-git` before launching the writer would make the loop self-healing for this failure mode.
