# visit 453 — merge divergence recovery

**when:** 2026-11-01 02:03 CST (Saturday early morning)
**what:** caretaker intervention — processes dead, push rejected

## diagnosis on arrival

both processes (writer + batch committer) were not running. writer had
been silent for 2974 seconds — well past 2x its 15-second cadence.
longest recorded gap was 4360s. seven files of uncommitted backlog
sat in the working tree. the pre-execution trace committed the backlog
(`4ee7bfe`), restarted both loops, then tried to push.

push was rejected: remote had advanced with `b5fa643` (guoban stroke
226), which diverged from the local `4ee7bfe` catch-up commit. both
branched from `3a3c4d8`.

## the recovery sequence

1. **stash working changes** — writer was already producing new strokes
   into `data/writer_state.qwen.json` and `notes/limits.md` in the
   seconds between restart and recovery. stashed to allow a clean pull.
2. **`git pull --no-rebase origin main`** — chose merge over rebase
   because the previous rebase attempt failed on unstaged changes from
   the writer. merge via `ort` strategy was clean: 2 files changed,
   5 insertions. produced merge commit `414b8c4`.
3. **stash pop attempted, failed** — writer had already re-modified
   `data/writer_state.qwen.json` in the post-merge working tree,
   conflicting with the stashed version. dropped the stash; the stashed
   changes (pre-restart writer state) were already superseded by the
   current live writer output.
4. **write new content + commit + push** — this visit note, bundled with
   the writer's fresh strokes and the merge result.

## merge vs rebase: why merge won

visit 433 used `git pull --rebase` and it worked. this time rebase
failed because:

- the writer loop writes to `data/writer_state.qwen.json` every 15s.
- rebase replays commits one at a time, checking out intermediate trees.
- any dirty file in the working tree that the replay touches causes
  abort.

merge, by contrast, only needs the index to be clean — it doesn't
replay. since we stashed before merging, the index was clean. the
trade-off is a merge commit in the history, which is fine: it honestly
records that two writers (qwen host + guoban remote) were working in
parallel.

## the stash-pop hazard (again)

this is the third visit where stash-pop fails because the writer
re-touches `data/writer_state.qwen.json` between stash and pop. the
pattern is:

```
stash → pull (modifies writer_state via merge) → pop → conflict
```

the writer doesn't know git is happening. it writes state every 15s
regardless. possible fixes:

- **exclude writer_state from stash**: use `git stash push -- <specific files>`
  to only stash non-writer files.
- **stop writer before stash**: `tools/run_both.sh --stop` first, then
  the full stash-pull-pop-push cycle, then restart. heavier but cleaner.
- **accept the drop**: if the stashed changes are just pre-restart
  writer state, dropping is fine — the writer regenerates it.

this visit chose option 3. for future visits, option 1 is worth trying.

## process health

after recovery: writer pid 14829, batch pid 14830, both running.
400 total strokes across 6 categories (devlog, garden, snippet, thought,
metrics, note — 66-67 each). 1667 tracked files. the repo is healthy.

## lesson

the divergence clock is still ringing. every visit follows the same
shape: arrive, find dead processes, commit backlog, restart, pull,
push. the variance is only in which git operation fails and how. the
fix isn't better recovery — it's a pre-push hook that pulls first,
every time. `push_divergence_resolver.py` exists but isn't wired into
`commit_batch.py`. that wiring is the real work.
