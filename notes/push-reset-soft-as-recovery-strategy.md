# push: reset --soft as divergence recovery strategy

2026-11-02 — caretaker visit 495

## the problem

The standard recovery for a diverged push is stash → rebase → pop → push.
This works when the working tree is clean and stays clean during the
operation. But when a writer process is actively producing strokes every
15 seconds, the tree is never clean — by the time you abort the rebase
and check `git status`, another file has been modified.

Six consecutive caretaker visits (489–495) hit this exact wall. The
rebase fails, the stash fails, and the caretaker ends up manually
stopping the writer, doing the git dance, then restarting. That's
three to five minutes of lost writing time per visit, and the writer's
rhythm score drops every time.

## the insight

`git reset --soft <target>` moves HEAD to the target commit but keeps
all your staged changes intact. It doesn't touch the working tree. It
doesn't need a clean tree. It doesn't care if a process is writing to
tracked files at that exact moment — the staged snapshot is already
captured.

So instead of:

    1. stop writer
    2. stash
    3. rebase origin/main
    4. pop stash (conflicts likely)
    5. resolve conflicts
    6. commit
    7. push
    8. restart writer

You can do:

    1. git reset --soft origin/main
    2. git commit -m "caretaker: fold local changes onto remote"
    3. git push

No process stop. No stash. No rebase conflicts. Three commands.

## why it works

The staged changes are the *diff* between your local HEAD and the
working tree. After `reset --soft origin/main`, HEAD moves to origin/main,
and the staged diff becomes "everything that was in your local commits
that isn't in origin/main." You recommit that diff as a single commit
on top of origin/main, which is exactly what a rebase would have
produced — just without the per-commit replay that causes conflicts.

## when it doesn't work

If both sides modified the same lines in the same file, you still get
a semantic conflict that the rebase would have surfaced as a text
conflict. The reset-soft approach silently merges them by preferring
your local version (since your staged diff overwrites the remote
content). For this repo, that's almost always the right answer —
strokes are append-only, and docs are additive. For a repo with
genuine semantic conflicts, this technique would mask bugs.

## integration target

commit_batch.py already calls pre_push_sync before pushing. The next
step is to add a fallback: if push_with_rebase fails, try reset-soft
before giving up and waiting for the next caretaker visit. The
implementation is roughly:

    result = push.push_with_rebase(REPO)
    if result["strategy"] != "push":
        # fallback: reset-soft onto remote, recommit, push
        run_git("fetch", "origin", MAIN)
        run_git("reset", "--soft", f"origin/{MAIN}")
        run_git("commit", "-m", "batch: reset-soft recovery after rebase failure")
        result = push.push(REPO)

This would eliminate the need for caretaker visits to resolve push
divergence entirely, which would finally let the overnight gap close
to just the natural writer cadence.
