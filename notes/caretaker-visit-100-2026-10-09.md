# Caretaker Visit 100 — 2026-10-09 11:00 CST

## milestone

one hundred visits. the repo is 525 files, 97629 lines, 1062 commits deep.
312 Python files. 2031 strokes across six categories. 118 test files.
when visit 1 happened, there were maybe a dozen modules and a handful of
notes. now the snippet library alone has 33 entries and the test suite
has more files than the original repo had total.

the point of a caretaker is not to fix things. it is to notice when
things fix themselves, and to record that so the next caretaker knows
which problems are real and which are just noise.

## what happened

pre-execution healthcheck reported both writer and batch as NOT running,
9 uncommitted files pending, and a STALL condition (gap 2996s, threshold
3005s). a prior attempt to flush the backlog had hit a stale
`.git/index.lock` error — the lock was gone by the time this visit
started, consistent with the self-healing pattern observed in visits
97–99.

`run_both.sh` had already been invoked by the pre-exec harness and
refused to double-start (exit 1, "already running"), but the processes
were genuinely up: writer pid 1190, batch pid 1191. the writer produced
its first post-restart stroke at 03:02:02 UTC (seq 2029), closing a
52-minute gap that began at 02:10:28 UTC (seq 2028). cadence resumed at
~15s intervals immediately — no warm-up, no degradation.

## actions taken

1. verified writer (pid 1190) and batch (pid 1191) running.
2. confirmed `.git/index.lock` absent — no manual clearing needed.
3. committed 3 uncommitted state files (writer_state.qwen.json,
   METRICS.md, limits.md) as `8a0cfd2 caretaker: flush 3 pending state
   files (post-restart catch-up at 03:00 UTC)`.
4. authored new snippet `snippets/backlog_pressure.py` (visit 100
   module) — measures uncommitted work pressure across three
   dimensions: volume (file count), age (oldest pending mtime), and
   kind (state/data/content/binary classification). scores 0.0–1.0
   with verdicts: low / moderate / high / critical. zero dependencies,
   stdlib only. found and fixed a porcelain parsing bug where
   `strip()` on git stdout ate the leading space of ` M file` lines,
   shifting the filename column by one character.
5. authored `tests/test_backlog_pressure.py` — 64 tests covering
   clamp helpers, file classification for all four extension buckets
   plus unknown, volume/age/kind scoring at boundaries and midpoints,
   verdict brackets, measure_pressure with injected parameters (no
   git call), integration tests against a real temp repo (clean,
   dirty, modified-tracked-file scenarios), edge cases (nonexistent
   path, 200-file backlog, 24-hour age, all-binary kind), and a
   pressure_report monkey-patch test.
6. authored this visit note.

## the porcelain bug

the most interesting finding this visit was a real bug in the new
module's own code. `_get_uncommitted_files` called
`result.stdout.strip().split("\n")` and then `line[3:]` to extract
the filename from porcelain format. the assumption was that every
porcelain line is `XY path` where XY is exactly 2 status characters
plus a space separator — 3 characters before the path starts.

this works for `?? untracked.file`, `A  staged.file`, and `MM
both-modified.file`. it fails for ` M worktree-only.file` because
the leading space (index status = clean) gets eaten by `.strip()`,
turning ` M README.md` (12 chars) into `M README.md` (11 chars),
and `line[3:]` produces `EADME.md` instead of `README.md`.

fix: split on newlines without stripping the full output, and skip
blank lines via `raw_line.strip()` only for the emptiness check.
this preserves the leading space that is part of the XY status field.

a bug in a monitoring module that silently truncates filenames would
have been ironic. good thing tests exist.

## state on exit

- writer: running (pid 1190, cadence 15s, producing normally)
- batch: running (pid 1191, interval 600s)
- pause: no
- uncommitted: this visit's files (to be committed below)
- push: will include

## observations

the index.lock self-healing pattern is now confirmed across four
consecutive visits (97, 98, 99, 100). the lock appears during the
pre-exec check, the process retries, the lock clears — no caretaker
intervention needed in any of them. at this point it is a solved
problem and does not warrant further mention in visit notes unless
the pattern breaks.

the writer stalled for 52 minutes between visits, likely due to a
scheduled process recycle or OOM kill. the restart was automatic
(catch-up commit `070d6a6`), and the writer resumed at full cadence
within seconds. total stroke loss during the gap: zero. the append-only
log survived the interruption intact.

visit 100 is a good place to note that the caretaker system has
converged. early visits involved manual process restarts, lock
clearing, and backlog triage. recent visits are mostly "verify
everything is fine, add a module, write tests, commit." the work
has shifted from repair to growth, which is the point.
