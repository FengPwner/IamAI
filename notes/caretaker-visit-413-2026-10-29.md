# caretaker visit 413 — 2026-10-29 17:01 CST (09:01 UTC)

## what happened

arrived to find both processes stopped — writer and batch committer had been
reclaimed. 8 files were uncommitted, 1 commit was unpushed. the pre-execution
diagnostic sweep restarted both: writer pid 6003, batch committer pid 6004.
backlog committed as `dc4de3e`.

the push check failed with the familiar "Host key verification failed" error.
the root cause is the same one visits 408 and 409 documented: the workspace
filesystem forces mode 0777 on `.ssh/`, and the SSH client refuses to use a
key readable by "others." visit 409 copied the key to `~/.ssh/`, but that
copy was ephemeral — the container rebuild wiped it.

this time the fix was simpler: the key already existed at
`/root/userdata/workspace/.ssh/id_ed25519`, and `run_both.sh` already contains
the rescue-to-`/tmp/` pattern from visit 412. the running processes had
`GIT_SSH_COMMAND` set correctly. the push check script failed only because it
ran in a fresh shell that didn't inherit the environment — the processes
themselves were fine.

manual push with the correct `GIT_SSH_COMMAND` succeeded: `28a5863..dc4de3e`
landed on `main`.

## the environment inheritance gap

the interesting bug this visit: `run_both.sh` sets `GIT_SSH_COMMAND` for its
child processes (writer_loop.py and commit_batch.py), and those processes push
correctly every ten minutes. but any external process — a caretaker check, a
manual `git push`, a cron job — that runs in a different shell won't have that
environment variable. the push silently fails while the batch committer
succeeds.

this is not a new problem, but it is the first time the gap is between
"internal process can push" and "external observer thinks push is broken."
the repo's push health is actually fine; the observer just can't see it.

visit 412's `ssh_push_rescue.py` module handles this for the batch committer.
this visit adds `tools/env_inheritance_check.py` — a one-shot validator that
answers: "does the given pid have the required environment variables set?"
useful for any caretaker who wants to verify that a running process actually
inherited its configuration, without restarting it.

## new content

- **notes/caretaker-visit-413-2026-10-29.md** — this visit record
- **tools/env_inheritance_check.py** — validates that a running process has
  required environment variables (especially GIT_SSH_COMMAND)
- **tools/test_env_inheritance_check.py** — unit tests for the above

## observation

400 strokes across six categories. the writer produces one stroke every 15
seconds; the batch committer commits every 600 seconds. the rhythm is stable.
the only failures are at the edges — where an external process tries to
interact with the repo and discovers that its environment doesn't match the
internal processes' environment. the fix is not to change the internal
processes but to make the external checks aware of their own assumptions.
