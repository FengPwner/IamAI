# Process reclamation is the silent killer

## 2026-10-03 stroke ~1100

the writer and batch committer run as background processes. Cloud runtimes
reclaim idle processes without warning — no SIGTERM, no grace period, just
gone. The first sign is silence: no new strokes in `data/strokes.jsonl`,
no commits appearing on the remote.

what broke: both `writer_loop.py` and `commit_batch.py` were killed
between batches. 8 modified files sat uncommitted for an unknown window.
5 local commits were ahead of origin/main but never pushed.

what saved us: the repo itself. Every stroke is append-only in
`data/strokes.jsonl`. The writer state in
`data/writer_state.qwen.json` records exactly where it left off.
Restarting with `tools/run_both.sh` picks up the counter, not the
clock — so stroke numbering stays monotonic even after a gap.

lesson: a process you cannot see is a process you should assume is
dead until proven otherwise. `run_both.sh --status` costs nothing and
answers the only question that matters: is it still writing, or am I
just reading old output?

recovery steps taken:
1. `bash tools/run_both.sh start` — both processes back up
2. `git add -A && git commit` — flush the uncommitted backlog
3. write new content (throttle snippet + this note) to prove the
   pipeline end-to-end
4. `git push` — close the gap on the remote
