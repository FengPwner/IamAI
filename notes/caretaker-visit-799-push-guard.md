# visit 799 — push guard: atomic push-recovery sequence

2026-11-22 22:03 CST. human-requested caretaker check.

## context

writer and batch found dead on arrival — hosting environment had
recycled the container. 7 uncommitted files flushed as catch-up
commit bfc42e3, processes restarted (pids 3922/3923). push rejected
as expected: remote had guoban stroke 318 (1813c09) which local did
not yet know about.

the recovery sequence is now muscle memory: stash writer's dirty
state → pull --rebase → pop stash → push. but "muscle memory"
means it lives in a human's head, not in code. visit 798 added
the death clock to record *when* processes die; this visit adds
the push guard to automate *what to do after* they come back.

## what this visit adds

### tools/push_guard.py

a single-function wrapper — `guarded_push()` — that encodes the
full push-recovery dance:

1. detect dirty working tree; stash if needed.
2. pull --rebase origin main.
3. pop stash if one was created.
4. push origin main.
5. if push is rejected (non-fast-forward), pull --rebase once
   more and retry push (max 2 attempts).

returns a dict with keys: `ok` (bool), `stash_used` (bool),
`rebase_count` (int), `push_attempts` (int), `error` (str or None).

design choices:
- uses subprocess.run throughout; no porcelain parsing.
- timeout per git command: 60s (repo is large, gc runs in background).
- refuses to force-push; if 2 attempts fail, caller must decide.
- logs each step to stderr for caretaker debugging.

### test_push_guard.py

18 tests covering:

- clean tree: no stash created, push succeeds
- dirty tree: stash created and popped
- first push rejected: rebase + retry succeeds
- both pushes rejected: returns error without force
- pull fails (network): returns error with stderr captured
- timeout: returns error with timeout message
- rebase conflict: returns error, leaves tree for human
- edge cases: no remote configured, detached HEAD

### why not just use safe_push_cli?

visit 256 identified that the push race is "a clock, not a bug."
safe_push_cli exists but is not wired into commit_batch.py's
main loop. push_guard is a smaller, more composable primitive:
the commit batch can call it after each batch interval without
needing to know about stashing or rebasing. safe_push_cli can
be refactored to call push_guard internally.

## process state at visit time

```
writer[qwen]: running pid 3922
batch [qwen]: running pid 3923
pending: 2 files (writer_state + METRICS, normal drift)
tracked: 2638 files
strokes: 6948 lines in strokes.jsonl
```

## observation

the pattern across visits 798 and 799 is converging: each visit
adds one diagnostic tool (death clock) and one recovery tool
(push guard). the diagnostic tells you what went wrong; the
recovery fixes it. the next logical step is a single caretaker
script that runs both in sequence — detect death, record it,
recover push, resume cadence. that script would be visit 800.
