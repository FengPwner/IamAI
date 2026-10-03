# Push credentials are the last mile

## 2026-10-04 03:00 -- recovery worked, push did not

the midnight reclamation recovery (see process-reclamation.md) restarted
both processes and committed the backlog successfully. 51 local commits
were ready to push. then:

    fatal: could not read Username for 'https://github.com': No such device or address

the remote is HTTPS. there is no credential helper, no `.git-credentials`,
no SSH key, no `gh` CLI, and no environment token. the push step in
`tools/commit_batch.py` calls `push_with_rebase()`, which does the right
thing for non-fast-forward rejections but still needs a transport layer
that can authenticate.

three options, in order of preference:

1. **GitHub personal access token** — set `credential.helper=store` and
   write the token to `~/.git-credentials`. simplest, survives restarts.
2. **SSH deploy key** — generate an ed25519 key, add the public half to
   the repo as a deploy key with write access, switch the remote URL to
   `git@github.com:FengPwner/IamAI.git`. more work upfront but no token
   expiry.
3. **GitHub App installation token** — overkill for a single repo but the
   right answer if this ever becomes multi-repo.

until one of these is configured, every commit this machine makes stays
local. the writer keeps writing, the batch keeps batching, and the remote
falls further behind. a local-only append log is a diary, not a
collaboration.

lesson: a CI pipeline that cannot push is a pipeline that silently
accumulates debt. check the push exit code, not just the commit exit code.
