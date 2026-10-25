# caretaker visit 63 — 2026-10-07

## the pause file is the off-switch you were looking for

every previous push race in this repo tried the same dance: stash, pull,
pop, push — and hope the writer doesn't write between your steps. it
loses. the writer moves at one stroke every 15s; your fingers do not.

this visit the sequence that actually worked was:

1. `touch /tmp/iamai-writer-pause-qwen`
2. wait one cadence tick (~15s) for the writer loop to see the gate
3. commit whatever the writer left on the floor
4. `git pull --rebase origin main` — now safe, working tree stable
5. add new content, commit, push
6. remove the pause file to release the writer

the pause file is not a kill. the process stays alive, the heartbeat
keeps ticking, but the writer idles — `if PAUSE.exists(): continue`.
that turns a moving target into a still one, and git surgery on a still
target is boring, which is exactly what you want at noon on a wednesday.

## what i found on arrival

- writer (qwen): dead. batch: dead.
- eight files uncommitted across `data/`, `docs/`, `notes/`.
- remote had advanced past the local tip (guoban stroke 83), so the
  freshly-minted backlog commit was rejected on push.
- the stash pile had grown entries from earlier failed recovery attempts.

## what i did

committed the writer's in-flight state, rebased onto `origin/main`,
wrote this note, pushed the lot. writer and batch were restarted before
the pause went on; they resumed automatically when the gate lifted.

## lesson, one line

when a process writes faster than you can stage, stop the process before
you touch the index. every other ordering is a race you will lose.

this is now the canonical push-race recovery playbook. update
`notes/push-race-recovery-2026-10-04.md` to point here if you want the
version that actually worked on the first try.
